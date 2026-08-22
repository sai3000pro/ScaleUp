"""Course CRUD, PDF upload, deduplication, and job polling."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import Document, IngestJob
from tests.fixtures.sample_pdf import build_sample_pdf

CREDENTIALS = {"email": "learner@example.com", "password": "hunter22-long-enough", "display_name": "Learner"}


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/auth/register", json=CREDENTIALS)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def course_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    response = await client.post("/api/courses", json={"title": "Linear Algebra"}, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_created_course_starts_empty(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/courses",
        json={"title": "Linear Algebra", "description": "Strang"},
        headers=auth_headers,
    )
    body = response.json()
    assert body["status"] == "draft"
    assert body["node_count"] == 0
    assert body["edge_count"] == 0
    assert body["graph_version"] == 0


async def test_courses_are_scoped_to_their_owner(client: AsyncClient, auth_headers: dict[str, str], course_id: str) -> None:
    other = await client.post(
        "/api/auth/register",
        json={"email": "stranger@example.com", "password": "hunter22-long-enough", "display_name": "Stranger"},
    )
    stranger_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert (await client.get("/api/courses", headers=stranger_headers)).json()["courses"] == []
    # 404 rather than 403: a 403 would confirm the id exists.
    assert (await client.get(f"/api/courses/{course_id}", headers=stranger_headers)).status_code == 404


async def test_upload_is_accepted_and_queued(client: AsyncClient, auth_headers: dict[str, str], course_id: str) -> None:
    response = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth_headers,
        files={"file": ("linear-algebra.pdf", build_sample_pdf(), "application/pdf")},
    )
    assert response.status_code == 202, response.text

    body = response.json()
    assert body["deduplicated"] is False
    assert body["document"]["filename"] == "linear-algebra.pdf"

    job = await client.get(f"/api/jobs/{body['job_id']}", headers=auth_headers)
    assert job.status_code == 200
    assert job.json()["state"] in {"queued", "parsing", "succeeded"}
    # Queue time and worker start time are different facts. A queued job has not
    # started yet; once a worker enters a stage, the API must expose that time.
    if job.json()["state"] != "queued":
        assert job.json()["started_at"] is not None
    if job.json()["state"] == "succeeded":
        assert job.json()["finished_at"] is not None

    # `ingesting` the moment the upload is accepted, so the UI can react; the
    # pipeline flips it to `ready` once the graph is committed. Under eager
    # Celery in tests, that has already happened by the time we look.
    course = await client.get(f"/api/courses/{course_id}", headers=auth_headers)
    assert course.json()["status"] in {"ingesting", "ready"}
    assert len(course.json()["documents"]) == 1


async def test_reuploading_identical_bytes_dedupes(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    payload = build_sample_pdf()
    files = {"file": ("linear-algebra.pdf", payload, "application/pdf")}

    first = await client.post(f"/api/courses/{course_id}/documents", headers=auth_headers, files=files)
    second = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth_headers,
        files={"file": ("renamed.pdf", payload, "application/pdf")},
    )

    assert second.status_code == 202
    assert second.json()["deduplicated"] is True
    # Same document and same job -- a second ingest never starts.
    assert second.json()["document"]["id"] == first.json()["document"]["id"]
    assert second.json()["job_id"] == first.json()["job_id"]

    course = await client.get(f"/api/courses/{course_id}", headers=auth_headers)
    assert len(course.json()["documents"]) == 1


async def test_non_pdf_upload_is_rejected_on_magic_bytes(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    """The filename and content-type both claim PDF; the bytes do not."""
    response = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth_headers,
        files={"file": ("totally-a.pdf", b"MZ\x90\x00 this is an exe", "application/pdf")},
    )
    assert response.status_code == 415


async def test_empty_upload_is_rejected(client: AsyncClient, auth_headers: dict[str, str], course_id: str) -> None:
    response = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth_headers,
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


async def test_failed_job_can_be_retried_without_reuploading_the_source(
    client: AsyncClient,
    auth_headers: dict[str, str],
    course_id: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retry uses the server's stored document rather than browser state or a new fetch."""
    from app.tasks import ingest as ingest_tasks

    course_uuid = uuid.UUID(course_id)
    stored_path = tmp_path / "stored.pdf"
    stored_path.write_bytes(build_sample_pdf())
    called: list[str] = []

    class FakeResult:
        id = "retry-celery-id"

    def fake_delay(job_id: str) -> FakeResult:
        called.append(job_id)
        return FakeResult()

    monkeypatch.setattr(ingest_tasks.run_ingest_pipeline, "delay", fake_delay)

    with sync_session() as session:
        document = Document(
            course_id=course_uuid,
            source_type="pdf",
            filename="stored.pdf",
            content_sha256="a" * 64,
            storage_path=str(stored_path),
            byte_size=123,
        )
        session.add(document)
        session.flush()
        failed = IngestJob(
            course_id=course_uuid,
            document_id=document.id,
            kind="ingest",
            idempotency_key="b" * 64,
            state="failed",
            error="SchemaValidationError: retry me",
        )
        session.add(failed)
        session.flush()
        failed_id = failed.id

    response = await client.post(f"/api/jobs/{failed_id}/retry", headers=auth_headers)
    assert response.status_code == 202, response.text
    accepted = response.json()
    document_id = uuid.UUID(accepted["document"]["id"])
    assert accepted["deduplicated"] is False
    assert accepted["document"]["id"]
    assert accepted["job_id"] != str(failed_id)
    assert called == [accepted["job_id"]]

    with sync_session() as session:
        jobs = session.scalars(
            select(IngestJob).where(IngestJob.document_id == document_id)
        ).all()
        assert len(jobs) == 2
        retry = session.get(IngestJob, uuid.UUID(accepted["job_id"]))
        assert retry.state == "queued"
        assert retry.celery_root_id == "retry-celery-id"

    conflict = await client.post(f"/api/jobs/{accepted['job_id']}/retry", headers=auth_headers)
    assert conflict.status_code == 409


async def test_job_is_not_readable_by_another_user(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    upload = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth_headers,
        files={"file": ("doc.pdf", build_sample_pdf(), "application/pdf")},
    )
    other = await client.post(
        "/api/auth/register",
        json={"email": "nosy@example.com", "password": "hunter22-long-enough", "display_name": "Nosy"},
    )
    stranger_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = await client.get(f"/api/jobs/{upload.json()['job_id']}", headers=stranger_headers)
    assert response.status_code == 404

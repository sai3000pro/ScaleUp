"""The ingest pipeline against real Postgres and real Chroma, with fake embeddings."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import Chunk, Document, DocumentPage, IngestJob
from app.vector.chroma_store import get_vector_store
from tests.fixtures.sample_pdf import build_sample_pdf

CREDENTIALS = {"email": "ingest@example.com", "password": "hunter22-long-enough", "display_name": "Ingest"}


@pytest.fixture
async def ingested(client: AsyncClient) -> dict:
    """Upload the sample PDF and let the eager task run it to completion."""
    registered = await client.post("/api/auth/register", json=CREDENTIALS)
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    course = await client.post("/api/courses", json={"title": "Ingest Test"}, headers=headers)
    course_id = course.json()["id"]

    upload = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=headers,
        files={"file": ("sample.pdf", build_sample_pdf(), "application/pdf")},
    )
    assert upload.status_code == 202, upload.text

    job = await client.get(f"/api/jobs/{upload.json()['job_id']}", headers=headers)
    return {
        "course_id": uuid.UUID(course_id),
        "document_id": uuid.UUID(upload.json()["document"]["id"]),
        "job": job.json(),
        "headers": headers,
    }


def test_job_reaches_succeeded(ingested: dict) -> None:
    job = ingested["job"]
    assert job["state"] == "succeeded", job
    assert job["percent"] == 100.0


def test_stage_detail_reports_real_counts(ingested: dict) -> None:
    detail = ingested["job"]["stage_detail"]
    assert detail["pages"] >= 1
    assert detail["chunks"] >= 1
    # Everything chunked was embedded.
    assert detail["embedded"] == detail["chunks"]


def test_pages_and_chunks_are_persisted(ingested: dict) -> None:
    with sync_session() as session:
        pages = session.scalars(
            select(DocumentPage).where(DocumentPage.document_id == ingested["document_id"])
        ).all()
        chunks = session.scalars(select(Chunk).where(Chunk.document_id == ingested["document_id"])).all()
        document = session.get(Document, ingested["document_id"])

    assert pages, "no document_pages written"
    assert chunks, "no chunks written"
    assert document.page_count == len(pages)
    # Ordinals dense and ordered.
    assert [c.ordinal for c in sorted(chunks, key=lambda c: c.ordinal)] == list(range(len(chunks)))


def test_chunks_carry_section_paths_from_heading_detection(ingested: dict) -> None:
    """If this regresses, the extraction prompt loses its best disambiguator."""
    with sync_session() as session:
        chunks = session.scalars(select(Chunk).where(Chunk.document_id == ingested["document_id"])).all()

    paths = [c.section_path for c in chunks]
    assert all(paths), f"chunks missing section_path: {paths}"
    assert any("1.1" in (p or "") for p in paths), paths


def test_vectors_land_in_chroma(ingested: dict) -> None:
    with sync_session() as session:
        chunks = session.scalars(select(Chunk).where(Chunk.course_id == ingested["course_id"])).all()

    store = get_vector_store()
    assert store.count(str(ingested["course_id"])) == len(chunks)
    assert all(chunk.vector_id for chunk in chunks)


def test_retrieval_returns_a_relevant_chunk(ingested: dict) -> None:
    """Round-trips the embedding path: embed a query, get chunks back."""
    from app.ingestion.embed import embed_texts

    [query_vector] = embed_texts(["dot product perpendicular orthogonality"])
    hits = get_vector_store().query(str(ingested["course_id"]), query_vector, k=3)

    assert hits
    assert all(-1.0 <= hit.score <= 1.0 for hit in hits)
    assert all("section_path" in hit.metadata for hit in hits)


async def test_reingesting_the_same_document_does_not_duplicate(ingested: dict, client: AsyncClient) -> None:
    """acks_late redelivery must be a no-op, not a second set of chunks."""
    from app.tasks.ingest import run_ingest_pipeline

    with sync_session() as session:
        job = session.scalar(select(IngestJob).where(IngestJob.document_id == ingested["document_id"]))
        job_id = str(job.id)
        before = len(session.scalars(select(Chunk).where(Chunk.document_id == ingested["document_id"])).all())

    run_ingest_pipeline(job_id)

    with sync_session() as session:
        after = len(session.scalars(select(Chunk).where(Chunk.document_id == ingested["document_id"])).all())

    assert after == before
    assert get_vector_store().count(str(ingested["course_id"])) == after


def _outlined_pdf(chapters: list[str]) -> bytes:
    """A PDF with a real embedded outline, so the ToC path builds the graph."""
    import pymupdf

    doc = pymupdf.open()
    toc = []
    for name in chapters:
        chapter_start = len(doc)

        # The chapter gets an opening page of its OWN, before its first
        # subsection. Both used to start on the same page, which made every
        # chapter here a pure container -- it owned no page exclusively, so
        # under the current rules it is not a node and cannot introduce
        # anything, and this fixture produced a graph with no edges at all.
        # Real books open a chapter with its own prose (CO 250 spends page 75
        # on why an IP is harder than an LP before section 4.1 begins), so the
        # collision was the unrealistic part, not the rule.
        opening = doc.new_page()
        opening.insert_text((72, 90), name, fontsize=20)
        opening.insert_text((72, 130), f"This chapter introduces {name.lower()}. " * 14, fontsize=10)

        section_start = len(doc)
        for section in ("Definition", "Worked Example"):
            page = doc.new_page()
            page.insert_text((72, 90), f"{name} — {section}", fontsize=18)
            page.insert_text((72, 130), f"This section covers {name.lower()}. " * 14, fontsize=10)
        toc.append([1, name, chapter_start + 1])
        toc.append([2, f"{name} foundations", section_start + 1])
    doc.set_toc(toc)
    payload = doc.tobytes()
    doc.close()
    return payload


async def test_a_second_document_does_not_destroy_the_first_documents_progress(client: AsyncClient) -> None:
    """The regression that motivated building the graph per COURSE, not per document.

    `persist_graph` replaces a course's graph wholesale and deletes any node
    absent from the new concept list -- and the cascade takes that node's
    `node_progress` rows with it. Building the concept list from only the
    document being ingested therefore wiped every other document's EXP and
    review history on the second upload.
    """
    from app.models import NodeProgress, SkillEdge, SkillNode

    registered = await client.post(
        "/api/auth/register",
        json={"email": "multidoc@example.com", "password": "hunter22-long-enough", "display_name": "M"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    user_id = uuid.UUID(registered.json()["user"]["id"])

    course_id = (await client.post("/api/courses", json={"title": "Two books"}, headers=headers)).json()["id"]

    async def upload(name: str, payload: bytes) -> None:
        response = await client.post(
            f"/api/courses/{course_id}/documents",
            headers=headers,
            files={"file": (name, payload, "application/pdf")},
        )
        assert response.status_code == 202, response.text

    await upload("algebra.pdf", _outlined_pdf(["Vectors", "Matrices", "Determinants", "Eigenvalues"]))

    with sync_session() as session:
        first_nodes = {
            node.slug: node.id
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == uuid.UUID(course_id)))
        }
        first_edges = {
            (edge.prereq_id, edge.target_id)
            for edge in session.scalars(select(SkillEdge).where(SkillEdge.course_id == uuid.UUID(course_id)))
        }
        assert first_nodes, "first document produced no graph"
        assert first_edges, "first document produced no prerequisite edges"
        target_id = first_nodes["vectors"]
        # Stand in for a drilled node: real EXP and review history.
        session.add(NodeProgress(user_id=user_id, node_id=target_id, exp=1325, level=5, mastery=0.97, reps=9))

    await upload("probability.pdf", _outlined_pdf(["Probability", "Random Variables", "Expectation", "Bayes"]))

    with sync_session() as session:
        after = {
            node.slug: node.id
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == uuid.UUID(course_id)))
        }
        after_edges = {
            (edge.prereq_id, edge.target_id)
            for edge in session.scalars(select(SkillEdge).where(SkillEdge.course_id == uuid.UUID(course_id)))
        }
        progress = session.get(NodeProgress, (user_id, target_id))

    # Every node from the first document is still there, with the SAME id --
    # matching by slug is what keeps progress attached.
    for slug, node_id in first_nodes.items():
        assert after.get(slug) == node_id, f"{slug} was deleted or recreated by the second upload"
    # Edges from the first document also survive the course-wide rebuild.
    assert first_edges <= after_edges, "the second upload removed an earlier prerequisite edge"
    # And the second document actually contributed.
    assert set(after) - set(first_nodes), "second document added nothing"
    # The progress survived untouched.
    assert progress is not None, "node_progress was cascade-deleted"
    assert (progress.exp, progress.reps) == (1325, 9)


async def test_documents_sharing_a_chapter_name_stay_separate_nodes(client: AsyncClient) -> None:
    """Two books both containing "Introduction" must not collapse into one node."""
    from app.models import SkillNode

    registered = await client.post(
        "/api/auth/register",
        json={"email": "collide@example.com", "password": "hunter22-long-enough", "display_name": "C"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    course_id = (await client.post("/api/courses", json={"title": "Collide"}, headers=headers)).json()["id"]

    shared = ["Introduction", "Methods", "Results", "Discussion"]
    for name in ("paper-one.pdf", "paper-two.pdf"):
        response = await client.post(
            f"/api/courses/{course_id}/documents",
            headers=headers,
            files={"file": (name, _outlined_pdf(shared), "application/pdf")},
        )
        assert response.status_code == 202, response.text

    with sync_session() as session:
        slugs = sorted(
            session.scalars(select(SkillNode.slug).where(SkillNode.course_id == uuid.UUID(course_id)))
        )

    assert len(slugs) == len(set(slugs)), "slugs collided"
    assert "introduction" in slugs
    assert "introduction-2" in slugs, slugs

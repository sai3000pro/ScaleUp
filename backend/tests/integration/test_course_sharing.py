"""Share links and copy-to-account, against the real database."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import (
    Attempt,
    Chunk,
    Course,
    Document,
    NodeProgress,
    Question,
    SkillEdge,
    SkillNode,
)
from app.services.graph_service import persist_graph
from tests.fixtures.skill_graph import CONCEPTS, EDGES

SHARER = {"email": "sharer@example.com", "password": "hunter22-long-enough", "display_name": "Sharer"}
COPIER = {"email": "copier@example.com", "password": "hunter22-long-enough", "display_name": "Copier"}


async def _register(client: AsyncClient, credentials: dict[str, str]) -> dict:
    response = await client.post("/api/auth/register", json=credentials)
    assert response.status_code == 201, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


@pytest.fixture
async def shared_course(client: AsyncClient) -> dict:
    """A ready course with a document, a chunk, a graph, a question, and learner progress."""
    sharer = await _register(client, SHARER)

    with sync_session() as session:
        course = Course(owner_id=uuid.UUID(sharer["user"]["id"]), title="Shared Piano", status="ready")
        session.add(course)
        session.flush()

        document = Document(
            course_id=course.id,
            source_type="pdf",
            filename="linear-algebra.pdf",
            source_uri=None,
            content_sha256="a" * 64,
            storage_path="/tmp/source.pdf",
            byte_size=1024,
        )
        session.add(document)
        session.flush()

        chunk = Chunk(
            document_id=document.id,
            course_id=course.id,
            ordinal=0,
            page_start=0,
            page_end=0,
            text="Rhythm is read as a pattern of durations in time.",
            token_count=10,
            content_sha256="b" * 64,
            vector_id="vector-in-the-source-collection",
        )
        session.add(chunk)
        session.flush()

        persist_graph(session, course, CONCEPTS, EDGES)

        anchor = session.scalar(
            select(SkillNode).where(SkillNode.course_id == course.id, SkillNode.slug == "reading-rhythm")
        )
        assert anchor is not None
        # Provenance that must be remapped, not copied verbatim.
        anchor.source_chunk_ids = [chunk.id]

        question = Question(
            node_id=anchor.id,
            course_id=course.id,
            question_type="short_answer",
            question_text="What does a dotted half note last for?",
            rubric=[{"id": "kp1", "point": "three beats in common time", "weight": 1.0}],
            difficulty=2,
            prompt_version="fixture",
        )
        session.add(question)
        # Progress that must NOT travel with the copy.
        session.add(
            NodeProgress(
                user_id=uuid.UUID(sharer["user"]["id"]),
                node_id=anchor.id,
                exp=40,
                level=1,
                mastery=0.4,
                reps=2,
            )
        )

    return {"course_id": str(course.id), "chunk_id": str(chunk.id), "sharer": sharer}


async def _share_token(client: AsyncClient, shared_course: dict) -> str:
    share = await client.post(
        f"/api/courses/{shared_course['course_id']}/share",
        headers=shared_course["sharer"]["headers"],
    )
    assert share.status_code == 201, share.text
    url = share.json()["url"]
    assert url.startswith("http://localhost:3000/share/")
    return url.rsplit("/", 1)[-1]


async def test_create_share_returns_a_link_that_previews_publicly(
    client: AsyncClient, shared_course: dict
) -> None:
    token = await _share_token(client, shared_course)

    # No auth on the preview: the token is the credential, and the visitor may
    # not have an account yet.
    preview = await client.get(f"/api/shares/{token}")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["title"] == "Shared Piano"
    assert body["status"] == "ready"
    assert body["shared_by"] == "Sharer"
    assert body["node_count"] == len(CONCEPTS)
    assert body["edge_count"] == len(EDGES) - 1  # the planted back-edge is rejected


async def test_copy_deep_copies_content_but_no_learner_progress(
    client: AsyncClient, shared_course: dict
) -> None:
    token = await _share_token(client, shared_course)
    copier = await _register(client, COPIER)

    copied = await client.post(f"/api/shares/{token}/copy", headers=copier["headers"])
    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["title"] == "Copy of Shared Piano"
    assert body["status"] == "ready"
    assert body["node_count"] == len(CONCEPTS)
    assert body["mastered_count"] == 0  # no progress travelled

    with sync_session() as session:
        course = session.get(Course, uuid.UUID(body["id"]))
        assert course is not None
        assert str(course.owner_id) == copier["user"]["id"]
        assert str(course.copied_from_id) == shared_course["course_id"]
        assert course.graph_version == 0  # fresh; no projection exists yet

        nodes = session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)).all()
        edges = session.scalars(select(SkillEdge).where(SkillEdge.course_id == course.id)).all()
        documents = session.scalars(select(Document).where(Document.course_id == course.id)).all()
        chunks = session.scalars(select(Chunk).where(Chunk.course_id == course.id)).all()
        questions = session.scalars(select(Question).where(Question.course_id == course.id)).all()
        progress = session.scalars(
            select(NodeProgress).join(SkillNode, SkillNode.id == NodeProgress.node_id).where(
                SkillNode.course_id == course.id
            )
        ).all()
        attempts = session.scalars(select(Attempt).where(Attempt.course_id == course.id)).all()

    assert len(nodes) == len(CONCEPTS)
    assert len(edges) == len(EDGES) - 1
    assert len(documents) == 1
    assert len(chunks) == 1
    assert len(questions) == 1
    assert progress == []
    assert attempts == []

    (chunk,) = chunks
    (document,) = documents
    (question,) = questions
    # The bytes are the same content-addressed object, so the path is reused...
    assert document.storage_path == "/tmp/source.pdf"
    assert chunk.text == "Rhythm is read as a pattern of durations in time."
    # ...but identity is fresh: new ids, and no dangling vector pointer into the
    # source course's Chroma collection.
    assert str(chunk.id) != shared_course["chunk_id"]
    assert chunk.vector_id is None

    # Provenance was remapped onto the copy's own chunk.
    anchor = next(node for node in nodes if node.slug == "reading-rhythm")
    assert anchor.source_chunk_ids == [chunk.id]
    assert question.node_id == anchor.id


async def test_copy_is_idempotent(client: AsyncClient, shared_course: dict) -> None:
    token = await _share_token(client, shared_course)
    copier = await _register(client, COPIER)

    first = await client.post(f"/api/shares/{token}/copy", headers=copier["headers"])
    second = await client.post(f"/api/shares/{token}/copy", headers=copier["headers"])
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]


async def test_copying_a_copy_stays_in_the_original_cohort(client: AsyncClient, shared_course: dict) -> None:
    original_token = await _share_token(client, shared_course)
    copier = await _register(client, COPIER)
    copied = await client.post(f"/api/shares/{original_token}/copy", headers=copier["headers"])
    assert copied.status_code == 201, copied.text

    reshared = await client.post(
        f"/api/courses/{copied.json()['id']}/share",
        headers=copier["headers"],
    )
    assert reshared.status_code == 201, reshared.text
    reshared_token = reshared.json()["url"].rsplit("/", 1)[-1]

    # The canonical root is the idempotency key, even when the link came from
    # a copy rather than directly from the original course.
    copied_again = await client.post(f"/api/shares/{reshared_token}/copy", headers=copier["headers"])
    assert copied_again.status_code == 200, copied_again.text
    assert copied_again.json()["id"] == copied.json()["id"]


async def test_copy_requires_authentication(client: AsyncClient, shared_course: dict) -> None:
    token = await _share_token(client, shared_course)
    assert (await client.post(f"/api/shares/{token}/copy")).status_code == 401


async def test_share_status_and_revocation(client: AsyncClient, shared_course: dict) -> None:
    status = await client.get(
        f"/api/courses/{shared_course['course_id']}/share",
        headers=shared_course["sharer"]["headers"],
    )
    assert status.status_code == 200
    assert status.json() == {"course_id": shared_course["course_id"], "shared": False, "created_at": None}

    token = await _share_token(client, shared_course)

    status = await client.get(
        f"/api/courses/{shared_course['course_id']}/share",
        headers=shared_course["sharer"]["headers"],
    )
    assert status.json()["shared"] is True
    assert status.json()["created_at"] is not None

    revoked = await client.delete(
        f"/api/courses/{shared_course['course_id']}/share",
        headers=shared_course["sharer"]["headers"],
    )
    assert revoked.status_code == 204
    assert (await client.get(f"/api/shares/{token}")).status_code == 404

    status = await client.get(
        f"/api/courses/{shared_course['course_id']}/share",
        headers=shared_course["sharer"]["headers"],
    )
    assert status.json()["shared"] is False


async def test_recreating_a_share_rotates_the_token(client: AsyncClient, shared_course: dict) -> None:
    first = await _share_token(client, shared_course)
    second = await _share_token(client, shared_course)
    assert second != first
    assert (await client.get(f"/api/shares/{first}")).status_code == 404
    assert (await client.get(f"/api/shares/{second}")).status_code == 200


async def test_only_ready_courses_can_be_shared(client: AsyncClient) -> None:
    owner = await _register(client, SHARER)
    draft = await client.post(
        "/api/courses",
        json={"title": "Not ready yet"},
        headers=owner["headers"],
    )
    assert draft.status_code == 201, draft.text

    share = await client.post(f"/api/courses/{draft.json()['id']}/share", headers=owner["headers"])
    assert share.status_code == 409


async def test_unknown_tokens_are_404(client: AsyncClient) -> None:
    owner = await _register(client, SHARER)
    assert (await client.get("/api/shares/not-a-real-token")).status_code == 404
    assert (await client.post("/api/shares/not-a-real-token/copy", headers=owner["headers"])).status_code == 404

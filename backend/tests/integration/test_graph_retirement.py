"""A re-extraction can drop a concept; it cannot drop a learner's progress on it."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.domain.dag import CandidateEdge
from app.models import Course, NodeProgress, SkillEdge, SkillNode
from app.services.graph_service import ConceptSpec, persist_graph

FIRST = [
    ConceptSpec("scales", "Scales", "Major scales, hands separately.", assessable=True),
    ConceptSpec("arpeggios", "Arpeggios", "Triads broken across the octave.", assessable=True),
    ConceptSpec("trills", "Trills", "Rapid alternation between adjacent notes.", assessable=True),
]
FIRST_EDGES = [CandidateEdge("scales", "arpeggios", 0.9), CandidateEdge("arpeggios", "trills", 0.9)]
SECOND = [FIRST[0]]

CREDENTIALS = {"email": "retire@example.com", "password": "hunter22-long-enough", "display_name": "R"}


@pytest.fixture
async def course_and_user(client: AsyncClient) -> tuple[uuid.UUID, uuid.UUID]:
    registered = await client.post("/api/auth/register", json=CREDENTIALS)
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    created = await client.post("/api/courses", json={"title": "Retire"}, headers=headers)
    return uuid.UUID(created.json()["id"]), uuid.UUID(registered.json()["user"]["id"])


# @spec CURR-GRAPH-005
async def test_a_practised_node_that_vanishes_is_retired_not_deleted(course_and_user) -> None:
    course_id, user_id = course_and_user
    with sync_session() as session:
        persist_graph(session, session.get(Course, course_id), FIRST, FIRST_EDGES)
        ids = {node.slug: node.id for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course_id))}
        session.add(NodeProgress(user_id=user_id, node_id=ids["arpeggios"], exp=400, level=3, mastery=0.8, reps=4))
        session.commit()

    with sync_session() as session:
        persist_graph(session, session.get(Course, course_id), SECOND, [])
        session.commit()

    with sync_session() as session:
        nodes = {node.slug: node for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course_id))}
        assert set(nodes) == {"scales", "arpeggios"}, "unpractised 'trills' should be gone; practised 'arpeggios' kept"
        assert nodes["scales"].retired_at is None
        assert nodes["arpeggios"].retired_at is not None
        progress = session.get(NodeProgress, (user_id, ids["arpeggios"]))
        assert progress is not None and progress.exp == 400
        assert session.scalars(select(SkillEdge).where(SkillEdge.course_id == course_id)).first() is None

    # The concept coming back un-retires the same row, so the progress reattaches.
    with sync_session() as session:
        persist_graph(session, session.get(Course, course_id), FIRST, FIRST_EDGES)
        session.commit()
    with sync_session() as session:
        node = session.get(SkillNode, ids["arpeggios"])
        assert node is not None and node.retired_at is None


# @spec CURR-GRAPH-005
async def test_learner_rows_restrict_node_deletion_at_the_database(course_and_user) -> None:
    from sqlalchemy.exc import IntegrityError

    course_id, user_id = course_and_user
    with sync_session() as session:
        persist_graph(session, session.get(Course, course_id), FIRST, FIRST_EDGES)
        node_id = session.scalar(select(SkillNode.id).where(SkillNode.slug == "scales", SkillNode.course_id == course_id))
        session.add(NodeProgress(user_id=user_id, node_id=node_id, exp=1, level=1, mastery=0.1, reps=1))
        session.commit()
    with sync_session() as session:
        session.delete(session.get(SkillNode, node_id))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

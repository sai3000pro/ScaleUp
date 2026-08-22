"""A learner's sentence becomes a published, playable tree in one request.

The end of the arrow for goal-first construction: not "the planner returns a
definition" (that is a unit test) but "the learner types a sentence and gets a
course whose graph they can open and drill".

Everything here runs with `LLM_PROVIDER=fake`, which is the point. The
deterministic floor is not a stand-in for the feature; it *is* the feature when
no provider is configured, and it has to produce a real ordered tree.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import CurriculumVersion, SkillEdge, SkillNode


def _version_for(course_id) -> CurriculumVersion:
    with sync_session() as session:
        version = session.scalar(
            select(CurriculumVersion).where(
                CurriculumVersion.course_id == course_id,
                CurriculumVersion.status == "published",
            )
        )
        assert version is not None, "goal-first construction must publish, not draft"
        return version


# @spec CURR-GOAL-001, CURR-GOAL-004
async def test_a_goal_naming_a_shipped_instrument_returns_a_playable_tree(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/courses/from-goal", json={"goal": "I want to learn how to play Guitar"}
    )

    assert response.status_code == 201, response.text
    course = response.json()
    assert course["title"] == "Guitar"
    assert course["node_count"] > 0, "a tree with no nodes is not a tree"
    assert course["edge_count"] > 0, "a tree with no edges is a list"

    # The graph the learner will actually open.
    graph = await authed_client.get(f"/api/courses/{course['id']}/graph")
    assert graph.status_code == 200
    nodes = graph.json()["nodes"]
    assert len(nodes) == course["node_count"]
    assert any(node["progress"]["state"] == "available" for node in nodes), (
        "a learner needs somewhere to begin"
    )


# @spec CURR-GOAL-012, CURR-GOAL-004
async def test_a_shipped_instrument_is_labelled_as_assembled_not_proposed(authed_client: AsyncClient) -> None:
    response = await authed_client.post("/api/courses/from-goal", json={"goal": "teach me piano"})
    assert response.status_code == 201, response.text

    version = _version_for(response.json()["id"])
    assert version.compiler_version == "catalogue-assembly-v1"


# @spec CURR-GOAL-006, CURR-GOAL-012
async def test_an_instrument_nothing_ships_still_gets_an_ordered_tree(authed_client: AsyncClient) -> None:
    """The case the catalogue exists for: an instrument nobody authored."""
    response = await authed_client.post(
        "/api/courses/from-goal", json={"goal": "I want to learn how to play the cello"}
    )

    assert response.status_code == 201, response.text
    course = response.json()
    assert course["title"] == "Cello"
    assert course["node_count"] >= 4
    assert course["edge_count"] > 0

    with sync_session() as session:
        nodes = session.scalars(select(SkillNode).where(SkillNode.course_id == course["id"])).all()
        edges = session.scalars(select(SkillEdge).where(SkillEdge.course_id == course["id"])).all()
    assert {node.slug for node in nodes}, "the spine should carry catalogue-derived slugs"
    assert edges, "the catalogue's suggested ordering should have seeded the tree"


# @spec CURR-GOAL-005
@pytest.mark.parametrize("goal", ["I want to get better at things", "asdfghjkl"])
async def test_a_goal_naming_no_instrument_is_refused_with_a_reason(
    authed_client: AsyncClient, goal: str
) -> None:
    response = await authed_client.post("/api/courses/from-goal", json={"goal": goal})

    assert response.status_code == 422
    assert "instrument" in response.json()["detail"].lower()


# @spec CURR-GOAL-003
async def test_the_instrument_is_read_from_the_sentence_not_supplied(authed_client: AsyncClient) -> None:
    """The learner never names a field; they write a sentence."""
    response = await authed_client.post(
        "/api/courses/from-goal", json={"goal": "honestly I've always wanted to play the fiddle"}
    )

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Violin"


# @spec CURR-GOAL-014
async def test_two_instruments_realise_the_same_catalogue_skill(authed_client: AsyncClient) -> None:
    """The property the shared catalogue exists for, end to end."""
    first = await authed_client.post("/api/courses/from-goal", json={"goal": "learn cello"})
    second = await authed_client.post("/api/courses/from-goal", json={"goal": "learn the ukulele"})
    assert first.status_code == 201 and second.status_code == 201

    def slugs(course_id) -> set[str]:
        with sync_session() as session:
            return {
                node.slug.split("-", 1)[1]
                for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course_id))
                if "-" in node.slug
            }

    shared = slugs(first.json()["id"]) & slugs(second.json()["id"])
    assert "steady-pulse" in shared, "both instruments should draw the same catalogue skill"


# @spec CURR-GOAL-001
async def test_a_goal_built_course_appears_in_the_learners_own_list(authed_client: AsyncClient) -> None:
    created = await authed_client.post("/api/courses/from-goal", json={"goal": "I want to learn trumpet"})
    assert created.status_code == 201, created.text

    listing = await authed_client.get("/api/courses")
    ids = {course["id"] for course in listing.json()["courses"]}
    assert created.json()["id"] in ids

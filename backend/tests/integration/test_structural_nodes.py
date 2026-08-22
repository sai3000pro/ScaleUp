"""A non-drillable node must carry structure without breaking anything.

`assessable=False` used to be unusable in practice. A structural node can never
be drilled, so no attempt is recorded against it, so its mastery stays 0.0 for
ever -- and every read path fed that raw 0.0 in as a prerequisite mastery, which
locked the entire subtree behind it permanently. The quest board excludes
structural nodes, so nothing could ever unlock it either. One container chapter
quarantined a whole book with no in-app way out, which is why the ingest
pipeline forced `assessable=True` on every outline node instead.

`app.domain.states.gating_masteries` made a structural node *transparent*: it
contributes its OWN prerequisites' masteries rather than its non-existent one.
This file is the end-to-end proof that all four consumers honour that -- the
graph read, drill eligibility, the quest board, and the EXP/level math -- so the
pipeline can go back to labelling containers honestly.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.domain.dag import CandidateEdge
from app.models import Attempt, Course, NodeProgress, Question, SkillNode
from app.services.graph_service import ConceptSpec, persist_graph

# open-chapter (structural, a root)   -> open-section
# intro -> gated-chapter (structural) -> gated-section
CONCEPTS = [
    ConceptSpec("intro", "Intro", "A drillable skill with no prerequisites of its own.", assessable=True),
    ConceptSpec("open-chapter", "Open Chapter", "A container with no prerequisites.", assessable=False),
    ConceptSpec("open-section", "Open Section", "A drillable skill under an unblocked container.", assessable=True),
    ConceptSpec("gated-chapter", "Gated Chapter", "A container that sits behind real work.", assessable=False),
    ConceptSpec("gated-section", "Gated Section", "A drillable skill under a blocked container.", assessable=True),
]
EDGES = [
    CandidateEdge("open-chapter", "open-section", 0.95),
    CandidateEdge("intro", "gated-chapter", 0.95),
    CandidateEdge("gated-chapter", "gated-section", 0.95),
]

CREDENTIALS = {"email": "structural@example.com", "password": "hunter22-long-enough", "display_name": "S"}


@pytest.fixture
async def course(client: AsyncClient) -> dict:
    registered = await client.post("/api/auth/register", json=CREDENTIALS)
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    created = await client.post("/api/courses", json={"title": "Structural"}, headers=headers)
    course_id = uuid.UUID(created.json()["id"])

    with sync_session() as session:
        persist_graph(session, session.get(Course, course_id), CONCEPTS, EDGES)

    with sync_session() as session:
        ids = {
            node.slug: node.id
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course_id))
        }

    return {"id": course_id, "headers": headers, "ids": ids}


async def fetch_graph(client: AsyncClient, course: dict) -> dict[str, dict]:
    response = await client.get(f"/api/courses/{course['id']}/graph", headers=course["headers"])
    assert response.status_code == 200, response.text
    return {node["slug"]: node for node in response.json()["nodes"]}


def covering_answer(attempt_id: str) -> str:
    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(attempt_id))
        question = session.get(Question, attempt.question_id)
        return " ".join(point["point"] for point in question.rubric)


async def drill_and_pass(client: AsyncClient, course: dict, slug: str) -> dict:
    drill = await client.post(f"/api/nodes/{course['ids'][slug]}/drill", headers=course["headers"])
    assert drill.status_code == 201, drill.text
    attempt_id = drill.json()["attempt_id"]
    graded = await client.post(
        f"/api/attempts/{attempt_id}/grade",
        headers=course["headers"],
        json={"answer": covering_answer(attempt_id)},
    )
    assert graded.status_code == 200, graded.text
    return graded.json()


async def clear(client: AsyncClient, course: dict, slug: str) -> dict:
    """Drill a node until its mastery crosses the prerequisite threshold.

    Mastery is an exponential moving average with alpha 0.4, so one perfect
    answer only reaches 0.4 and a single pass can never unlock anything. Three
    passes reach 0.784.
    """
    result: dict = {}
    for _ in range(3):
        result = await drill_and_pass(client, course, slug)
    assert result["progress"]["mastery"] >= 0.5, result
    return result


# ── the graph read ────────────────────────────────────────────────────────


async def test_a_structural_root_does_not_lock_its_section(client: AsyncClient, course: dict) -> None:
    """The failure that forced `assessable=True` in the first place."""
    nodes = await fetch_graph(client, course)

    assert nodes["open-chapter"]["assessable"] is False
    assert nodes["open-section"]["progress"]["state"] == "available"
    assert nodes["open-section"]["blocked_by"] == []


async def test_a_structural_node_still_passes_its_own_prerequisites_through(
    client: AsyncClient, course: dict
) -> None:
    """Transparent, not free."""
    nodes = await fetch_graph(client, course)

    assert nodes["gated-section"]["progress"]["state"] == "locked"
    # And it names the node the user can actually go and drill, not the
    # container, which they could not.
    assert [ref["title"] for ref in nodes["gated-section"]["blocked_by"]] == ["Intro"]


async def test_clearing_the_real_prerequisite_unlocks_through_the_container(
    client: AsyncClient, course: dict
) -> None:
    await clear(client, course, "intro")
    nodes = await fetch_graph(client, course)

    assert nodes["gated-section"]["progress"]["state"] == "available"
    assert nodes["gated-section"]["blocked_by"] == []


async def test_a_fresh_user_has_something_to_drill(client: AsyncClient, course: dict) -> None:
    """A tree whose only entry points are containers is a tree nobody can start."""
    nodes = await fetch_graph(client, course)
    startable = [n for n in nodes.values() if n["assessable"] and n["progress"]["state"] == "available"]

    assert {n["slug"] for n in startable} == {"intro", "open-section"}


async def test_stats_still_account_for_every_node(client: AsyncClient, course: dict) -> None:
    response = await client.get(f"/api/courses/{course['id']}/graph", headers=course["headers"])
    stats = response.json()["stats"]

    assert stats["total"] == len(CONCEPTS)
    assert stats["locked"] + stats["available"] + stats["learning"] + stats["decaying"] + stats["mastered"] == (
        stats["total"]
    )


# ── drill eligibility ─────────────────────────────────────────────────────


async def test_drilling_a_structural_node_is_refused(client: AsyncClient, course: dict) -> None:
    response = await client.post(f"/api/nodes/{course['ids']['open-chapter']}/drill", headers=course["headers"])

    assert response.status_code == 409, response.text
    assert "cannot be drilled" in response.text


async def test_the_section_under_a_structural_root_drills_immediately(
    client: AsyncClient, course: dict
) -> None:
    result = await drill_and_pass(client, course, "open-section")
    assert result["exp_awarded"] > 0


async def test_a_section_behind_a_structural_node_is_refused_until_its_real_prerequisite_is_met(
    client: AsyncClient, course: dict
) -> None:
    blocked = await client.post(f"/api/nodes/{course['ids']['gated-section']}/drill", headers=course["headers"])
    assert blocked.status_code == 409, blocked.text

    await clear(client, course, "intro")

    allowed = await client.post(f"/api/nodes/{course['ids']['gated-section']}/drill", headers=course["headers"])
    assert allowed.status_code == 201, allowed.text


# ── the quest board ───────────────────────────────────────────────────────


async def test_no_structural_node_ever_reaches_the_board(client: AsyncClient, course: dict) -> None:
    """A quest the user cannot clear is worse than an empty board."""
    board = (await client.get("/api/quests/daily", headers=course["headers"])).json()
    structural = {str(course["ids"][slug]) for slug in ("open-chapter", "gated-chapter")}

    assert board["quests"], "structural nodes emptied the board"
    assert structural.isdisjoint({quest["node_id"] for quest in board["quests"]})


async def test_the_board_offers_the_sections_behind_the_containers(
    client: AsyncClient, course: dict
) -> None:
    board = (await client.get("/api/quests/daily", headers=course["headers"])).json()
    offered = {quest["node_id"] for quest in board["quests"]}

    assert str(course["ids"]["open-section"]) in offered
    assert board["total_reward_exp"] > 0


# ── EXP and levels ────────────────────────────────────────────────────────


async def test_exp_accrues_normally_around_a_structural_node(client: AsyncClient, course: dict) -> None:
    first = await clear(client, course, "intro")
    second = await drill_and_pass(client, course, "gated-section")

    assert first["exp_awarded"] > 0
    assert second["user_total_exp"] == first["user_total_exp"] + second["exp_awarded"]


async def test_a_structural_node_earns_nothing_and_stays_at_level_zero(
    client: AsyncClient, course: dict
) -> None:
    await clear(client, course, "intro")
    await drill_and_pass(client, course, "gated-section")

    nodes = await fetch_graph(client, course)
    for slug in ("open-chapter", "gated-chapter"):
        assert nodes[slug]["progress"]["exp"] == 0, slug
        assert nodes[slug]["progress"]["level"] == 0, slug
        assert nodes[slug]["progress"]["mastery"] == 0.0, slug

    with sync_session() as session:
        rows = session.scalars(
            select(NodeProgress).where(NodeProgress.node_id == course["ids"]["gated-chapter"])
        ).all()
    # A row exists (lazily created on read) but nothing was ever awarded to it.
    assert all(row.exp == 0 for row in rows)


async def test_difficulty_comes_from_dependency_depth(client: AsyncClient, course: dict) -> None:
    """No concept named a difficulty, so `persist_graph` derived every one."""
    nodes = await fetch_graph(client, course)

    assert nodes["intro"]["difficulty"] < nodes["gated-section"]["difficulty"]
    assert nodes["gated-section"]["depth"] > nodes["intro"]["depth"]
    assert all(1 <= node["difficulty"] <= 5 for node in nodes.values())


async def test_the_unlock_names_the_drillable_section_not_the_container(
    client: AsyncClient, course: dict
) -> None:
    """`unlocked_node_ids` must never hand the UI a node with nothing to drill.

    `intro`'s only direct dependent is the structural `gated-chapter`, so a
    flat "who depends on me" query reports the container -- the one node the
    learner cannot open -- and stays silent about `gated-section`, which is
    what actually became available. The graph refetch was always correct, so
    this never locked anyone out; it just aimed the single moment the product
    celebrates at a heading.
    """
    # Collected across passes, not read off the last one: the unlock fires on
    # the single pass that CROSSES 0.5 (the second, 0.4 -> 0.64), and an
    # already-cleared node deliberately reports nothing on later reviews.
    unlocked: set[str] = set()
    for _ in range(3):
        result = await drill_and_pass(client, course, "intro")
        unlocked |= set(result["unlocked_node_ids"])

    assert str(course["ids"]["gated-section"]) in unlocked
    assert str(course["ids"]["gated-chapter"]) not in unlocked

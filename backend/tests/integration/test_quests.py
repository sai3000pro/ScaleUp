"""Decay, the Daily Quest board, and the rescue bonus."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import Attempt, NodeProgress, Question, SkillNode
from app.seed import (
    BANJO_COURSE_ID,
    DEV_USER_ID,
    DRUMS_COURSE_ID,
    GUITAR_COURSE_ID,
    PIANO_COURSE_ID,
    TRUMPET_COURSE_ID,
    VIOLIN_COURSE_ID,
    seed,
)

# The board spans EVERY course the user owns -- the query filters on ownership,
# not on a list -- so this has to name every course `seed()` provisions or the
# reachability assertion below fails the moment a quest comes from a course the
# test forgot about.
SEEDED_COURSE_IDS = (
    PIANO_COURSE_ID,
    GUITAR_COURSE_ID,
    VIOLIN_COURSE_ID,
    TRUMPET_COURSE_ID,
    DRUMS_COURSE_ID,
    BANJO_COURSE_ID,
)

JUNK = "banana banana banana"


def covering_answer(attempt_id: str) -> str:
    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(attempt_id))
        question = session.get(Question, attempt.question_id)
        return " ".join(point["point"] for point in question.rubric)


def rewind(node_slug: str, days: float) -> None:
    """The time machine, inline. Equivalent to scripts/timewarp.py."""
    with sync_session() as session:
        node = session.scalar(
            select(SkillNode).where(SkillNode.course_id == PIANO_COURSE_ID, SkillNode.slug == node_slug)
        )
        _rewind_progress(session, node.id, days)


def rewind_node(node_id: uuid.UUID, days: float) -> None:
    """Rewind by id, so a test can move whichever node the board actually offered."""
    with sync_session() as session:
        _rewind_progress(session, node_id, days)


def _rewind_progress(session, node_id: uuid.UUID, days: float) -> None:
    progress = session.get(NodeProgress, (DEV_USER_ID, node_id))
    shift = timedelta(days=days)
    progress.last_reviewed_at -= shift
    progress.due_at -= shift


@pytest.fixture
def seeded(clean_db: None) -> dict:
    seed()
    with sync_session() as session:
        root = session.scalar(
            select(SkillNode).where(SkillNode.course_id == PIANO_COURSE_ID, SkillNode.slug == "keyboard-layout")
        )
        return {"root_id": root.id}


@pytest.fixture
async def dev_headers(client: AsyncClient, seeded: dict) -> dict[str, str]:
    response = await client.post("/api/auth/dev-login")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def drill_and_pass(client: AsyncClient, headers: dict[str, str], node_id: uuid.UUID) -> dict:
    drill = await client.post(f"/api/nodes/{node_id}/drill", headers=headers)
    graded = await client.post(
        f"/api/attempts/{drill.json()['attempt_id']}/grade",
        headers=headers,
        json={"answer": covering_answer(drill.json()["attempt_id"])},
    )
    return graded.json()


# ── the board ─────────────────────────────────────────────────────────────


async def test_a_new_user_never_sees_an_empty_board(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """An empty quest screen on day one reads as 'nothing here for me'."""
    board = (await client.get("/api/quests/daily", headers=dev_headers)).json()

    assert board["quests"], board
    assert all(quest["reason"] == "frontier" for quest in board["quests"])
    assert board["total_reward_exp"] > 0


async def test_frontier_quests_are_reachable_nodes_only(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    board = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    # Frontier quests can come from any of the seeded courses, so union the
    # reachable set across every course the dev user owns.
    available: set[str] = set()
    for course_id in SEEDED_COURSE_IDS:
        graph = (await client.get(f"/api/courses/{course_id}/graph", headers=dev_headers)).json()
        available |= {n["id"] for n in graph["nodes"] if n["progress"]["state"] == "available"}

    assert {quest["node_id"] for quest in board["quests"]} <= available


async def test_a_drilled_node_leaves_the_board_until_it_is_due(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    await drill_and_pass(client, dev_headers, seeded["root_id"])
    board = (await client.get("/api/quests/daily", headers=dev_headers)).json()

    assert str(seeded["root_id"]) not in {q["node_id"] for q in board["quests"]}


async def test_rewinding_time_puts_a_node_back_on_the_board(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """The end-to-end assertion for the whole retention system."""
    await drill_and_pass(client, dev_headers, seeded["root_id"])
    rewind("keyboard-layout", days=60)

    graph = (await client.get(f"/api/courses/{PIANO_COURSE_ID}/graph", headers=dev_headers)).json()
    node = next(n for n in graph["nodes"] if n["slug"] == "keyboard-layout")
    assert node["progress"]["state"] == "decaying"
    # Proficiency halves every interval, so after many intervals it is near zero.
    assert node["progress"]["proficiency"] < 0.2
    # Mastery itself does NOT decay -- only the displayed proficiency does.
    assert node["progress"]["mastery"] > 0.3

    board = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    overdue = [q for q in board["quests"] if q["reason"] == "overdue"]
    assert overdue, board
    assert str(seeded["root_id"]) in {q["node_id"] for q in overdue}


async def test_an_overdue_quest_is_worth_more_than_a_fresh_one(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """The rescue bonus is what makes the board worth clearing.

    Uses whichever node the board actually offered rather than naming one. Six
    seeded courses compete for three frontier slots, so pinning this to the
    linear-algebra root asserted the sort order as much as the bonus.
    """
    fresh = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    assert fresh["quests"], "a new user must never see an empty board"
    offered = fresh["quests"][0]
    node_id = uuid.UUID(offered["node_id"])
    fresh_reward = offered["reward_exp"]

    await drill_and_pass(client, dev_headers, node_id)
    rewind_node(node_id, days=60)

    board = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    overdue_reward = next(q for q in board["quests"] if q["node_id"] == str(node_id))["reward_exp"]

    assert overdue_reward > fresh_reward
    assert overdue_reward <= round(fresh_reward * 1.5) + 1  # bonus caps at 1.5x


async def test_rescuing_a_decayed_node_pays_the_bonus(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    first = await drill_and_pass(client, dev_headers, seeded["root_id"])
    assert first["rescue_bonus_applied"] is False

    rewind("keyboard-layout", days=60)
    rescue = await drill_and_pass(client, dev_headers, seeded["root_id"])

    assert rescue["rescue_bonus_applied"] is True
    # First pass carries a +50 bonus the rescue does not, so compare the
    # difficulty-scaled base rather than the raw totals.
    assert rescue["exp_awarded"] > 100


async def test_board_is_capped_and_ordered_by_relative_urgency(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    await drill_and_pass(client, dev_headers, seeded["root_id"])
    rewind("keyboard-layout", days=90)

    board = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    overdue = [q for q in board["quests"] if q["reason"] == "overdue"]

    assert len(board["quests"]) <= 11  # 8 overdue + 3 frontier top-up
    urgencies = [q["overdue_days"] for q in overdue]
    assert urgencies == sorted(urgencies, reverse=True) or len(urgencies) == 1


async def test_streak_counts_a_day_with_an_attempt(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    before = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    assert before["streak_days"] == 0

    await drill_and_pass(client, dev_headers, seeded["root_id"])
    after = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    assert after["streak_days"] == 1
    assert after["date"] == datetime.now(timezone.utc).date().isoformat()


async def test_the_board_is_per_user(client: AsyncClient, dev_headers: dict[str, str], seeded: dict) -> None:
    other = await client.post(
        "/api/auth/register",
        json={"email": "stranger@example.com", "password": "hunter22-long-enough", "display_name": "S"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    board = (await client.get("/api/quests/daily", headers=headers)).json()
    assert board["quests"] == []


async def test_the_board_is_stable_across_reads(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """The same data must produce the same board, every time.

    Both quest lists are capped, so any tie left unbroken by the sort key is
    decided by the order Postgres happened to return rows in -- which is not
    stable. With six seeded courses there are many depth-0 roots tied on depth
    alone, and the board visibly reshuffled between refreshes: a quest a learner
    was looking at could vanish on the next read.
    """
    first = (await client.get("/api/quests/daily", headers=dev_headers)).json()
    for _ in range(4):
        again = (await client.get("/api/quests/daily", headers=dev_headers)).json()
        assert [quest["node_id"] for quest in again["quests"]] == [
            quest["node_id"] for quest in first["quests"]
        ]
        assert again["total_reward_exp"] == first["total_reward_exp"]

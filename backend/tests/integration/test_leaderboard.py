"""The cohort leaderboard: copies of a shared course race the same tree."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import Course, NodeProgress, SkillNode, User
from app.services.graph_service import persist_graph
from tests.fixtures.skill_graph import CONCEPTS, EDGES

SHARER = {"email": "sharer@example.com", "password": "hunter22-long-enough", "display_name": "Sharer"}
RIVAL = {"email": "rival@example.com", "password": "hunter22-long-enough", "display_name": "Rival"}
LURKER = {"email": "lurker@example.com", "password": "hunter22-long-enough", "display_name": "Lurker"}
OUTSIDER = {"email": "outsider@example.com", "password": "hunter22-long-enough", "display_name": "Outsider"}


async def _register(client: AsyncClient, credentials: dict[str, str]) -> dict:
    response = await client.post("/api/auth/register", json=credentials)
    assert response.status_code == 201, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


@pytest.fixture
async def cohort(client: AsyncClient) -> dict:
    """Original course + two copies, with distinct EXP across the three owners."""
    sharer = await _register(client, SHARER)

    with sync_session() as session:
        course = Course(owner_id=uuid.UUID(sharer["user"]["id"]), title="Raced Piano", status="ready")
        session.add(course)
        session.flush()
        persist_graph(session, course, CONCEPTS, EDGES)

    share = await client.post(f"/api/courses/{course.id}/share", headers=sharer["headers"])
    assert share.status_code == 201, share.text
    token = share.json()["url"].rsplit("/", 1)[-1]

    rival = await _register(client, RIVAL)
    lurker = await _register(client, LURKER)
    rival_copy = await client.post(f"/api/shares/{token}/copy", headers=rival["headers"])
    lurker_copy = await client.post(f"/api/shares/{token}/copy", headers=lurker["headers"])
    assert rival_copy.status_code == lurker_copy.status_code == 201

    # Give the rival a real lead: two started nodes, one of them mastered, plus
    # account-level EXP that outranks the sharer.
    with sync_session() as session:
        nodes = session.scalars(
            select(SkillNode).where(SkillNode.course_id == uuid.UUID(rival_copy.json()["id"]))
        ).all()
        session.add(
            NodeProgress(
                user_id=uuid.UUID(rival["user"]["id"]),
                node_id=nodes[0].id,
                exp=200,
                level=5,
                mastery=0.9,
                reps=3,
                last_reviewed_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            NodeProgress(
                user_id=uuid.UUID(rival["user"]["id"]),
                node_id=nodes[1].id,
                exp=60,
                level=2,
                mastery=0.5,
                reps=1,
                last_reviewed_at=datetime.now(timezone.utc),
            )
        )
        user = session.scalars(select(User).where(User.id == uuid.UUID(rival["user"]["id"]))).one()
        # The account level is DERIVED from EXP (app/domain/exp.py), never
        # stored -- 7,000 EXP is past the 5,800 level-3 threshold and short of
        # the 9,190 level-4 one, and the leaderboard must agree with the HUD
        # curve.
        user.total_exp = 7_000

    return {
        "course_id": str(course.id),
        "rival_copy_id": rival_copy.json()["id"],
        "lurker_copy_id": lurker_copy.json()["id"],
        "sharer": sharer,
        "rival": rival,
        "lurker": lurker,
    }


async def test_leaderboard_ranks_the_cohort_by_exp(client: AsyncClient, cohort: dict) -> None:
    board = await client.get(
        f"/api/courses/{cohort['course_id']}/leaderboard",
        headers=cohort["sharer"]["headers"],
    )
    assert board.status_code == 200, board.text
    body = board.json()

    assert body["cohort_size"] == 3
    # Rival leads on EXP; Sharer and Lurker tie at 0, broken alphabetically.
    assert [entry["display_name"] for entry in body["entries"]] == ["Rival", "Lurker", "Sharer"]
    assert body["my_rank"] == 3

    (rival,) = [entry for entry in body["entries"] if entry["display_name"] == "Rival"]
    assert rival["total_exp"] == 7_000
    # Level comes from the same curve as the HUD, not from a stored column.
    assert rival["level"] == 3
    # Two started, one mastered (level 5 + mastery 0.9).
    assert rival["started_count"] == 2
    assert rival["mastered_count"] == 1
    assert rival["me"] is False

    (sharer,) = [entry for entry in body["entries"] if entry["display_name"] == "Sharer"]
    assert sharer["me"] is True
    assert sharer["total_exp"] == 0
    (lurker,) = [entry for entry in body["entries"] if entry["display_name"] == "Lurker"]
    assert lurker["me"] is False


async def test_leaderboard_marks_the_caller_anywhere_in_the_cohort(client: AsyncClient, cohort: dict) -> None:
    board = await client.get(
        f"/api/courses/{cohort['rival_copy_id']}/leaderboard",
        headers=cohort["rival"]["headers"],
    )
    assert board.status_code == 200, board.text
    body = board.json()

    # Same cohort from the copy's point of view.
    assert body["cohort_size"] == 3
    assert body["my_rank"] == 1
    assert next(entry for entry in body["entries"] if entry["display_name"] == "Rival")["me"] is True


async def test_leaderboard_is_invisible_to_non_members(client: AsyncClient, cohort: dict) -> None:
    outsider = await _register(client, OUTSIDER)
    response = await client.get(
        f"/api/courses/{cohort['course_id']}/leaderboard",
        headers=outsider["headers"],
    )
    # Owner-scoped like every course endpoint: someone else's course is a 404,
    # not a 403, so the cohort's existence is not disclosed.
    assert response.status_code == 404


async def test_a_lone_course_is_a_cohort_of_one(client: AsyncClient) -> None:
    owner = await _register(client, SHARER)
    course = await client.post("/api/courses", json={"title": "Solo"}, headers=owner["headers"])
    assert course.status_code == 201, course.text

    board = await client.get(f"/api/courses/{course.json()['id']}/leaderboard", headers=owner["headers"])
    assert board.status_code == 200, board.text
    body = board.json()
    assert body["cohort_size"] == 1
    assert body["my_rank"] == 1
    assert body["entries"][0]["display_name"] == "Sharer"
    assert body["entries"][0]["me"] is True

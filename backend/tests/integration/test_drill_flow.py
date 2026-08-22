"""Drill, grade, EXP, and the unlock cascade."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import Attempt, NodeProgress, Question, SkillNode, User
from app.seed import DEV_USER_ID, PIANO_COURSE_ID, seed

JUNK_ANSWER = "banana banana banana"


def covering_answer(attempt_id: str) -> str:
    """An answer that genuinely covers the rubric this attempt was given.

    Derived from the stored rubric rather than hard-coded, because the rubric is
    produced by the question generator and a fixed string would be testing
    whether that generator happens to have picked particular words. What we
    actually want to assert is that coverage drives the score -- so we build a
    covering answer and compare it against junk.

    The rubric is deliberately NOT in the drill response (that would hand the
    learner the answer), hence reading it from the database here.
    """
    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(attempt_id))
        question = session.get(Question, attempt.question_id)
        return " ".join(point["point"] for point in question.rubric)


@pytest.fixture
def seeded(clean_db: None) -> dict:
    """The hand-authored fixture course. No LLM calls, no ingest latency."""
    seed()
    with sync_session() as session:
        root = session.scalar(
            select(SkillNode).where(SkillNode.course_id == PIANO_COURSE_ID, SkillNode.slug == "keyboard-layout")
        )
        vectors = session.scalar(
            select(SkillNode).where(SkillNode.course_id == PIANO_COURSE_ID, SkillNode.slug == "finger-numbers")
        )
        return {"root_id": root.id, "dependent_id": vectors.id}


@pytest.fixture
async def dev_headers(client: AsyncClient, seeded: dict) -> dict[str, str]:
    response = await client.post("/api/auth/dev-login")
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_mcq_drill_returns_choices_and_grades_without_an_llm_call(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    drill = await client.post(
        f"/api/nodes/{seeded['root_id']}/drill?question_type=mcq",
        headers={**dev_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert drill.status_code == 201, drill.text
    body = drill.json()
    assert body["question_type"] == "mcq"
    assert len(body["options"]) == 4

    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(body["attempt_id"]))
        question = session.get(Question, attempt.question_id)
        correct_option_id = question.correct_option_id

    graded = await client.post(
        f"/api/attempts/{body['attempt_id']}/grade",
        headers=dev_headers,
        json={"answer": correct_option_id},
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["score"] == 1.0

    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(body["attempt_id"]))
    assert attempt.grade_llm_call_id is None
    assert attempt.prompt_version == "deterministic/mcq-v1"


async def test_drill_generates_a_question_with_sources(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    response = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["question"].strip()
    assert body["node_title"] == "Keyboard Layout"
    assert 1 <= body["difficulty"] <= 5
    assert body["sources"]
    assert all(source["document_id"] for source in body["sources"])


async def test_drilling_a_locked_node_is_refused(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """`finger-numbers` needs `keyboard-layout` first."""
    response = await client.post(f"/api/nodes/{seeded['dependent_id']}/drill", headers=dev_headers)
    assert response.status_code == 409


async def test_idempotency_key_returns_the_same_attempt(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """A retry must not pay for a second generation call."""
    headers = {**dev_headers, "Idempotency-Key": "abc-123"}
    first = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=headers)
    second = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=headers)

    assert first.json()["attempt_id"] == second.json()["attempt_id"]
    with sync_session() as session:
        assert len(session.scalars(select(Question)).all()) == 1


async def test_a_good_answer_scores_higher_than_junk(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """The property the whole EXP and SRS loop rests on."""
    good_drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    good = await client.post(
        f"/api/attempts/{good_drill.json()['attempt_id']}/grade",
        headers=dev_headers,
        json={"answer": covering_answer(good_drill.json()["attempt_id"])},
    )
    assert good.status_code == 200, good.text

    junk_drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    junk = await client.post(
        f"/api/attempts/{junk_drill.json()['attempt_id']}/grade",
        headers=dev_headers,
        json={"answer": JUNK_ANSWER},
    )

    assert good.json()["score"] > junk.json()["score"]
    assert good.json()["exp_awarded"] > junk.json()["exp_awarded"]
    assert junk.json()["verdict"] == "incorrect"


async def test_grading_awards_exp_and_advances_the_schedule(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    result = (
        await client.post(
            f"/api/attempts/{drill.json()['attempt_id']}/grade",
            headers=dev_headers,
            json={"answer": covering_answer(drill.json()["attempt_id"])},
        )
    ).json()

    assert result["exp_awarded"] > 0
    assert result["user_total_exp"] == result["exp_awarded"]
    assert result["progress"]["exp"] == result["exp_awarded"]
    # A pass schedules the first review a day out.
    assert result["progress"]["due_at"] is not None
    assert result["progress"]["state"] in {"learning", "available", "mastered"}


async def test_progress_analytics_tracks_a_graded_drill(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    attempt_id = drill.json()["attempt_id"]
    await client.post(
        f"/api/attempts/{attempt_id}/grade",
        headers=dev_headers,
        json={"answer": covering_answer(attempt_id)},
    )

    response = await client.get(f"/api/courses/{PIANO_COURSE_ID}/progress", headers=dev_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_skills"] > 0
    assert body["started_skills"] == 1
    assert body["total_attempts"] == 1
    assert body["exp_earned"] > 0
    assert body["mastery_trend"]
    assert body["mastery_trend"][-1]["attempts"] == 1


async def test_grading_twice_never_double_awards(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """A retry after a dropped connection must be free."""
    drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    attempt_id = drill.json()["attempt_id"]

    first = await client.post(
        f"/api/attempts/{attempt_id}/grade", headers=dev_headers, json={"answer": covering_answer(attempt_id)}
    )
    second = await client.post(
        f"/api/attempts/{attempt_id}/grade", headers=dev_headers, json={"answer": covering_answer(attempt_id)}
    )

    assert second.status_code == 200
    assert second.json()["exp_awarded"] == first.json()["exp_awarded"]
    assert second.json()["user_total_exp"] == first.json()["user_total_exp"]

    with sync_session() as session:
        user = session.get(User, DEV_USER_ID)
        progress = session.get(NodeProgress, (DEV_USER_ID, seeded["root_id"]))
    assert user.total_exp == first.json()["exp_awarded"]
    assert progress.exp == first.json()["exp_awarded"]


async def test_passing_a_root_unlocks_its_dependent(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """The unlock cascade -- the payoff of the tech-tree metaphor."""
    graph_before = (await client.get(f"/api/courses/{PIANO_COURSE_ID}/graph", headers=dev_headers)).json()
    vectors_before = next(n for n in graph_before["nodes"] if n["slug"] == "finger-numbers")
    assert vectors_before["progress"]["state"] == "locked"

    # Mastery is an EMA, so one perfect answer only reaches 0.4 -- below the 0.5
    # unlock threshold. Two are needed, which is the intended pacing.
    for _ in range(3):
        drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
        await client.post(
            f"/api/attempts/{drill.json()['attempt_id']}/grade",
            headers=dev_headers,
            json={"answer": covering_answer(drill.json()["attempt_id"])},
        )

    graph_after = (await client.get(f"/api/courses/{PIANO_COURSE_ID}/graph", headers=dev_headers)).json()
    vectors_after = next(n for n in graph_after["nodes"] if n["slug"] == "finger-numbers")
    assert vectors_after["progress"]["state"] == "available", graph_after["stats"]


async def test_attempt_records_the_prompt_version(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """Without this, 'which prompt produced this grade?' is unanswerable later."""
    drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    await client.post(
        f"/api/attempts/{drill.json()['attempt_id']}/grade",
        headers=dev_headers,
        json={"answer": covering_answer(drill.json()["attempt_id"])},
    )

    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(drill.json()["attempt_id"]))
        question = session.get(Question, attempt.question_id)

    assert attempt.prompt_version == "grade/v1"
    assert question.prompt_version == "question_gen/v3"
    assert attempt.points_hit or attempt.points_missed


async def test_another_users_attempt_is_not_gradeable(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    drill = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)

    other = await client.post(
        "/api/auth/register",
        json={"email": "thief@example.com", "password": "hunter22-long-enough", "display_name": "Thief"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = await client.post(
        f"/api/attempts/{drill.json()['attempt_id']}/grade", headers=headers, json={"answer": "hi"}
    )
    assert response.status_code == 404


async def test_non_assessable_nodes_cannot_be_drilled(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """Structural concepts carry the tree's shape but have nothing to ask about."""
    with sync_session() as session:
        node = session.get(SkillNode, seeded["root_id"])
        node.assessable = False

    response = await client.post(f"/api/nodes/{seeded['root_id']}/drill", headers=dev_headers)
    assert response.status_code == 409


async def test_the_first_pass_bonus_cannot_be_farmed_by_failing(
    client: AsyncClient, dev_headers: dict[str, str], seeded: dict
) -> None:
    """A lapse resets `reps` to 0, which used to make "first pass" true again.

    Alternating a perfect answer with a blank one therefore paid the +50 bonus
    on every cycle, without limit -- and the deterministic fake grader makes
    that trivially scriptable.
    """
    node_id = seeded["root_id"]

    async def drill_and_answer(answer_of) -> dict:
        drill = await client.post(
            f"/api/nodes/{node_id}/drill",
            headers={**dev_headers, "Idempotency-Key": str(uuid.uuid4())},
        )
        attempt_id = drill.json()["attempt_id"]
        graded = await client.post(
            f"/api/attempts/{attempt_id}/grade",
            headers=dev_headers,
            json={"answer": answer_of(attempt_id)},
        )
        return graded.json()

    first = await drill_and_answer(covering_answer)
    assert first["exp_awarded"] > 100, "first genuine pass should carry the bonus"

    # Fail it, which lapses the node and resets reps to 0.
    await drill_and_answer(lambda _: "banana banana banana")

    # Passing again is a RECOVERY, not a first pass.
    recovered = await drill_and_answer(covering_answer)
    assert recovered["exp_awarded"] <= first["exp_awarded"] - 50, (
        f"bonus was paid twice: {first['exp_awarded']} then {recovered['exp_awarded']}"
    )

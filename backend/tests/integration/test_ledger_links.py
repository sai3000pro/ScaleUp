"""Two holes in the ledger, both of which made `GET /courses/{id}/cost` a partial answer.

1. `attempts.grade_llm_call_id` has carried a foreign key to `llm_calls` since
   the first migration, and `models/attempt.py` opens by claiming attempts carry
   it "from day one" -- but nothing ever wrote it, so every join from a grade to
   what that grade cost returned empty.

2. Embedding spend happened entirely outside the ledger. `text-embedding-3-small`
   is priced in `registry.py` and was never charged, so the cost endpoint
   understated a real-key ingest by every token it embedded.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.llm.base import LLMRole
from app.models import Attempt, Chunk, LlmCall, Question, SkillNode
from app.seed import PIANO_COURSE_ID, seed
from app.services.llm_gateway import EMBED_ROLE


@pytest.fixture
def seeded(clean_db: None) -> uuid.UUID:
    seed()
    with sync_session() as session:
        node = session.scalar(
            select(SkillNode).where(SkillNode.course_id == PIANO_COURSE_ID, SkillNode.slug == "keyboard-layout")
        )
        return node.id


@pytest.fixture
async def dev_headers(client: AsyncClient, seeded: uuid.UUID) -> dict[str, str]:
    response = await client.post("/api/auth/dev-login")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def covering_answer(attempt_id: str) -> str:
    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(attempt_id))
        question = session.get(Question, attempt.question_id)
        return " ".join(point["point"] for point in question.rubric)


# ── grade_llm_call_id ─────────────────────────────────────────────────────


async def test_a_graded_attempt_names_the_ledger_row_that_graded_it(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """The join that returned empty for the whole of stage 1.

    Asserted end to end: the id on the attempt must resolve to a real
    `llm_calls` row, and that row must be the GRADE call -- not the question
    generation that preceded it on the same client.
    """
    drill = await client.post(f"/api/nodes/{seeded}/drill", headers=dev_headers)
    attempt_id = drill.json()["attempt_id"]
    await client.post(
        f"/api/attempts/{attempt_id}/grade",
        headers=dev_headers,
        json={"answer": covering_answer(attempt_id)},
    )

    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(attempt_id))
        assert attempt.grade_llm_call_id is not None

        # The foreign key is satisfied because the ledger commits on its own
        # short-lived session, so the row was durable before the attempt's
        # transaction closed.
        call = session.get(LlmCall, attempt.grade_llm_call_id)
        assert call is not None
        assert call.role == str(LLMRole.GRADE)
        assert call.prompt_version == attempt.prompt_version.split("/")[-1]
        assert call.course_id == PIANO_COURSE_ID


async def test_a_lost_ledger_write_does_not_fail_the_grade(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bookkeeping observes the pipeline; it must never gate it.

    `record()` swallows its own failure and returns None, and the column is
    nullable precisely so that None is a legal answer rather than a 500 over a
    grade the learner already earned.
    """
    from app.repositories import llm_calls

    drill = await client.post(f"/api/nodes/{seeded}/drill", headers=dev_headers)
    attempt_id = drill.json()["attempt_id"]

    monkeypatch.setattr(llm_calls, "sync_session", lambda: (_ for _ in ()).throw(RuntimeError("no db")))

    response = await client.post(
        f"/api/attempts/{attempt_id}/grade",
        headers=dev_headers,
        json={"answer": covering_answer(attempt_id)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["exp_awarded"] > 0

    with sync_session() as session:
        assert session.get(Attempt, uuid.UUID(attempt_id)).grade_llm_call_id is None


# ── embedding spend ───────────────────────────────────────────────────────


async def test_embedding_spend_reaches_the_ledger_and_the_cost_endpoint(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """A reindex's entire cost is embeddings, so this is the one it must report."""
    with sync_session() as session:
        assert session.scalars(select(LlmCall).where(LlmCall.role == EMBED_ROLE)).first() is None

    response = await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)
    assert response.status_code == 202, response.text

    with sync_session() as session:
        rows = list(session.scalars(select(LlmCall).where(LlmCall.role == EMBED_ROLE)))
        chunks = session.scalar(select(Chunk.id).where(Chunk.course_id == PIANO_COURSE_ID))

    assert chunks is not None
    assert rows, "re-embedding a whole course must leave a row in the ledger"
    assert all(row.status == "ok" for row in rows)
    assert all(row.course_id == PIANO_COURSE_ID for row in rows)
    assert sum(row.input_tokens for row in rows) > 0
    # FakeProvider costs nothing and the ledger must say so rather than guess --
    # the model recorded against it is "fake", not the configured OpenAI model.
    assert all(row.model == "fake" for row in rows)
    assert all(float(row.cost_usd) == 0.0 for row in rows)

    cost = (await client.get(f"/api/courses/{PIANO_COURSE_ID}/cost", headers=dev_headers)).json()
    assert EMBED_ROLE in {item["role"] for item in cost["by_role"]}


def test_a_priced_embedding_model_is_actually_charged() -> None:
    """The price table entry that existed and was never applied."""
    from app.llm.registry import price_for

    assert price_for("text-embedding-3-small", 1_000_000, 0) > 0

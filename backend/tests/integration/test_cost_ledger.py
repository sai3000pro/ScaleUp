"""The `llm_calls` ledger and the per-course cost endpoint.

The regression these tests exist for is not subtle: the table, the model, the
price table and the `attempts.grade_llm_call_id` foreign key all shipped, and
then never received a single row for the whole of stage 1, because writing one
was every caller's job and therefore nobody's. Assert that calls are recorded
*through the seam services actually use*, not by calling the recorder directly.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.llm.base import LLMRole, ProviderError, RefusalError, SchemaValidationError, StructuredResult
from app.models import Attempt, LlmCall, Question, SkillNode
from app.seed import PIANO_COURSE_ID, seed
from app.services.llm_gateway import EMBED_ROLE, RecordingLLMClient, status_for_error


def ledger_rows() -> list[LlmCall]:
    with sync_session() as session:
        return list(session.scalars(select(LlmCall).order_by(LlmCall.created_at)))


def covering_answer(attempt_id: str) -> str:
    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(attempt_id))
        question = session.get(Question, attempt.question_id)
        return " ".join(point["point"] for point in question.rubric)


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


# ── the seam records ──────────────────────────────────────────────────────


async def test_a_drill_and_grade_each_leave_a_ledger_row(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    assert ledger_rows() == []

    drill = await client.post(f"/api/nodes/{seeded}/drill", headers=dev_headers)
    attempt_id = drill.json()["attempt_id"]
    await client.post(
        f"/api/attempts/{attempt_id}/grade",
        headers=dev_headers,
        json={"answer": covering_answer(attempt_id)},
    )

    rows = ledger_rows()
    # `embedding` leads because retrieval tops up the node's own provenance
    # chunks with semantic neighbours before the question is generated. It is in
    # the ledger now: embedding is billable, and leaving it out understated the
    # cost of every drill and of an entire vector reindex.
    assert [row.role for row in rows] == [EMBED_ROLE, str(LLMRole.QUESTION_GEN), str(LLMRole.GRADE)]
    assert all(row.status == "ok" for row in rows)
    assert all(row.course_id == PIANO_COURSE_ID for row in rows)
    # The column the table exists for: which exact prompt bytes produced this.
    # Embeddings have no prompt, so they carry a sentinel of the right width
    # rather than a fabricated hash.
    prompted = [row for row in rows if row.role != EMBED_ROLE]
    assert all(len(row.prompt_sha256) == 64 for row in rows)
    assert all(row.prompt_id and row.prompt_version for row in rows)
    assert all(row.latency_ms is not None for row in rows)
    assert all(row.prompt_sha256 != "-" * 64 for row in prompted)


async def test_a_regraded_attempt_does_not_bill_twice(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """Grading is idempotent, so the ledger must not grow on a repeat."""
    drill = await client.post(f"/api/nodes/{seeded}/drill", headers=dev_headers)
    attempt_id = drill.json()["attempt_id"]
    body = {"answer": covering_answer(attempt_id)}

    await client.post(f"/api/attempts/{attempt_id}/grade", headers=dev_headers, json=body)
    after_first = len(ledger_rows())
    await client.post(f"/api/attempts/{attempt_id}/grade", headers=dev_headers, json=body)

    assert len(ledger_rows()) == after_first


# ── failures are the rows that matter most ────────────────────────────────


class ExplodingClient:
    """Implements app.llm.base.LLMClient by always failing."""

    provider = "fake"

    def __init__(self, error: Exception) -> None:
        self._error = error

    def model_for(self, role: LLMRole) -> str:
        return "fake"

    async def structured(self, role, variables, *, course_id=None) -> StructuredResult:
        raise self._error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SchemaValidationError("concepts.0.title: '1' is too short"), "schema_error"),
        (RefusalError("declined"), "refusal"),
        (ProviderError("503"), "provider_error"),
        (TimeoutError("timed out"), "timeout"),
    ],
)
async def test_a_failed_call_is_recorded_with_its_status(
    seeded: uuid.UUID, error: Exception, expected: str
) -> None:
    """A schema error still burned output tokens. It belongs in the ledger."""
    recorder = RecordingLLMClient(ExplodingClient(error), course_id=PIANO_COURSE_ID)

    with pytest.raises(type(error)):
        await recorder.structured(
            LLMRole.GRAPH_EXTRACT_MAP,
            {"book_title": "b", "section_path": "1", "chunks": "[0] some text"},
        )

    [row] = ledger_rows()
    assert row.status == expected
    assert row.error and type(error).__name__ in row.error
    # A failure row with an empty model is the row you least want empty.
    assert row.model == "fake"
    assert row.role == str(LLMRole.GRAPH_EXTRACT_MAP)
    assert row.course_id == PIANO_COURSE_ID
    # Recovered by re-deriving the prompt identity, since there is no result to
    # read it from. `prepare` is pure, so this is what the failed call used.
    assert len(row.prompt_sha256) == 64
    assert row.prompt_id == "graph_extract"


async def test_a_call_whose_prompt_will_not_render_is_still_recorded(seeded: uuid.UUID) -> None:
    """The last-resort branch: a variable is missing, so `prepare` itself raises.

    Recording "unknown" beats recording nothing -- the call still happened, and
    a silent gap in the ledger is what this whole table exists to prevent.
    """
    recorder = RecordingLLMClient(ExplodingClient(ProviderError("503")), course_id=PIANO_COURSE_ID)

    with pytest.raises(ProviderError):
        await recorder.structured(LLMRole.GRAPH_EXTRACT_MAP, {"book_title": "only one variable"})

    [row] = ledger_rows()
    assert row.status == "provider_error"
    assert row.prompt_sha256 == "unknown"
    assert row.model == "fake"


def test_status_mapping_prefers_the_most_specific_type() -> None:
    """SchemaValidationError and RefusalError are both LLMError; order matters."""
    assert status_for_error(SchemaValidationError("x")) == "schema_error"
    assert status_for_error(RefusalError("x")) == "refusal"
    assert status_for_error(TimeoutError("x")) == "timeout"
    assert status_for_error(RuntimeError("x")) == "provider_error"


async def test_a_ledger_failure_never_breaks_the_call(
    monkeypatch: pytest.MonkeyPatch, seeded: uuid.UUID
) -> None:
    """Bookkeeping observes the pipeline; it must never gate it."""
    from app.repositories import llm_calls

    def explode(*args, **kwargs):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(llm_calls, "sync_session", explode)

    from app.llm.fake_provider import FakeLLMClient

    recorder = RecordingLLMClient(FakeLLMClient(), course_id=PIANO_COURSE_ID)
    result = await recorder.structured(
        LLMRole.QUESTION_GEN, {"node_title": "Vectors", "node_summary": "s", "context": "c"}
    )
    assert result.data["question"]


# ── the endpoint ──────────────────────────────────────────────────────────


async def test_cost_endpoint_attributes_spend_to_role_and_prompt_version(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    drill = await client.post(f"/api/nodes/{seeded}/drill", headers=dev_headers)
    attempt_id = drill.json()["attempt_id"]
    await client.post(
        f"/api/attempts/{attempt_id}/grade",
        headers=dev_headers,
        json={"answer": covering_answer(attempt_id)},
    )

    cost = (await client.get(f"/api/courses/{PIANO_COURSE_ID}/cost", headers=dev_headers)).json()

    # Three, not two: the retrieval embedding is billable spend and is now
    # attributed like any other call.
    assert cost["total_calls"] == 3
    assert cost["failed_calls"] == 0
    roles = {item["role"] for item in cost["by_role"]}
    assert roles == {EMBED_ROLE, str(LLMRole.QUESTION_GEN), str(LLMRole.GRADE)}
    assert all(item["prompt_version"] for item in cost["by_role"])
    # FakeProvider is free, and the ledger must say so rather than guess.
    assert cost["total_cost_usd"] == 0.0


async def test_cost_is_scoped_to_the_owner(client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID) -> None:
    other = await client.post(
        "/api/auth/register",
        json={"email": "nosy@example.com", "password": "hunter22-long-enough", "display_name": "N"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = await client.get(f"/api/courses/{PIANO_COURSE_ID}/cost", headers=headers)
    assert response.status_code == 404

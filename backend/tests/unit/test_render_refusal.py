"""A prompt that will not render is refused before any provider spend.

The refusal still gets its one ledger row via the failure recorder: never
zero rows, never two.
"""

from __future__ import annotations

import uuid

import pytest

from app.llm.base import LLMRole
from app.services import llm_gateway

COURSE_ID = uuid.uuid4()


class _Inner:
    provider = "fake"
    contacted = 0

    def model_for(self, role: LLMRole) -> str:
        return "fake"

    async def structured(self, role, variables, *, course_id=None):
        _Inner.contacted += 1
        raise AssertionError("the provider must not be contacted")


# @spec LLM-BUDGET-005
async def test_a_render_failure_refuses_the_call_and_leaves_one_row(monkeypatch) -> None:
    rows: list[dict] = []
    monkeypatch.setattr(llm_gateway.llm_calls, "record", lambda **kwargs: rows.append(kwargs))
    inner = _Inner()
    client = llm_gateway.RecordingLLMClient(inner, course_id=COURSE_ID)

    with pytest.raises(KeyError):
        await client.structured(LLMRole.LIVE_COACH_CUE, {"missing": "every variable"})

    assert inner.contacted == 0
    assert len(rows) == 1
    assert rows[0]["status"] != "ok"
    assert rows[0]["course_id"] == COURSE_ID


# @spec LLM-BUDGET-005
async def test_a_streamed_render_failure_refuses_the_call_and_leaves_one_row(monkeypatch) -> None:
    rows: list[dict] = []
    monkeypatch.setattr(llm_gateway.llm_calls, "record", lambda **kwargs: rows.append(kwargs))

    class Streaming(_Inner):
        async def stream_text(self, role, variables, *, course_id=None):
            yield None

    client = llm_gateway.RecordingLLMClient(Streaming(), course_id=COURSE_ID)

    with pytest.raises(KeyError):
        [delta async for delta in client.stream_text(LLMRole.LIVE_COACH_CUE, {"missing": "every variable"})]

    assert len(rows) == 1
    assert rows[0]["status"] != "ok"

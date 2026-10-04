"""Streamed calls record the provider's token counts when it reports them.

The character estimate is a stand-in for providers that do not report; a
usage delta is the truth, and the ledger row must show it.
"""

from __future__ import annotations

from decimal import Decimal

from app.llm.base import LLMRole, StreamDelta, Usage
from app.llm.fake_provider import FakeLLMClient
from app.services import llm_gateway

VARIABLES = {
    "exercise_title": "C major scale",
    "instrument": "piano",
    "cue": "rushed tempo",
    "severity": "low",
    "metric_words": "tempo",
    "deterministic_cue": "Keep going -- I'm listening.",
    "recent_utterances": "(none)",
}


class _Inner:
    provider = "fake"

    def __init__(self, deltas: list[StreamDelta]) -> None:
        self._deltas = deltas

    def model_for(self, role: LLMRole) -> str:
        return "fake"

    async def stream_text(self, role, variables, *, course_id=None):
        for delta in self._deltas:
            yield delta


def _recorded_rows(monkeypatch) -> list[dict]:
    rows: list[dict] = []
    monkeypatch.setattr(llm_gateway.llm_calls, "record", lambda **kwargs: rows.append(kwargs))
    return rows


# @spec LLM-PROV-006
async def test_the_fake_stream_ends_with_a_usage_delta() -> None:
    deltas = [delta async for delta in FakeLLMClient().stream_text(LLMRole.LIVE_COACH_CUE, VARIABLES)]

    assert deltas[-1].usage is not None
    assert deltas[-1].text == ""
    assert all(delta.text for delta in deltas[:-1])


# @spec LLM-PROV-006
async def test_reported_usage_beats_the_character_estimate(monkeypatch) -> None:
    rows = _recorded_rows(monkeypatch)
    inner = _Inner(
        [
            StreamDelta(text="Keep going"),
            StreamDelta(
                text="",
                usage=Usage(input_tokens=11, output_tokens=7, cost_usd=Decimal("0.001")),
            ),
        ]
    )
    client = llm_gateway.RecordingLLMClient(inner)

    [delta async for delta in client.stream_text(LLMRole.LIVE_COACH_CUE, VARIABLES)]

    assert len(rows) == 1
    assert (rows[0]["input_tokens"], rows[0]["output_tokens"]) == (11, 7)


# @spec LLM-PROV-006
async def test_the_estimate_stands_in_when_nothing_is_reported(monkeypatch) -> None:
    rows = _recorded_rows(monkeypatch)
    client = llm_gateway.RecordingLLMClient(_Inner([StreamDelta(text="Keep going")]))

    [delta async for delta in client.stream_text(LLMRole.LIVE_COACH_CUE, VARIABLES)]

    assert len(rows) == 1
    assert rows[0]["input_tokens"] > 0
    assert rows[0]["output_tokens"] == len("Keep going") // 4

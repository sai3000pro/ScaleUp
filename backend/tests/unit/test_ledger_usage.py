"""A repair turn is two billed calls, and the ledger must say so.

`llm_calls` exists to answer "what did this ingest cost", and `models/llm_call.py`
singles out this exact case: a rejected response still burned output tokens. Both
providers rebound the response variable on repair and then read usage off it, so
the first call -- the one that failed -- was charged by the provider and absent
from the ledger. The ledger undercounted precisely the case it was built for.

Driven through the real `structured()` with only the transport stubbed, so these
fail if the accumulation regresses, whatever shape the fix takes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.base import LLMRole

VARIABLES = {
    "book_title": "LA",
    "section_path": "1",
    "chunks": "[0] A vector is an ordered list of numbers and vectors add componentwise.",
}
_SUMMARY = "Understand and apply vectors as presented in this section."
VALID = (
    '{"concepts": [{"slug": "vectors", "title": "Vectors", "summary": "'
    + _SUMMARY
    + '", "difficulty": 2, "assessable": true}], "prerequisites": []}'
)
# Fails the schema on the slug pattern, which is what triggers the repair turn.
GARBAGE = '{"concepts": [{"slug": "NOT A SLUG"}], "prerequisites": []}'


def _anthropic(monkeypatch, turns):
    from app.llm import anthropic_provider

    monkeypatch.setattr(anthropic_provider, "AsyncAnthropic", lambda **_: object())
    client = anthropic_provider.AnthropicLLMClient()

    calls = iter(turns)

    async def fake_request(prompt, call, model):
        text, tokens_in, tokens_out = next(calls)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
        )

    monkeypatch.setattr(client, "_request", fake_request)
    return client


def _openai(monkeypatch, turns):
    from app.llm import openai_provider

    monkeypatch.setattr(openai_provider, "AsyncOpenAI", lambda **_: object())
    client = openai_provider.OpenAILLMClient()

    calls = iter(turns)

    async def fake_request(prompt, call, model):
        text, tokens_in, tokens_out = next(calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
        )

    monkeypatch.setattr(client, "_request", fake_request)
    return client


@pytest.mark.parametrize("build", [_anthropic, _openai], ids=["anthropic", "openai"])
async def test_a_clean_call_reports_its_own_usage(monkeypatch, build) -> None:
    client = build(monkeypatch, [(VALID, 100, 20)])
    result = await client.structured(LLMRole.GRAPH_EXTRACT_MAP, VARIABLES)
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 20)


@pytest.mark.parametrize("build", [_anthropic, _openai], ids=["anthropic", "openai"])
async def test_a_repair_turn_bills_both_calls(monkeypatch, build) -> None:
    """The failed turn's tokens were charged, so they must be counted."""
    client = build(monkeypatch, [(GARBAGE, 100, 20), (VALID, 130, 25)])
    result = await client.structured(LLMRole.GRAPH_EXTRACT_MAP, VARIABLES)

    assert result.usage.input_tokens == 230, "first turn's input tokens were dropped"
    assert result.usage.output_tokens == 45, "first turn's output tokens were dropped"


@pytest.mark.parametrize("build", [_anthropic, _openai], ids=["anthropic", "openai"])
async def test_cost_is_priced_on_the_accumulated_totals(monkeypatch, build) -> None:
    """Priced against the exact expected total, not merely "more than clean".

    A repair turn is usually the LARGER of the two, so `repaired > clean` held
    even with the bug present -- it compared the second turn alone against the
    first alone and both orderings looked right.
    """
    from app.llm.registry import price_for

    client = build(monkeypatch, [(GARBAGE, 100, 20), (VALID, 130, 25)])
    result = await client.structured(LLMRole.GRAPH_EXTRACT_MAP, VARIABLES)

    assert result.usage.cost_usd == price_for(result.model, 230, 45)

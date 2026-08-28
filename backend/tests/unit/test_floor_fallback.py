"""The deterministic provider as the floor under a credentialed one.

The behaviour under test is what a learner experiences during a provider outage.
Before this floor existed, a Gemini 503 -- which its shared free tier returns on
its stronger aliases for minutes at a time -- travelled all the way up as an
unhandled exception, so `POST /drill` answered 500 and the browser, because an
unhandled exception escapes outside CORSMiddleware, reported only "Failed to
fetch". The drill did not degrade; it disappeared.

Two properties matter and they pull against each other, so both are pinned here:
the call must be *served* rather than raised, and it must be *recorded as
degraded* rather than passed off as the paid answer it is not.
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMRole, ProviderError, RefusalError, SchemaValidationError
from app.llm.fake_provider import FakeLLMClient
from app.llm.resilient import FloorFallbackLLMClient

QUESTION_VARIABLES = {
    "node_title": "Thumb-under",
    "node_summary": "Passing the thumb under the hand mid-scale.",
    "context": "(no source material available)",
    "requested_type": "short_answer",
}


class _Failing:
    """A credentialed provider that is having the bad minute."""

    provider = "gemini"

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls = 0

    def model_for(self, role: LLMRole) -> str:
        del role
        return "gemini-flash-latest"

    async def structured(self, role, variables, *, course_id=None):
        del role, variables, course_id
        self.calls += 1
        raise self._error


# @spec LLM-PROV-012
@pytest.mark.asyncio
async def test_a_provider_outage_is_served_by_the_floor_rather_than_raised() -> None:
    primary = _Failing(ProviderError("gemini error 503"))
    client = FloorFallbackLLMClient(primary, FakeLLMClient())

    result = await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)

    assert primary.calls == 1
    assert result.data["question"]
    assert result.data["rubric"]


# @spec LLM-PROV-013
@pytest.mark.asyncio
async def test_a_degraded_call_names_the_floor_so_the_ledger_can_tell_them_apart() -> None:
    """`llm_gateway` writes `result.provider`, so this is what reaches the ledger."""
    client = FloorFallbackLLMClient(_Failing(ProviderError("gemini error 503")), FakeLLMClient())

    result = await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)

    assert result.provider == "fake"
    assert result.model == "fake"
    assert result.usage.cost_usd == 0
    # What was *configured* is still readable; only the served call is degraded.
    assert client.provider == "gemini"


# @spec LLM-PROV-012
@pytest.mark.asyncio
@pytest.mark.parametrize("error", [SchemaValidationError("bad shape"), RefusalError("declined")])
async def test_the_model_answering_badly_is_not_an_outage(error: BaseException) -> None:
    """A schema failure and a refusal are defects worth seeing, not outages to paper over."""
    client = FloorFallbackLLMClient(_Failing(error), FakeLLMClient())

    with pytest.raises(type(error)):
        await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)


# @spec LLM-PROV-012
@pytest.mark.asyncio
async def test_a_healthy_provider_is_not_second_guessed() -> None:
    served = FakeLLMClient()
    client = FloorFallbackLLMClient(served, FakeLLMClient())

    result = await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)

    assert result.provider == "fake"


# @spec LLM-PROV-002, LLM-PROV-012
def test_selecting_the_deterministic_provider_is_not_wrapped() -> None:
    """The floor under the floor is nothing; wrapping it would only hide a stack frame."""
    from app.config import Settings
    from app.llm import factory

    factory.get_llm_client.cache_clear()
    original = factory.get_settings
    factory.get_settings = lambda: Settings(_env_file=None, llm_provider="fake")
    try:
        assert isinstance(factory.get_llm_client(), FakeLLMClient)
    finally:
        factory.get_settings = original
        factory.get_llm_client.cache_clear()

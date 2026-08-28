"""Gemini as a provider in its own right, asserted without a key or a network.

Three things are worth pinning here, and none of them need Google to answer.

The registry has to name a Gemini model for every role and price every one of
them, because the moment it does not, a call is either unroutable or billed at
zero and the cost ledger quietly stops meaning anything.

The factory has to refuse clearly. A provider selected without its credential and
an unimplemented provider name are both configuration mistakes someone makes at
2am, and the message is the whole product at that moment.

And streaming has to actually be there. Gemini is selected partly *because* it
streams -- if it silently did not, the live coach would fall back to its
deterministic floor and nothing would look broken.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from openai import APIStatusError

from app.config import Settings
from app.llm import factory, gemini_provider
from app.llm.base import LLMRole, ProviderError
from app.llm.gemini_provider import UNSUPPORTED_SCHEMA_KEYWORDS, GeminiLLMClient, _wire_schema
from app.llm.registry import LANE_TIMEOUT_SECONDS, LANES, PRICES, ROLES, price_for


def _settings(**overrides) -> Settings:
    """Settings built from the overrides alone.

    `_env_file=None` is load-bearing. Without it these construct from the
    developer's own `.env`, which makes every assertion here depend on whose
    machine it runs on -- and puts a real credential into pytest's diff output
    the moment one of them fails.
    """
    return Settings(_env_file=None, **overrides)


#: Everything `live_coach_cue/v1` interpolates. The role is used throughout
#: because it is both the streaming role and the smallest schema in the registry.
CUE_VARIABLES = {
    "cue": "BOW_PRESSURE",
    "severity": "notice",
    "instrument": "violin",
    "exercise_title": "Open strings",
    "metric_words": "tone is thin and scratchy",
    "recent_utterances": "(none)",
    "deterministic_cue": "Ease off the bow.",
}


# @spec LLM-PROV-003
def test_every_role_names_a_gemini_model_and_every_one_is_priced() -> None:
    for role, config in ROLES.items():
        assert config.gemini_model, f"{role} has no Gemini model"
        assert config.gemini_model in PRICES, f"{config.gemini_model} is unpriced, so it would bill as free"
        rate_in, rate_out = PRICES[config.gemini_model]
        assert rate_in > Decimal(0) and rate_out > Decimal(0)


# @spec LLM-PROV-003
def test_gemini_does_not_borrow_another_providers_model_name() -> None:
    """The column exists so the ledger prices the model that actually ran."""
    for config in ROLES.values():
        assert config.gemini_model not in {config.anthropic_model, config.openai_model}
        assert config.gemini_model.startswith("gemini-")


# @spec LLM-PROV-002
def test_selecting_gemini_without_a_key_names_the_setting_and_the_alternative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings(llm_provider="gemini", gemini_api_key=""))
    factory.get_llm_client.cache_clear()

    with pytest.raises(RuntimeError) as caught:
        factory.get_llm_client()

    message = str(caught.value)
    assert "GEMINI_API_KEY" in message
    assert "fake" in message
    factory.get_llm_client.cache_clear()


# @spec LLM-PROV-001
def test_an_unimplemented_provider_name_is_refused_rather_than_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings(llm_provider="bard"))
    factory.get_llm_client.cache_clear()

    with pytest.raises(RuntimeError) as caught:
        factory.get_llm_client()

    assert "gemini" in str(caught.value), "the refusal should list what is actually available"
    factory.get_llm_client.cache_clear()


# @spec LLM-PROV-001
def test_a_configured_key_selects_the_gemini_client(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = _settings(llm_provider="gemini", gemini_api_key="k")
    monkeypatch.setattr(factory, "get_settings", lambda: configured)
    monkeypatch.setattr(gemini_provider, "get_settings", lambda: configured)
    factory.get_llm_client.cache_clear()

    client = factory.get_llm_client()

    assert client.provider == "gemini"
    assert client.model_for(LLMRole.CURRICULUM_PLAN) == ROLES[LLMRole.CURRICULUM_PLAN].gemini_model
    factory.get_llm_client.cache_clear()


# @spec LLM-PROV-004
def test_gemini_is_the_credentialed_provider_that_streams() -> None:
    from app.llm.anthropic_provider import AnthropicLLMClient
    from app.llm.openai_provider import OpenAILLMClient

    assert hasattr(GeminiLLMClient, "stream_text")
    assert not hasattr(AnthropicLLMClient, "stream_text")
    assert not hasattr(OpenAILLMClient, "stream_text")


class _Completions:
    """Stands in for `AsyncOpenAI().chat.completions`, recording what it was sent."""

    def __init__(self, payload: str, chunks: list[str] | None = None) -> None:
        self.payload = payload
        self.chunks = chunks or []
        self.seen: dict = {}

    async def create(self, **kwargs):
        self.seen = kwargs
        if kwargs.get("stream"):
            return _Stream(self.chunks)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.payload))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


class _Stream:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for text in self._chunks:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])
            # Providers routinely end with a content-free chunk.
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))])

        return gen()


def _client_with(completions: _Completions) -> GeminiLLMClient:
    """One stub behind every lane, so a test asserts behaviour rather than routing."""
    client = GeminiLLMClient.__new__(GeminiLLMClient)
    stub = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._clients = {lane: stub for lane in LANES}
    return client


# @spec LLM-PROV-003
async def test_a_structured_call_reports_gemini_and_prices_the_model_that_ran() -> None:
    payload = json.dumps({"utterance": "Ease off the bow pressure."})
    completions = _Completions(payload)
    client = _client_with(completions)

    result = await client.structured(LLMRole.LIVE_COACH_CUE, CUE_VARIABLES)

    assert result.provider == "gemini"
    assert result.model == ROLES[LLMRole.LIVE_COACH_CUE].gemini_model
    assert result.data["utterance"] == "Ease off the bow pressure."
    assert result.usage.cost_usd > Decimal(0), "a real call priced at zero is a hole in the ledger"
    # The wire schema is the shared one narrowed to what Gemini accepts -- never an
    # OpenAI strict-mode rewrite, and never a different schema.
    wire = completions.seen["response_format"]["json_schema"]["schema"]
    assert wire == _wire_schema(client_schema())


def _keywords(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for value in node.values() for k in _keywords(value)}
    if isinstance(node, list):
        return {k for item in node for k in _keywords(item)}
    return set()


# @spec LLM-PROV-003
def test_the_wire_schema_drops_only_what_gemini_refuses() -> None:
    """Narrowing must not become "send something else".

    Gemini answers 400 without naming the keyword it disliked, so the list is
    subtractive and easy to over-trim. Structure -- properties, required, types --
    has to survive intact, because that is what steers the answer.
    """
    full = client_schema()
    wire = _wire_schema(full)

    assert not _keywords(wire) & UNSUPPORTED_SCHEMA_KEYWORDS
    assert _keywords(full) - _keywords(wire) <= UNSUPPORTED_SCHEMA_KEYWORDS
    assert wire["properties"].keys() == full["properties"].keys()
    assert wire.get("required") == full.get("required")


def client_schema() -> dict:
    from app.llm.support import prepare

    return prepare(LLMRole.LIVE_COACH_CUE, CUE_VARIABLES, "gemini-flash-lite-latest").schema


# @spec LLM-PROV-004
async def test_streaming_yields_text_as_it_arrives_and_skips_empty_chunks() -> None:
    completions = _Completions("", chunks=["Ease ", "off ", "the bow."])
    client = _client_with(completions)

    seen = [delta.text async for delta in client.stream_text(LLMRole.LIVE_COACH_CUE, CUE_VARIABLES)]

    assert seen == ["Ease ", "off ", "the bow."], "a content-free final chunk is not a delta"
    assert completions.seen["stream"] is True


# @spec LLM-PROV-007
def test_a_lane_key_serves_its_lane_and_the_shared_key_serves_the_rest() -> None:
    settings = _settings(gemini_api_key="shared", gemini_api_key_live="live-only")

    assert settings.gemini_key_for("live") == "live-only"
    assert settings.gemini_key_for("ingest") == "shared"
    assert settings.gemini_key_for("tutor") == "shared"


# @spec LLM-PROV-002, LLM-PROV-007
def test_a_key_on_one_lane_only_names_the_lanes_it_leaves_unserved() -> None:
    """The likely mistake is filling one lane slot and leaving the others blank.

    Reporting that as "no Gemini credential" would be a lie, and reporting it at
    first use would surface it on whichever lane a learner touched first.
    """
    assert _settings(gemini_api_key_ingest="only-ingest").gemini_lanes_without_a_key() == ("tutor", "live")
    assert _settings(gemini_api_key="shared").gemini_lanes_without_a_key() == ()
    assert _settings().gemini_lanes_without_a_key() == ("ingest", "tutor", "live")


# @spec LLM-PROV-009
def test_paying_for_one_lane_leaves_the_others_on_the_deterministic_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The realistic first day with a key: one lane paid for, the rest not yet."""
    monkeypatch.setattr(
        factory, "get_settings", lambda: _settings(llm_provider="gemini", gemini_api_key_ingest="k")
    )
    monkeypatch.setattr(
        gemini_provider, "get_settings", lambda: _settings(llm_provider="gemini", gemini_api_key_ingest="k")
    )
    factory.get_llm_client.cache_clear()

    client = factory.get_llm_client()

    assert client.lanes() == {"ingest": "gemini", "tutor": "fake", "live": "fake"}
    assert client.model_for(LLMRole.CURRICULUM_PLAN) == ROLES[LLMRole.CURRICULUM_PLAN].gemini_model
    assert client.model_for(LLMRole.GRADE) == "fake", "an unpaid lane must not reach the provider"
    factory.get_llm_client.cache_clear()


# @spec LLM-PROV-010
def test_a_fallen_back_lane_is_recorded_as_what_served_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ledger row naming the configured provider instead of the serving one is fiction."""
    monkeypatch.setattr(
        factory, "get_settings", lambda: _settings(llm_provider="gemini", gemini_api_key_ingest="k")
    )
    monkeypatch.setattr(
        gemini_provider, "get_settings", lambda: _settings(llm_provider="gemini", gemini_api_key_ingest="k")
    )
    factory.get_llm_client.cache_clear()

    client = factory.get_llm_client()

    assert client.provider_for(LLMRole.CURRICULUM_PLAN) == "gemini"
    assert client.provider_for(LLMRole.GRADE) == "fake"
    factory.get_llm_client.cache_clear()


# @spec LLM-PROV-002
def test_gemini_with_no_credential_anywhere_still_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _settings(llm_provider="gemini"))
    factory.get_llm_client.cache_clear()

    with pytest.raises(RuntimeError) as caught:
        factory.get_llm_client()

    assert "GEMINI_API_KEY" in str(caught.value)
    factory.get_llm_client.cache_clear()


# @spec LLM-PROV-008
def test_every_role_declares_a_known_lane() -> None:
    """The lane is a property of the role, so no call site ever picks a credential."""
    for role, config in ROLES.items():
        assert config.lane in LANES, f"{role} names lane {config.lane!r}"
    assert ROLES[LLMRole.LIVE_COACH_CUE].lane == "live"
    assert ROLES[LLMRole.CURRICULUM_PLAN].lane == "ingest"
    assert ROLES[LLMRole.GRADE].lane == "tutor"


# ---------------------------------------------------------------------------
# Availability: a model identifier is not a promise that the model will answer.
# ---------------------------------------------------------------------------


class _Overloaded(APIStatusError):
    """A 503 shaped like the one Google's shared free tier actually returns."""

    def __init__(self, status_code: int = 503) -> None:
        self.status_code = status_code
        Exception.__init__(self, f"error code: {status_code}")


def _stub_client(monkeypatch, answers):
    """A Gemini client whose transport pops one answer per call.

    An entry that is an exception is raised; anything else is returned. The
    models actually asked for are appended to `asked`, which is what the
    fallback assertions are really about.
    """
    asked: list[str] = []
    client = GeminiLLMClient.__new__(GeminiLLMClient)

    async def _request(_self, _client, prompt_text, call, model):
        del prompt_text, call
        asked.append(model)
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise ProviderError(f"gemini error {getattr(answer, 'status_code', '?')}") from answer
        return answer

    monkeypatch.setattr(GeminiLLMClient, "_request", _request, raising=True)
    monkeypatch.setattr(GeminiLLMClient, "_for", lambda _self, _role: object(), raising=True)
    return client, asked


def _ok_response(payload: dict):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


#: `live_coach_cue/v1`'s schema is the smallest in the registry, but it is also the
#: one role with no fallback model. QUESTION_GEN is the role the learner actually
#: waits on, so the fallback assertions use it.
QUESTION_VARIABLES = {
    "node_title": "Thumb-under",
    "node_summary": "Passing the thumb under the hand mid-scale.",
    "context": "(no source material available)",
    "requested_type": "short_answer",
}

QUESTION_PAYLOAD = {
    "question_type": "short_answer",
    "question": "Describe the thumb-under transition.",
    "options": [],
    "correct_option_id": None,
    "accepted_answers": [],
    "code_language": None,
    "code_requirements": [],
    "rubric": [{"id": "kp1", "point": "Names the thumb passing under.", "weight": 1.0}],
    "difficulty": 2,
}


# @spec LLM-PROV-011
@pytest.mark.asyncio
async def test_an_overloaded_primary_is_re_attempted_on_the_role_s_fallback_model(monkeypatch) -> None:
    client, asked = _stub_client(monkeypatch, [_Overloaded(503), _ok_response(QUESTION_PAYLOAD)])

    result = await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)

    config = ROLES[LLMRole.QUESTION_GEN]
    assert asked == [config.gemini_model, config.gemini_fallback_model]
    assert result.data["question"] == "Describe the thumb-under transition."


# @spec LLM-PROV-003, LLM-PROV-011
@pytest.mark.asyncio
async def test_a_fallen_back_call_is_priced_at_the_model_that_answered(monkeypatch) -> None:
    """The whole point of the cost table is that it is not fiction."""
    client, _ = _stub_client(monkeypatch, [_Overloaded(503), _ok_response(QUESTION_PAYLOAD)])

    result = await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)

    fallback = ROLES[LLMRole.QUESTION_GEN].gemini_fallback_model
    assert result.model == fallback
    assert result.usage.cost_usd == price_for(fallback, 100, 50)
    assert result.usage.cost_usd != price_for(ROLES[LLMRole.QUESTION_GEN].gemini_model, 100, 50)


# @spec LLM-PROV-011
@pytest.mark.asyncio
async def test_a_terminal_status_is_raised_rather_than_re_attempted(monkeypatch) -> None:
    """A 400 fails identically on the sibling; asking it twice only doubles the wait."""
    client, asked = _stub_client(monkeypatch, [_Overloaded(400)])

    with pytest.raises(ProviderError):
        await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)

    assert asked == [ROLES[LLMRole.QUESTION_GEN].gemini_model]


# @spec LLM-PROV-011
@pytest.mark.asyncio
async def test_a_role_with_no_fallback_model_does_not_re_attempt(monkeypatch) -> None:
    client, asked = _stub_client(monkeypatch, [_Overloaded(503)])
    assert not ROLES[LLMRole.LIVE_COACH_CUE].gemini_fallback_model

    with pytest.raises(ProviderError):
        await client.structured(LLMRole.LIVE_COACH_CUE, CUE_VARIABLES)

    assert asked == [ROLES[LLMRole.LIVE_COACH_CUE].gemini_model]


# @spec LLM-PROV-011
def test_every_fallback_model_is_a_different_model_and_is_priced() -> None:
    for role, config in ROLES.items():
        if not config.gemini_fallback_model:
            assert config.gemini_model in PRICES
        else:
            assert config.gemini_fallback_model != config.gemini_model, f"{role} falls back to itself"
            assert config.gemini_fallback_model in PRICES, f"{role}'s fallback is unpriced"


# @spec LLM-PROV-015
def test_the_deadline_belongs_to_the_lane_not_to_the_provider() -> None:
    """An unattended ingest and a learner mid-take are not the same deadline."""
    assert set(LANE_TIMEOUT_SECONDS) == set(LANES)
    assert LANE_TIMEOUT_SECONDS["live"] < LANE_TIMEOUT_SECONDS["tutor"] < LANE_TIMEOUT_SECONDS["ingest"]


# @spec LLM-PROV-015
def test_a_lane_deadline_is_a_ceiling_that_the_setting_can_lower(monkeypatch) -> None:
    """Lowering GEMINI_TIMEOUT_SECONDS lowers every lane; raising it cannot make
    an interactive path patient again."""
    monkeypatch.setattr(
        gemini_provider, "get_settings", lambda: _settings(gemini_api_key="k", gemini_timeout_seconds=2.0)
    )
    assert gemini_provider._client("ingest").timeout == 2.0

    monkeypatch.setattr(
        gemini_provider, "get_settings", lambda: _settings(gemini_api_key="k", gemini_timeout_seconds=600.0)
    )
    assert gemini_provider._client("tutor").timeout == LANE_TIMEOUT_SECONDS["tutor"]


# @spec LLM-PROV-011, LLM-PROV-015
def test_the_interactive_lanes_decline_the_sdk_retry_because_the_fallback_is_the_retry(monkeypatch) -> None:
    monkeypatch.setattr(
        gemini_provider, "get_settings", lambda: _settings(gemini_api_key="k", gemini_max_retries=3)
    )
    assert gemini_provider._client("tutor").max_retries == 0
    assert gemini_provider._client("live").max_retries == 0
    assert gemini_provider._client("ingest").max_retries == 3


# @spec LLM-PROV-011
@pytest.mark.asyncio
async def test_a_timed_out_primary_falls_back_rather_than_failing(monkeypatch) -> None:
    """A timeout is `this model, right now`, which is exactly what a sibling answers."""
    from openai import APITimeoutError

    timeout = APITimeoutError.__new__(APITimeoutError)
    Exception.__init__(timeout, "timed out")
    client, asked = _stub_client(monkeypatch, [timeout, _ok_response(QUESTION_PAYLOAD)])

    result = await client.structured(LLMRole.QUESTION_GEN, QUESTION_VARIABLES)

    assert asked == [ROLES[LLMRole.QUESTION_GEN].gemini_model, ROLES[LLMRole.QUESTION_GEN].gemini_fallback_model]
    assert result.data["question"]

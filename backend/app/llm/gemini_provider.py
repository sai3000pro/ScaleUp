"""Gemini-backed LLMClient, and the only real provider that can stream.

Reached through Google's OpenAI-compatible endpoint rather than the `google-genai`
SDK. Both speak the two things this application asks of a model -- a JSON object
matching a supplied schema, and a stream of prose tokens -- and the compatible
endpoint reaches them through the `openai` package this project already depends
on, over the same request and error-mapping shapes `openai_provider` has been
exercised against. A second SDK would be a new dependency for everyone and a
second set of exception types to map, in exchange for parameters no role sets.

Gemini is nevertheless a *provider*, not a flavour of OpenAI: it names its own
models in the registry, prices them in the registry's own table, and reports
`provider="gemini"` on every ledger row. Borrowing the OpenAI column would make
the ledger quote GPT prices for calls Gemini served, and that table exists to
answer what an ingest costs.

**Structured output.** The schema is narrowed before it goes on the wire --
Gemini's structured-output subset rejects several JSON Schema keywords outright,
answering 400 without naming the one it disliked. The narrowing costs nothing,
because the wire schema only steers generation: the guarantee is
`validate_or_raise` against the *full* schema plus one repair turn, so a response
that breaks a stripped constraint is caught here and corrected, exactly like one
that breaks a kept constraint.

**Streaming.** Implemented here and nowhere else among the real providers, so
selecting Gemini is what lets the live coach speak from a model rather than from
its deterministic floor. Deltas carry text only; the ledger row for a stream is
written by `services.llm_gateway`, which is where a cancelled stream still gets
recorded as cancelled.

**Availability.** Google's shared free tier answers 503 UNAVAILABLE on its stronger
aliases for minutes at a time while the cheaper alias beside it stays healthy, so a
role that names one model is only as available as that model's busiest hour. Every
role therefore names a fallback model too, and an overloaded or rate-limited primary
is re-attempted on it rather than failed. Backoff against the same alias would only
spend the learner's patience: the outage outlasts any wait worth making someone sit
through. The result names the model that actually answered, so the ledger prices the
call at what ran.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Mapping, Sequence

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError

from app.config import get_settings
from app.llm.base import (
    LLMRole,
    ProviderError,
    SchemaValidationError,
    StreamDelta,
    StructuredResult,
    Usage,
)
from app.llm.registry import LANE_TIMEOUT_SECONDS, LANES, LANES_WITHOUT_SDK_RETRY, ROLES, price_for
from app.llm.support import parse_json_or_raise, prepare, validate_or_raise

#: Google's OpenAI-compatible surface. Overridable through GEMINI_BASE_URL so a
#: proxy or a pinned API version is configuration rather than a code change.
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


#: JSON Schema keywords Gemini's structured-output subset does not accept. Sending
#: any of them answers 400 INVALID_ARGUMENT with no indication of which one, so the
#: list is subtractive rather than diagnostic.
#:
#: Dropping them is safe by construction, not by luck: the schema on the wire only
#: steers generation, while the guarantee is `validate_or_raise` against the *full*
#: schema plus one repair turn. A response that violates a stripped constraint is
#: caught locally and sent back to be corrected, exactly as a response that violates
#: a kept one is.
UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "additionalProperties",
        "default",
        "examples",
        "maxItems",
        "maxLength",
        "minItems",
        "minLength",
        "pattern",
        "title",
    }
)


#: Statuses that mean "this model, right now" rather than "this request, ever". They
#: are the ones a different model can answer, so they are the ones that fall back;
#: a 400 or a 404 would fail identically on the sibling and is raised as it arrives.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _wire_schema(node):
    """The role's schema, minus the keywords Gemini refuses."""
    if isinstance(node, dict):
        return {
            key: _wire_schema(value)
            for key, value in node.items()
            if key not in UNSUPPORTED_SCHEMA_KEYWORDS
        }
    if isinstance(node, list):
        return [_wire_schema(item) for item in node]
    return node


def _client(lane: str = "tutor") -> AsyncOpenAI:
    """A client for one workload lane, on that lane's credential.

    Built per lane rather than per call: a lane's quota is the thing being kept
    separate, so the client that carries its key is the natural unit to cache.
    """
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.gemini_key_for(lane),
        base_url=settings.gemini_base_url or DEFAULT_BASE_URL,
        # The deadline belongs to whoever is waiting, so it comes from the lane.
        # Gemini answers 503 under load and takes its time doing it -- often more
        # than a minute -- and a lane-blind timeout has to be set for the most
        # patient caller. That is how an overloaded model turned a drill into an
        # eighty-second wait that still ended on the deterministic question: the
        # fallback was right and arrived far too late to matter.
        timeout=min(settings.gemini_timeout_seconds, LANE_TIMEOUT_SECONDS[lane]),
        # The fallback model is the retry, and it is a retry against something
        # different. Asking the overloaded alias twice only doubles the wait.
        max_retries=0 if lane in LANES_WITHOUT_SDK_RETRY else settings.gemini_max_retries,
    )


class GeminiLLMClient:
    """Implements app.llm.base.LLMClient and app.llm.base.StreamingLLMClient."""

    provider = "gemini"

    def __init__(self) -> None:
        settings = get_settings()
        # Only lanes with a credential. A lane routed here without one would fail
        # inside the SDK at construction, which is the wrong place and the wrong
        # message; the factory keeps unserved lanes away from this client.
        self._clients = {lane: _client(lane) for lane in LANES if settings.gemini_key_for(lane)}

    def model_for(self, role: LLMRole) -> str:
        return ROLES[role].gemini_model

    def _for(self, role: LLMRole) -> AsyncOpenAI:
        lane = ROLES[role].lane
        client = self._clients.get(lane)
        if client is None:
            raise ProviderError(f"no Gemini credential for the {lane} lane; set GEMINI_API_KEY_{lane.upper()}")
        return client

    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        started = time.monotonic()
        model, call, response = await self._request_with_fallback(role, variables)
        text = response.choices[0].message.content or ""

        # Accumulated across turns -- a repair turn is a second billed call, and
        # reading usage off `response` after reassignment discards the first.
        # See the matching comment in anthropic_provider.
        usage_in = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        usage_out = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

        try:
            data = validate_or_raise(parse_json_or_raise(text), call.schema)
        except SchemaValidationError as first_error:
            repair = (
                f"{call.prompt_text}\n\n---\n\nYour previous response did not satisfy the schema.\n"
                f"Validator error: {first_error}\n\nReturn corrected JSON only."
            )
            response = await self._request(self._for(role), repair, call, model)
            text = response.choices[0].message.content or ""
            usage_in += getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
            usage_out += getattr(response.usage, "completion_tokens", 0) if response.usage else 0
            data = validate_or_raise(parse_json_or_raise(text), call.schema)

        return StructuredResult(
            data=data,
            raw_text=text,
            model=model,
            provider=self.provider,
            prompt_id=call.config.prompt_id,
            prompt_version=call.config.prompt_version,
            prompt_sha256=call.prompt_sha256,
            request_fingerprint=call.request_fingerprint,
            usage=Usage(
                input_tokens=usage_in,
                output_tokens=usage_out,
                cost_usd=price_for(model, usage_in, usage_out),
                latency_ms=int((time.monotonic() - started) * 1000),
            ),
        )

    # @spec LLM-PROV-004
    async def stream_text(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Yield prose as it arrives, for the one role where latency is the product."""
        del course_id
        model = ROLES[role].gemini_model
        call = prepare(role, variables, model)

        try:
            stream = await self._for(role).chat.completions.create(
                model=model,
                max_tokens=call.config.max_tokens,
                messages=[{"role": "user", "content": call.prompt_text}],
                stream=True,
            )
            async for chunk in stream:
                text = chunk.choices[0].delta.content if chunk.choices else None
                if text:
                    yield StreamDelta(text=text)
                else:
                    pass
        except (RateLimitError, APIConnectionError) as exc:
            raise ProviderError(f"gemini transient failure: {exc}") from exc
        except APIStatusError as exc:
            raise ProviderError(f"gemini error {exc.status_code}: {exc}") from exc

    async def _request(self, client: AsyncOpenAI, prompt_text: str, call, model: str):
        try:
            return await client.chat.completions.create(
                model=model,
                max_tokens=call.config.max_tokens,
                messages=[{"role": "user", "content": prompt_text}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": f"{call.config.schema_id}_{call.config.schema_version}",
                        "schema": _wire_schema(call.schema),
                    },
                },
            )
        except (RateLimitError, APIConnectionError) as exc:
            raise ProviderError(f"gemini transient failure: {exc}") from exc
        except APIStatusError as exc:
            raise ProviderError(f"gemini error {exc.status_code}: {exc}") from exc

    # @spec LLM-PROV-011
    async def _request_with_fallback(self, role: LLMRole, variables: Mapping[str, Any]):
        """The first of the role's models that answers, with the call it answered.

        `prepare` is re-run for the fallback rather than reused, because the model
        identifier is part of what it fingerprints -- a request recorded under the
        primary's name when the sibling served it is the fiction the ledger exists
        to avoid.
        """
        config = ROLES[role]
        client = self._for(role)
        primary = config.gemini_model

        call = prepare(role, variables, primary)
        try:
            return primary, call, await self._request(client, call.prompt_text, call, primary)
        except ProviderError as exc:
            fallback = config.gemini_fallback_model
            if not fallback or not _is_retryable(exc):
                raise
            else:
                pass

        call = prepare(role, variables, fallback)
        return fallback, call, await self._request(client, call.prompt_text, call, fallback)


def _is_retryable(error: ProviderError) -> bool:
    """Whether a sibling model could plausibly answer what this one would not."""
    cause = error.__cause__
    if isinstance(cause, (RateLimitError, APIConnectionError)):
        return True
    if isinstance(cause, APIStatusError):
        return cause.status_code in RETRYABLE_STATUS
    return False


class GeminiEmbeddingProvider:
    """Implements app.llm.base.EmbeddingProvider.

    Worth having even though the LLM half is the point: Anthropic has no
    embeddings endpoint, so a Claude-served deployment needs a second vendor for
    retrieval. A Gemini-served one does not.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = _client()
        self._model = settings.gemini_embedding_model
        self.dimensions = settings.embedding_dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=list(texts),
                dimensions=self.dimensions,
            )
        except (RateLimitError, APIConnectionError) as exc:
            raise ProviderError(f"gemini transient failure: {exc}") from exc
        except APIStatusError as exc:
            raise ProviderError(f"gemini error {exc.status_code}: {exc}") from exc
        return [item.embedding for item in response.data]

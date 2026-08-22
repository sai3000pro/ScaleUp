"""The single seam through which every LLM call in the app is made.

Why a wrapper rather than a `record()` call inside each provider, or at each
call site:

* **Providers stay pure.** `anthropic_provider` knows how to talk to Anthropic
  and nothing about Postgres. Adding a fourth provider does not mean
  remembering to add bookkeeping to it.
* **Call sites cannot forget.** The ledger existed as a table, a model, and a
  price table for the whole of stage 1 and never received a single row, because
  writing one was every caller's job and therefore nobody's.

It lives in `services/` because that is the layer permitted to touch both `llm`
and the persistence layer; `app/llm/` must not import repositories.

Failures are recorded too, and are the rows that matter most -- a schema error
still burned output tokens, and a run where 3 of 51 windows failed is a fact you
want in the ledger, not only in a log line that scrolled away.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from typing import Any, AsyncIterator, Mapping, Sequence

from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.ingestion.embed import embed_texts
from app.llm.base import (
    LLMClient,
    LLMError,
    LLMRole,
    ProviderError,
    RefusalError,
    SchemaValidationError,
    StreamDelta,
    StructuredResult,
)
from app.llm.factory import get_llm_client
from app.llm.registry import price_for
from app.llm.support import prepare
from app.repositories import llm_calls

__all__ = [
    "RecordingLLMClient",
    "recording_llm_client",
    "status_for_error",
    "embed_texts_recorded",
]

CHARS_PER_TOKEN = 4



def status_for_error(error: BaseException) -> str:
    """Map an exception to one of the ledger's `status` values.

    Ordered most specific first: SchemaValidationError and RefusalError are both
    LLMError, and a TimeoutError is not an LLMError at all.
    """
    if isinstance(error, SchemaValidationError):
        return "schema_error"
    if isinstance(error, RefusalError):
        return "refusal"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, (ProviderError, LLMError)):
        return "provider_error"
    return "provider_error"


class RecordingLLMClient:
    """Implements app.llm.base.LLMClient by delegating and writing a ledger row."""

    def __init__(self, inner: LLMClient, course_id: uuid.UUID | None = None) -> None:
        self._inner = inner
        self._course_id = course_id
        self.provider = inner.provider

    def model_for(self, role: LLMRole) -> str:
        return self._inner.model_for(role)

    # @spec LLM-ROLE-004, LLM-BUDGET-002, LLM-BUDGET-003, LLM-BUDGET-005, LLM-LEDGER-001, LLM-LEDGER-005
    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        started = time.monotonic()
        resolved_course = self._resolve_course(course_id)
        await run_in_threadpool(self._enforce_budget, role, variables, resolved_course)
        try:
            result = await self._inner.structured(role, variables, course_id=course_id)
        except BaseException as error:
            # Re-derive the prompt identity rather than reading it off a result
            # that does not exist. `prepare` is pure and deterministic, so this
            # reproduces exactly what the failed call used.
            await run_in_threadpool(self._record_failure, role, variables, error, started, resolved_course)
            raise
        else:
            call_id = await run_in_threadpool(
                llm_calls.record,
                role=str(role),
                provider=result.provider,
                model=result.model,
                prompt_id=result.prompt_id,
                prompt_version=result.prompt_version,
                prompt_sha256=result.prompt_sha256,
                request_fingerprint=result.request_fingerprint,
                status="ok",
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost_usd,
                latency_ms=result.usage.latency_ms or self._elapsed_ms(started),
                course_id=resolved_course,
            )
            # Hand the ledger id back on the result rather than stashing it on
            # `self`. This client is shared across concurrent awaits (one
            # instance serves a whole ingest), so a "last id" attribute would
            # hand caller A the id of caller B's call -- and the one column that
            # would consume it, `attempts.grade_llm_call_id`, exists to make
            # grade-to-cost joins trustworthy.
            return replace(result, llm_call_id=call_id)

    # @spec LLM-LEDGER-002, LLM-LEDGER-003, LLM-PROV-005
    async def stream_text(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Stream prose, writing exactly one ledger row however the stream ends.

        The budget is enforced before the first token, not after the last: a
        course at its ceiling must not spend anything at all.

        The ledger write lives in a `finally:` because the interesting endings
        are the abnormal ones. A barge-in cancels this generator mid-flight and
        still burned tokens; recording that as `ok` would make "how often does
        the learner talk over the coach?" unanswerable. Callers must wrap the
        iterator in `contextlib.aclosing` so an abandoned generator still runs
        its cleanup.
        """
        started = time.monotonic()
        resolved_course = self._resolve_course(course_id)
        await run_in_threadpool(self._enforce_budget, role, variables, resolved_course)

        inner = getattr(self._inner, "stream_text", None)
        if inner is None:
            raise ProviderError(f"{self._provider_for(role)} cannot stream.")

        model = self._inner.model_for(role)
        chunks: list[str] = []
        status = "ok"
        error: BaseException | None = None
        try:
            async for delta in inner(role, variables, course_id=course_id):
                chunks.append(delta.text)
                yield delta
        except GeneratorExit:
            # The consumer stopped iterating -- barge-in, or the take finished.
            status = "cancelled"
            raise
        except BaseException as caught:
            status = status_for_error(caught)
            error = caught
            raise
        finally:
            await run_in_threadpool(
                self._record_stream,
                role,
                variables,
                model,
                "".join(chunks),
                status,
                error,
                started,
                resolved_course,
            )

    def _record_stream(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        model: str,
        text: str,
        status: str,
        error: BaseException | None,
        started: float,
        course_id: uuid.UUID | None,
    ) -> None:
        try:
            call = prepare(role, variables, model)
            prompt_id = call.config.prompt_id
            prompt_version = call.config.prompt_version
            prompt_sha256 = call.prompt_sha256
            fingerprint = call.request_fingerprint
            input_tokens = max(1, len(call.prompt_text) // CHARS_PER_TOKEN)
        except Exception:  # noqa: BLE001 - a prompt that will not render still deserves a row
            prompt_id = prompt_version = prompt_sha256 = fingerprint = "unknown"
            input_tokens = 0

        output_tokens = max(0, len(text) // CHARS_PER_TOKEN)
        llm_calls.record(
            role=str(role),
            provider=self._provider_for(role),
            model=model,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            request_fingerprint=fingerprint,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=price_for(model, input_tokens, output_tokens),
            latency_ms=self._elapsed_ms(started),
            error=None if error is None else f"{type(error).__name__}: {error}",
            course_id=course_id,
        )

    def _provider_for(self, role: LLMRole) -> str:
        """What actually served this role.

        Not `self._inner.provider`: with lanes routed to different providers, the
        client as a whole has no single one, and a ledger row naming the wrong
        vendor makes the cost record fiction.
        """
        resolve = getattr(self._inner, "provider_for", None)
        return resolve(role) if resolve is not None else self._inner.provider

    # ── internals ─────────────────────────────────────────────────────────

    def _enforce_budget(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        course_id: uuid.UUID | None,
    ) -> None:
        if course_id is None:
            return
        model = self._inner.model_for(role)
        try:
            prepared = prepare(role, variables, model)
        except Exception:
            # Prompt rendering is part of the provider call's failure surface.
            # There is no honest preflight estimate when a caller supplied an
            # incomplete variable set, so let the provider seam run and let the
            # normal failure recorder persist an `unknown` prompt row.
            return
        estimated_input = max(1, (len(prepared.prompt_text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)
        # Providers may spend a second max-sized turn repairing invalid JSON;
        # reserve for both so a schema repair cannot push a course over its cap.
        estimated_cost = price_for(model, estimated_input, prepared.config.max_tokens * 2)
        llm_calls.assert_budget(
            course_id=course_id,
            estimated_cost_usd=estimated_cost,
            budget_usd=get_settings().course_llm_budget_usd,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    def _resolve_course(self, course_id: str | None) -> uuid.UUID | None:
        if course_id is None:
            return self._course_id
        try:
            return uuid.UUID(str(course_id))
        except (ValueError, AttributeError):
            return self._course_id

    def _record_failure(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        error: BaseException,
        started: float,
        course_id: uuid.UUID | None,
    ) -> None:
        model = self._inner.model_for(role)
        try:
            call = prepare(role, variables, model)
            prompt_id = call.config.prompt_id
            prompt_version = call.config.prompt_version
            prompt_sha256 = call.prompt_sha256
            fingerprint = call.request_fingerprint
        except Exception:  # noqa: BLE001 - a prompt that will not even render still deserves a row
            prompt_id = prompt_version = prompt_sha256 = fingerprint = "unknown"

        llm_calls.record(
            role=str(role),
            provider=self._provider_for(role),
            model=model,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            request_fingerprint=fingerprint,
            status=status_for_error(error),
            latency_ms=self._elapsed_ms(started),
            error=f"{type(error).__name__}: {error}",
            course_id=course_id,
        )


def recording_llm_client(course_id: uuid.UUID | None = None) -> LLMClient:
    """The client every service should use. Never call `get_llm_client` directly."""
    return RecordingLLMClient(get_llm_client(), course_id=course_id)


# ── embeddings ────────────────────────────────────────────────────────────
#
# Embedding is the other thing the app spends money on, and it was outside the
# ledger entirely: `app/ingestion/embed.py` calls the provider directly, so
# `text-embedding-3-small` sat priced in `registry.py` and never charged. On a
# real-key ingest of a 400-page book that is thousands of API calls' worth of
# tokens missing from `GET /courses/{id}/cost` -- the endpoint understated the
# very thing it exists to report, and a reindex with `scope=vectors` is a
# rebuild whose entire cost is embeddings.
#
# The recording lives HERE rather than in `ingestion/embed.py` for the same
# reason `RecordingLLMClient` does: `app/ingestion/` and `app/llm/` must not
# import repositories. `services/` is the layer allowed to touch both.

EMBED_ROLE = "embedding"

# Embeddings have no prompt. The ledger's prompt columns are NOT NULL because
# for an LLM role they are the whole point, so a sentinel is recorded rather
# than a lie -- `prompt_id = "embedding"` reads correctly in a `GROUP BY role`
# and cannot be mistaken for a real versioned prompt file.
EMBED_PROMPT_ID = "embedding"
EMBED_PROMPT_VERSION = "n/a"
EMBED_PROMPT_SHA = "-" * 64

# Embedding providers return vectors, not token counts, and the Protocol in
# `llm/base.py` is deliberately that narrow. Four characters per token is the
# same approximation `FakeLLMClient` already uses for its own usage numbers.
# It is an ESTIMATE and is documented as one; the alternative is widening the
# EmbeddingProvider protocol for every provider to satisfy bookkeeping.


def _embedding_identity() -> tuple[str, str]:
    settings = get_settings()
    provider = settings.embedding_provider.lower()
    # The fake provider calls nothing and costs nothing; recording the configured
    # OpenAI model name against it would put fictional spend in the ledger.
    model = "fake" if provider == "fake" else settings.embedding_model
    return provider, model


# @spec LLM-EMBED-003
def embed_texts_recorded(texts: Sequence[str], *, course_id: uuid.UUID | None = None) -> list[list[float]]:
    """`embed_texts`, with the spend written to the ledger.

    Synchronous: every caller is either a Celery stage or already inside a
    threadpool, and `embed_texts` itself blocks. Failures are recorded and then
    re-raised -- unlike an LLM window, a failed embedding batch means the index
    is incomplete, and the caller decides what that is worth.
    """
    if not texts:
        return []

    provider, model = _embedding_identity()
    input_chars = sum(len(text) for text in texts)
    input_tokens = max(1, (input_chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)
    fingerprint = f"embed:{model}:{len(texts)}:{input_tokens}"
    started = time.monotonic()
    estimated_cost = price_for(model, input_tokens, 0)
    if course_id is not None:
        llm_calls.assert_budget(
            course_id=course_id,
            estimated_cost_usd=estimated_cost,
            budget_usd=get_settings().course_llm_budget_usd,
        )

    try:
        vectors = embed_texts(texts)
    except BaseException as error:
        llm_calls.record(
            role=EMBED_ROLE,
            provider=provider,
            model=model,
            prompt_id=EMBED_PROMPT_ID,
            prompt_version=EMBED_PROMPT_VERSION,
            prompt_sha256=EMBED_PROMPT_SHA,
            request_fingerprint=fingerprint,
            status=status_for_error(error),
            input_tokens=input_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"{type(error).__name__}: {error}",
            course_id=course_id,
        )
        raise

    llm_calls.record(
        role=EMBED_ROLE,
        provider=provider,
        model=model,
        prompt_id=EMBED_PROMPT_ID,
        prompt_version=EMBED_PROMPT_VERSION,
        prompt_sha256=EMBED_PROMPT_SHA,
        request_fingerprint=fingerprint,
        status="ok",
        input_tokens=input_tokens,
        # Embeddings produce no output tokens, and the price table already
        # carries 0 for the output rate -- so the cost is honest, not rounded.
        output_tokens=0,
        cost_usd=price_for(model, input_tokens, 0),
        latency_ms=int((time.monotonic() - started) * 1000),
        course_id=course_id,
    )
    return vectors

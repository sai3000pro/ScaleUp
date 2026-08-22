"""Anthropic-backed LLMClient.

Structured output is enforced with `output_config.format` (JSON schema), not by
asking the model nicely for JSON. On a schema failure we allow exactly ONE repair
turn, feeding the validator's own error back verbatim; a third attempt almost
never helps and the cost is linear.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic, RateLimitError

from app.config import get_settings
from app.llm.base import (
    LLMRole,
    ProviderError,
    RefusalError,
    SchemaValidationError,
    StructuredResult,
    Usage,
)
from app.llm.registry import ROLES, price_for
from app.llm.support import parse_json_or_raise, prepare, validate_or_raise


class AnthropicLLMClient:
    """Implements app.llm.base.LLMClient."""

    provider = "anthropic"

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    def model_for(self, role: LLMRole) -> str:
        return ROLES[role].anthropic_model

    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        model = ROLES[role].anthropic_model
        call = prepare(role, variables, model)

        started = time.monotonic()
        message = await self._request(call.prompt_text, call, model)
        attempt_text = _first_text(message)

        # Accumulated across turns, not read off the last response. A repair
        # turn means the model was called TWICE and both calls were billed;
        # reading usage off `message` after reassignment silently discarded the
        # first. That made the ledger undercount exactly the case it exists to
        # make visible -- see app/models/llm_call.py, "a schema error still
        # burned output tokens".
        usage_in = getattr(message.usage, "input_tokens", 0)
        usage_out = getattr(message.usage, "output_tokens", 0)

        try:
            data = validate_or_raise(parse_json_or_raise(attempt_text), call.schema)
        except SchemaValidationError as first_error:
            repair = (
                f"{call.prompt_text}\n\n---\n\nYour previous response did not satisfy the schema.\n"
                f"Validator error: {first_error}\n\nReturn corrected JSON only."
            )
            message = await self._request(repair, call, model)
            attempt_text = _first_text(message)
            usage_in += getattr(message.usage, "input_tokens", 0)
            usage_out += getattr(message.usage, "output_tokens", 0)
            data = validate_or_raise(parse_json_or_raise(attempt_text), call.schema)

        return StructuredResult(
            data=data,
            raw_text=attempt_text,
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

    async def _request(self, prompt_text: str, call, model: str):
        try:
            message = await self._client.messages.create(
                model=model,
                max_tokens=call.config.max_tokens,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": call.config.effort,
                    "format": {"type": "json_schema", "schema": call.schema},
                },
                messages=[{"role": "user", "content": prompt_text}],
            )
        except (RateLimitError, APIConnectionError) as exc:
            # Transient. The Celery task's autoretry_for handles the backoff.
            raise ProviderError(f"anthropic transient failure: {exc}") from exc
        except APIStatusError as exc:
            raise ProviderError(f"anthropic error {exc.status_code}: {exc}") from exc

        # A refusal is a successful HTTP response with an empty content list --
        # code that indexes content[0] unconditionally breaks here.
        if message.stop_reason == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            raise RefusalError(f"model declined the request (category={category})")

        return message


def _first_text(message) -> str:
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise SchemaValidationError("response contained no text block")

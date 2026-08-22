"""OpenAI-backed LLMClient and EmbeddingProvider.

The embedding half matters even when Claude serves the LLM roles: Anthropic has
no embeddings endpoint, so a real retrieval pipeline always needs a second
vendor here (OpenAI or Voyage).
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError

from app.config import get_settings
from app.llm.base import LLMRole, ProviderError, SchemaValidationError, StructuredResult, Usage
from app.llm.registry import ROLES, price_for
from app.llm.support import parse_json_or_raise, prepare, validate_or_raise


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode requires `required` to list every property.

    Optional fields are expressed by allowing null rather than by omission, so
    the shared schema (which uses a smaller `required`) has to be adapted here
    rather than weakened for everyone.
    """
    adapted = dict(schema)
    if adapted.get("type") == "object" and "properties" in adapted:
        adapted["required"] = sorted(adapted["properties"].keys())
        adapted["additionalProperties"] = False
        adapted["properties"] = {
            key: _strict_schema(value) if isinstance(value, dict) else value
            for key, value in adapted["properties"].items()
        }
    if adapted.get("type") == "array" and isinstance(adapted.get("items"), dict):
        adapted["items"] = _strict_schema(adapted["items"])
    return adapted


class OpenAILLMClient:
    """Implements app.llm.base.LLMClient."""

    provider = "openai"

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=get_settings().openai_api_key)

    def model_for(self, role: LLMRole) -> str:
        return ROLES[role].openai_model

    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        model = ROLES[role].openai_model
        call = prepare(role, variables, model)
        started = time.monotonic()

        response = await self._request(call.prompt_text, call, model)
        text = response.choices[0].message.content or ""

        # Accumulated across turns -- a repair turn is a second billed call, and
        # reading usage off `response` after reassignment discarded the first.
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
            response = await self._request(repair, call, model)
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

    async def _request(self, prompt_text: str, call, model: str):
        try:
            return await self._client.chat.completions.create(
                model=model,
                max_tokens=call.config.max_tokens,
                messages=[{"role": "user", "content": prompt_text}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": f"{call.config.schema_id}_{call.config.schema_version}",
                        "strict": True,
                        "schema": _strict_schema(call.schema),
                    },
                },
            )
        except (RateLimitError, APIConnectionError) as exc:
            raise ProviderError(f"openai transient failure: {exc}") from exc
        except APIStatusError as exc:
            raise ProviderError(f"openai error {exc.status_code}: {exc}") from exc


class OpenAIEmbeddingProvider:
    """Implements app.llm.base.EmbeddingProvider."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=list(texts),
                dimensions=self.dimensions,
            )
        except (RateLimitError, APIConnectionError) as exc:
            raise ProviderError(f"openai embeddings transient failure: {exc}") from exc
        except APIStatusError as exc:
            raise ProviderError(f"openai embeddings error {exc.status_code}: {exc}") from exc

        # The API may return results out of order; `index` is authoritative.
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]

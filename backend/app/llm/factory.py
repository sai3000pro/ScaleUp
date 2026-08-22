"""Provider selection.

The only place that reads LLM_PROVIDER / EMBEDDING_PROVIDER. Everything else
depends on the Protocols in base.py.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import EmbeddingProvider, LLMClient
from app.llm.fake_provider import FakeEmbeddingProvider, FakeLLMClient

#: Every provider `get_llm_client` implements. Declared here because the factory
#: is the only place that reads LLM_PROVIDER, so it is the only place that can
#: answer what is selectable without going out of date.
LLM_PROVIDERS: tuple[str, ...] = ("fake", "anthropic", "openai", "gemini")


@lru_cache(maxsize=1)
# @spec LLM-FAKE-001, LLM-FAKE-002, LLM-PROV-001, LLM-PROV-002
def get_llm_client() -> LLMClient:
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "fake":
        return FakeLLMClient()

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty. Set it, or use LLM_PROVIDER=fake.")
        from app.llm.anthropic_provider import AnthropicLLMClient

        return AnthropicLLMClient()

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is empty. Set it, or use LLM_PROVIDER=fake.")
        from app.llm.openai_provider import OpenAILLMClient

        return OpenAILLMClient()

    if provider == "gemini":
        from app.llm.gemini_provider import GeminiLLMClient
        from app.llm.lane_router import LaneRoutedLLMClient
        from app.llm.registry import LANES

        served = [lane for lane in LANES if settings.gemini_key_for(lane)]
        if not served:
            raise RuntimeError(
                "LLM_PROVIDER=gemini but no Gemini credential is set. Set GEMINI_API_KEY to serve every "
                "workload lane, or GEMINI_API_KEY_INGEST / _TUTOR / _LIVE to serve one, or use "
                "LLM_PROVIDER=fake."
            )
        if len(served) == len(LANES):
            return GeminiLLMClient()

        # Some lanes are paid for and some are not. The unpaid ones run on the
        # deterministic floor rather than refusing, so turning one lane on is
        # turning one lane on.
        gemini = GeminiLLMClient()
        return LaneRoutedLLMClient({lane: gemini for lane in served}, FakeLLMClient())

    raise RuntimeError(
        f"unknown LLM_PROVIDER {settings.llm_provider!r}; expected {' | '.join(LLM_PROVIDERS)}"
    )


@lru_cache(maxsize=1)
# @spec LLM-EMBED-001
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    provider = settings.embedding_provider.lower()

    if provider == "fake":
        return FakeEmbeddingProvider(dimensions=settings.embedding_dimensions)

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is empty. "
                "Anthropic has no embeddings endpoint, so real embeddings need OpenAI (or Voyage)."
            )
        from app.llm.openai_provider import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider()

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is empty. Embeddings are not a workload lane, "
                "so they read the shared key."
            )
        from app.llm.gemini_provider import GeminiEmbeddingProvider

        return GeminiEmbeddingProvider()

    raise RuntimeError(
        f"unknown EMBEDDING_PROVIDER {settings.embedding_provider!r}; expected fake | openai | gemini"
    )

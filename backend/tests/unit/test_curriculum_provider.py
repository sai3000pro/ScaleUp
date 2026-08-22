from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.research.providers import ExaResearchProvider, FakeResearchProvider, ResearchProviderError, _clean_result


@pytest.mark.asyncio
async def test_fake_research_provider_is_bounded_and_deterministic() -> None:
    provider = FakeResearchProvider()

    first = await provider.search("linear algebra", 2)
    second = await provider.search("linear algebra", 2)

    assert first == second
    assert len(first) == 2
    assert all(result.url.startswith("https://") for result in first)
    assert all(result.domain for result in first)


def test_search_result_normalization_rejects_unsafe_urls_and_drops_fragments() -> None:
    assert _clean_result({"title": "private", "url": "http://127.0.0.1/admin"}) is None
    assert _clean_result({"title": "credentials", "url": "https://user:pass@example.com/page"}) is None

    result = _clean_result(
        {
            "title": "Vectors",
            "url": "https://example.com/vectors#definition",
            "highlights": ["A vector has magnitude.", "It also has direction."],
            "publishedDate": "2026-08-01",
        }
    )
    assert result is not None
    assert result.url == "https://example.com/vectors"
    assert result.snippet == "A vector has magnitude. It also has direction."
    assert result.published_at == "2026-08-01"


@pytest.mark.asyncio
async def test_exa_provider_fails_clearly_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.research.providers.get_settings",
        lambda: SimpleNamespace(exa_api_key="", research_timeout_seconds=1),
    )

    with pytest.raises(ResearchProviderError, match="EXA_API_KEY"):
        await ExaResearchProvider().search("vectors", 3)

"""Provider seam for bounded curriculum research.

The planner asks for a small set of candidate URLs and never crawls from one
result to another. The default fake keeps local development and tests free of
network calls; Exa is opt-in through ``RESEARCH_PROVIDER=exa`` and
``EXA_API_KEY``.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

import httpx

from app.config import get_settings


class ResearchProviderError(RuntimeError):
    """The configured search provider could not return a proposal."""


@dataclass(frozen=True, slots=True)
class ResearchResult:
    title: str
    url: str
    snippet: str
    published_at: str | None
    domain: str


class ResearchProvider(Protocol):
    async def search(self, goal: str, limit: int) -> list[ResearchResult]:
        """Return at most ``limit`` reviewable web sources for a goal."""
        ...


def _canonical_http_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return None
    try:
        literal_host = ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        literal_host = None
    if literal_host is not None and not literal_host.is_global:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0]


def _clean_result(raw: dict[str, Any]) -> ResearchResult | None:
    url = _canonical_http_url(raw.get("url"))
    if url is None:
        return None

    highlights = raw.get("highlights")
    if isinstance(highlights, list):
        snippet = " ".join(str(item).strip() for item in highlights if str(item).strip())
    else:
        snippet = str(raw.get("snippet") or raw.get("text") or "").strip()

    title = str(raw.get("title") or _domain(url)).strip()[:300]
    return ResearchResult(
        title=title or _domain(url),
        url=url,
        snippet=snippet[:1000],
        published_at=str(raw["publishedDate"]) if raw.get("publishedDate") else None,
        domain=_domain(url),
    )


class FakeResearchProvider:
    """Deterministic candidates that make the planner usable without a key."""

    async def search(self, goal: str, limit: int) -> list[ResearchResult]:
        display_goal = goal.split(" for a ", 1)[0].strip()
        slug = "-".join(display_goal.lower().split())[:80].strip("-") or "learning-goal"
        candidates = [
            ResearchResult(
                title=f"A beginner's guide to {display_goal}",
                url=f"https://example.com/learn/{slug}",
                snippet=f"A structured introduction to {display_goal}, including terminology and first principles.",
                published_at=None,
                domain="example.com",
            ),
            ResearchResult(
                title=f"{display_goal} fundamentals and practice",
                url=f"https://learning.example.org/fundamentals/{slug}",
                snippet=f"Explanations and worked examples for building a foundation in {display_goal}.",
                published_at=None,
                domain="learning.example.org",
            ),
            ResearchResult(
                title=f"Reference notes: {display_goal}",
                url=f"https://docs.example.edu/reference/{slug}",
                snippet=f"Reference material and key concepts to review while learning {display_goal}.",
                published_at=None,
                domain="docs.example.edu",
            ),
        ]
        return candidates[:limit]


class ExaResearchProvider:
    """Small HTTP adapter for Exa's search endpoint.

    Using the existing ``httpx`` dependency keeps the provider isolated from an
    SDK and makes the request shape visible in tests. Contents are limited to
    highlights because the learner has not approved ingestion yet.
    """

    endpoint = "https://api.exa.ai/search"

    async def search(self, goal: str, limit: int) -> list[ResearchResult]:
        settings = get_settings()
        if not settings.exa_api_key:
            raise ResearchProviderError("RESEARCH_PROVIDER=exa requires EXA_API_KEY.")

        payload = {
            "query": goal,
            "type": "auto",
            "numResults": limit,
            "contents": {"highlights": {"maxCharacters": 1000}},
        }
        headers = {"Authorization": f"Bearer {settings.exa_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=settings.research_timeout_seconds) as client:
                response = await client.post(self.endpoint, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ResearchProviderError(f"Web search failed: {exc}") from exc

        body = response.json()
        raw_results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(raw_results, list):
            raise ResearchProviderError("Web search returned an invalid result shape.")

        results: list[ResearchResult] = []
        seen_urls: set[str] = set()
        for raw in raw_results:
            if isinstance(raw, dict):
                result = _clean_result(raw)
                if result is not None and result.url not in seen_urls:
                    seen_urls.add(result.url)
                    results.append(result)
        return results[:limit]


# @spec CURR-SOURCE-007
def get_research_provider() -> ResearchProvider:
    provider = get_settings().research_provider.lower()
    if provider == "fake":
        return FakeResearchProvider()
    if provider == "exa":
        return ExaResearchProvider()
    raise ResearchProviderError(f"Unknown research provider: {provider}.")

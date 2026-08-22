"""Transparent ranking for proposed curriculum sources.

This is intentionally a heuristic, not a hidden model judgement. Every score is
returned with the reasons that contributed to it so the learner can override it
before approval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.research.providers import ResearchResult

_STOPWORDS = frozenset("a an and for from how in into of on or the to what with".split())
_FORMAT_TERMS = {
    "mixed": ("guide", "tutorial", "reference", "course", "book"),
    "textbook": ("book", "textbook", "chapter", "lecture"),
    "course": ("course", "tutorial", "lesson", "lecture"),
    "papers": ("paper", "research", "journal", "publication"),
}
_LEVEL_TERMS = {
    "beginner": ("beginner", "introduction", "fundamentals", "basics"),
    "intermediate": ("intermediate", "practice", "applied", "implementation"),
    "advanced": ("advanced", "research", "theory", "deep dive"),
}


@dataclass(frozen=True, slots=True)
class RankedResearchResult:
    result: ResearchResult
    score: float
    reasons: list[str]


def _terms(text: str) -> set[str]:
    return {
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z-]{2,}", text)
        if word.lower() not in _STOPWORDS
    }


def _is_education_domain(domain: str) -> bool:
    lowered = domain.lower()
    return lowered.endswith(".edu") or ".ac." in lowered


def select_diverse_sources(ranked: list[RankedResearchResult], limit: int) -> list[RankedResearchResult]:
    """Keep high-ranked sources while ensuring early slots cover domains.

    This is still a proposal, not an autonomous crawler: only the provider's
    returned URLs are considered. Diversity prevents one host from occupying the
    whole campaign evidence set when several useful domains were discovered.
    """
    selected: list[RankedResearchResult] = []
    domains: set[str] = set()
    for item in ranked:
        if len(selected) < limit and item.result.domain not in domains:
            item.reasons.append("adds a distinct source domain")
            selected.append(item)
            domains.add(item.result.domain)

    for item in ranked:
        if len(selected) >= limit:
            pass
        elif item not in selected:
            selected.append(item)

    return selected[:limit]


def rank_sources(
    goal: str,
    level: str,
    format_preference: str,
    results: list[ResearchResult],
    *,
    prior_knowledge: str = "",
    application_context: str = "",
) -> list[RankedResearchResult]:
    goal_terms = _terms(goal)
    context_terms = _terms(f"{prior_knowledge} {application_context}")
    preferred_terms = set(_FORMAT_TERMS.get(format_preference, _FORMAT_TERMS["mixed"]))
    preferred_terms.update(_LEVEL_TERMS.get(level, _LEVEL_TERMS["beginner"]))
    ranked: list[RankedResearchResult] = []

    for result in results:
        searchable = f"{result.title} {result.snippet}".lower()
        score = 0.35
        reasons: list[str] = []
        domain = result.domain.lower()

        if result.url.startswith("https://"):
            score += 0.05
            reasons.append("secure HTTPS source")
        if _is_education_domain(domain):
            score += 0.2
            reasons.append("education domain")
        elif domain.endswith(".org"):
            score += 0.1
            reasons.append("organisation domain")
        if "example." in domain:
            score -= 0.2
            reasons.append("placeholder domain — verify manually")

        overlap = len(goal_terms & _terms(searchable))
        if overlap > 0:
            score += min(0.2, overlap * 0.07)
            reasons.append(f"matches {overlap} goal term" + ("s" if overlap != 1 else ""))
        context_overlap = len(context_terms & _terms(searchable))
        if context_overlap > 0:
            score += min(0.1, context_overlap * 0.04)
            reasons.append(
                f"matches {context_overlap} learner-context term" + ("s" if context_overlap != 1 else "")
            )
        if len(result.snippet) >= 120:
            score += 0.08
            reasons.append("has a useful excerpt")
        if any(term in searchable for term in preferred_terms):
            score += 0.1
            reasons.append(f"fits {level} / {format_preference} preference")
        if result.published_at:
            score += 0.02
            reasons.append("has publication metadata")

        ranked.append(
            RankedResearchResult(
                result=result,
                score=round(max(0.0, min(1.0, score)), 3),
                reasons=reasons or ["general relevance signal"],
            )
        )

    return sorted(ranked, key=lambda item: (-item.score, item.result.domain, item.result.url))

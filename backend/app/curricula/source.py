"""Deterministic source-to-candidate extraction for offline curriculum builds.

This is deliberately small and transparent. Production LLM extraction can feed
its ``ConceptSpec``/``CandidateEdge`` results into the same persistence lifecycle;
this parser gives tests and local demos a zero-provider path with inspectable
source evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Mapping

from app.domain.dag import CandidateEdge
from app.services.graph_service import ConceptSpec

_PREREQUISITES = re.compile(r"(?:requires?|prerequisites?)\s*:\s*([^.;\n]+)", re.IGNORECASE)
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SourceSection:
    slug: str
    title: str
    summary: str
    text: str
    difficulty: int = 3
    assessable: bool = True
    key_terms: tuple[str, ...] = ()
    section: str | None = None


@dataclass(frozen=True, slots=True)
class SourceCandidateBundle:
    concepts: tuple[ConceptSpec, ...]
    edges: tuple[CandidateEdge, ...]
    evidence_quotes: dict[tuple[str, str], str]


def load_source_sections(name: str) -> tuple[str, str, str, list[SourceSection]]:
    """Load a generic source bundle by data name, not by instrument module."""
    if not _SLUG.fullmatch(name):
        raise ValueError("Source bundle name must be slug-like.")
    try:
        resource = resources.files("app.curricula").joinpath(f"{name}.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(f"Source bundle was not found or is invalid: {name!r}.") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Source bundle must be a JSON object.")
    instrument = payload.get("instrument")
    slug = payload.get("slug")
    title = payload.get("title")
    raw_sections = payload.get("sections")
    if not all(isinstance(value, str) and value.strip() for value in (instrument, slug, title)):
        raise ValueError("Source bundle metadata is incomplete.")
    if not isinstance(raw_sections, list):
        raise ValueError("Source bundle sections must be a list.")
    sections: list[SourceSection] = []
    for raw in raw_sections:
        if not isinstance(raw, Mapping):
            raise ValueError("Every source section must be an object.")
        values = {key: raw.get(key) for key in ("slug", "title", "summary", "text")}
        if not all(isinstance(value, str) and value.strip() for value in values.values()):
            raise ValueError("Every source section requires slug, title, summary, and text.")
        difficulty = raw.get("difficulty", 3)
        terms = raw.get("key_terms", [])
        if not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
            raise ValueError("Source section difficulty must be between 1 and 5.")
        if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
            raise ValueError("Source section key_terms must be strings.")
        sections.append(
            SourceSection(
                slug=values["slug"],
                title=values["title"],
                summary=values["summary"],
                text=values["text"],
                difficulty=difficulty,
                key_terms=tuple(terms),
                section=raw.get("section") if isinstance(raw.get("section"), str) else None,
            )
        )
    return instrument, slug, title, sections


def compile_source_sections(sections: list[SourceSection]) -> SourceCandidateBundle:
    """Extract a closed-vocabulary DAG proposal from source sections.

    A source section may contain a line such as ``Prerequisites: bow-hold``.
    Only named sections in the same bundle can become edges; every accepted
    candidate carries the exact directive line as evidence for later review.
    """
    if not sections:
        raise ValueError("A source bundle must contain at least one section.")

    slugs = {section.slug for section in sections}
    if len(slugs) != len(sections):
        raise ValueError("Source sections must have unique slugs.")
    if any(not _SLUG.fullmatch(section.slug) for section in sections):
        raise ValueError("Source section slugs must be lowercase slug-like values.")

    concepts = tuple(
        ConceptSpec(
            slug=section.slug,
            title=section.title,
            summary=section.summary,
            difficulty=section.difficulty,
            assessable=section.assessable,
            key_terms=section.key_terms,
            section=section.section,
        )
        for section in sections
    )
    edges: list[CandidateEdge] = []
    evidence_quotes: dict[tuple[str, str], str] = {}

    for section in sections:
        for match in _PREREQUISITES.finditer(section.text):
            directive = match.group(0).strip()
            names = [name.strip().lower() for name in match.group(1).split(",")]
            for prereq in names:
                if prereq in slugs and prereq != section.slug:
                    pair = (prereq, section.slug)
                    if pair not in evidence_quotes:
                        edges.append(
                            CandidateEdge(
                                prereq=prereq,
                                target=section.slug,
                                confidence=0.9,
                                support=1,
                                rationale=directive,
                            )
                        )
                        evidence_quotes[pair] = directive

    return SourceCandidateBundle(concepts=concepts, edges=tuple(edges), evidence_quotes=evidence_quotes)

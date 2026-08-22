"""Turn a learner's stated goal into a curriculum definition.

Pure: goal text in, a `CurriculumDefinition` out. No session, no provider, no
clock. The service layer decides whether to ask a model; everything here is the
part that must be true either way.

Two jobs live here.

**The deterministic floor.** Every goal that names an instrument resolves to a
playable tree with no provider configured. Where the instrument has a curriculum
this project ships, that curriculum *is* the answer -- it was authored and
reviewed, and a model has nothing to add to it. Where it does not, the shared
catalogue supplies the spine: reading, pulse, orientation and phrasing are the
same skills on a cello as on a guitar, and the catalogue's own suggested ordering
puts them in a sensible order.

**Validating a proposal.** A model's plan is checked against the catalogue before
anything is written, and a plan that fails is refused whole rather than repaired.
A repaired plan is a tree nobody authored and nobody proposed.

Acyclicity is deliberately not checked here. Every construction path in this
segment feeds its candidate edges to `app.domain.dag.build_acyclic_edges`, which
admits them in descending confidence and records any that would close a cycle as
rejected with a reason. A proposed edge that closes a cycle is dropped there,
exactly as a compiled one is.
"""

from __future__ import annotations

import json
import re
from typing import Mapping, Sequence

from app.curricula.loader import (
    OVERRIDABLE_FIELDS,
    CatalogueSkill,
    CurriculumConcept,
    CurriculumDefinition,
    CurriculumDefinitionError,
    load_catalogue,
    load_catalogue_edges,
    load_curriculum,
)
from app.domain.dag import CandidateEdge

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: A tree below this is not a curriculum; above it is a syllabus nobody finishes.
MIN_CONCEPTS = 4
MAX_CONCEPTS = 24

#: Instruments this project ships a reviewed curriculum for. Assembly for one of
#: these is a lookup, not a generation.
SHIPPED = ("piano", "guitar", "violin", "trumpet", "drums", "banjo")

#: What a learner may call an instrument, mapped to what the curriculum is filed
#: under. Only genuine synonyms belong here -- a "fiddle" is a violin, but a
#: "bass guitar" is not a guitar and gets its own tree.
ALIASES: dict[str, str] = {
    "fiddle": "violin",
    "keys": "piano",
    "keyboard": "piano",
    "drum kit": "drums",
    "drumkit": "drums",
    "drum set": "drums",
    "percussion": "drums",
    "six string": "guitar",
    "six-string": "guitar",
    "acoustic guitar": "guitar",
    "electric guitar": "guitar",
    "classical guitar": "guitar",
    "upright piano": "piano",
    "grand piano": "piano",
}

#: Instruments the floor can name without a provider. The model may return one
#: outside this list; this is what keyword resolution can reach on its own.
VOCABULARY = (
    *SHIPPED,
    "cello", "viola", "double bass", "harp", "mandolin", "ukulele", "banjo",
    "saxophone", "clarinet", "flute", "oboe", "bassoon", "recorder", "piccolo",
    "trombone", "tuba", "french horn", "euphonium", "harmonica", "accordion",
    "organ", "synthesizer", "bass guitar", "sitar", "erhu", "koto", "guzheng",
    "tabla", "djembe", "cajon", "marimba", "vibraphone", "xylophone", "timpani",
    "bagpipes", "melodica", "kalimba", "lute", "oud", "balalaika", "charango",
)


class PlanValidationError(ValueError):
    """A proposed plan cannot be trusted, so it is refused rather than repaired."""


def known_instruments() -> frozenset[str]:
    """The instruments assembly can answer without asking anything."""
    return frozenset(SHIPPED)


def _normalise(goal: str) -> str:
    return re.sub(r"[^a-z0-9\s-]+", " ", goal.lower())


# @spec CURR-GOAL-003, CURR-GOAL-005
def resolve_instrument(goal: str) -> str | None:
    """Read the instrument out of a learner's sentence, or admit it is not there.

    Longest match wins, so "bass guitar" is not read as "guitar" and "french
    horn" is not read as "horn". Aliases resolve to the name the curriculum is
    filed under. A goal naming nothing playable returns None rather than a guess.
    """
    text = f" {_normalise(goal)} "
    candidates = sorted({*VOCABULARY, *ALIASES}, key=len, reverse=True)
    for name in candidates:
        if f" {name} " in text or f" {name}s " in text:
            return ALIASES.get(name, name)
    return None


def _title_for(instrument: str) -> str:
    return " ".join(word.capitalize() for word in instrument.split())


def _spine(instrument: str) -> CurriculumDefinition:
    """The shared catalogue as a tree, for an instrument nothing else covers."""
    catalogue = load_catalogue()
    concepts = tuple(
        CurriculumConcept(
            slug=f"{instrument.replace(' ', '-')}-{skill_id}",
            title=skill.title,
            summary=skill.summary,
            difficulty=skill.difficulty,
            key_terms=skill.key_terms,
            catalogue_id=skill_id,
        )
        for skill_id, skill in catalogue.items()
    )
    by_catalogue_id = {concept.catalogue_id: concept.slug for concept in concepts}
    edges = tuple(
        CandidateEdge(
            prereq=by_catalogue_id[edge.prereq],
            target=by_catalogue_id[edge.target],
            confidence=edge.confidence,
            rationale=edge.rationale,
        )
        for edge in load_catalogue_edges()
    )
    return CurriculumDefinition(
        instrument=instrument,
        slug=instrument.replace(" ", "-"),
        version=1,
        title=_title_for(instrument),
        concepts=concepts,
        edges=edges,
    )


# @spec CURR-GOAL-004, CURR-GOAL-006
def assemble(instrument: str) -> CurriculumDefinition:
    """The deterministic answer for an instrument, with no provider involved."""
    if instrument in known_instruments():
        return load_curriculum(instrument)
    return _spine(instrument)


# @spec CURR-GOAL-002
def catalogue_prompt_payload() -> str:
    """The whole catalogue, rendered for a planner to select from.

    Handing over the entire vocabulary is what makes a plan a *selection* rather
    than an invention: two instruments that both need a steady pulse come back
    naming the same catalogue id, so they end up sharing a skill entity rather
    than two similarly-worded copies of one.
    """
    catalogue = load_catalogue()
    skills = [
        {
            "id": skill_id,
            "title": skill.title,
            "summary": skill.summary,
            "difficulty": skill.difficulty,
            "key_terms": list(skill.key_terms),
        }
        for skill_id, skill in catalogue.items()
    ]
    suggested = [
        {"prereq": edge.prereq, "target": edge.target, "rationale": edge.rationale}
        for edge in load_catalogue_edges()
    ]
    return json.dumps({"skills": skills, "suggested_order": suggested}, indent=2)


def _concept_from_plan(raw: Mapping[str, object], index: int, catalogue: Mapping[str, CatalogueSkill]) -> CurriculumConcept:
    context = f"plan.concepts[{index}]"
    if not isinstance(raw, Mapping):
        raise PlanValidationError(f"{context} must be an object.")
    slug = raw.get("slug")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise PlanValidationError(f"{context}.slug must be slug-like, got {slug!r}.")

    catalogue_id = raw.get("from")
    if catalogue_id is None:
        for field in ("title", "summary", "difficulty"):
            if field not in raw:
                raise PlanValidationError(f"{context} is authored inline and must declare {field}.")
        difficulty = raw.get("difficulty")
        if not isinstance(difficulty, int) or isinstance(difficulty, bool) or not 1 <= difficulty <= 5:
            raise PlanValidationError(f"{context}.difficulty must be an integer between 1 and 5.")
        terms = raw.get("key_terms", [])
        if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
            raise PlanValidationError(f"{context}.key_terms must be a list of strings.")
        return CurriculumConcept(
            slug=slug,
            title=str(raw["title"]),
            summary=str(raw["summary"]),
            difficulty=difficulty,
            key_terms=tuple(terms),
            catalogue_id=None,
        )

    if not isinstance(catalogue_id, str) or catalogue_id not in catalogue:
        known = ", ".join(sorted(catalogue))
        raise PlanValidationError(f"{context}.from names no catalogue skill: {catalogue_id!r}. Known skills: {known}.")

    permitted = {"from", *OVERRIDABLE_FIELDS}
    offered = set(raw) - permitted
    if offered:
        allowed = ", ".join(sorted(OVERRIDABLE_FIELDS))
        raise PlanValidationError(
            f"{context} may not override {', '.join(sorted(offered))}. "
            f"A catalogue skill may restate only: {allowed}."
        )

    skill = catalogue[catalogue_id]
    difficulty = raw.get("difficulty", skill.difficulty)
    if not isinstance(difficulty, int) or isinstance(difficulty, bool) or not 1 <= difficulty <= 5:
        raise PlanValidationError(f"{context}.difficulty must be an integer between 1 and 5.")
    terms = raw.get("key_terms", list(skill.key_terms))
    if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
        raise PlanValidationError(f"{context}.key_terms must be a list of strings.")
    return CurriculumConcept(
        slug=slug,
        title=str(raw.get("title", skill.title)),
        summary=str(raw.get("summary", skill.summary)),
        difficulty=difficulty,
        key_terms=tuple(terms),
        catalogue_id=catalogue_id,
    )


def _edges_from_plan(raw_edges: Sequence[object], slugs: set[str]) -> tuple[CandidateEdge, ...]:
    edges: list[CandidateEdge] = []
    for index, raw in enumerate(raw_edges):
        context = f"plan.edges[{index}]"
        if not isinstance(raw, Mapping):
            raise PlanValidationError(f"{context} must be an object.")
        prereq, target = raw.get("prereq"), raw.get("target")
        for end, value in (("prereq", prereq), ("target", target)):
            if not isinstance(value, str) or value not in slugs:
                raise PlanValidationError(f"{context}.{end} names a concept the plan does not define: {value!r}.")
        if prereq == target:
            raise PlanValidationError(f"{context} links a concept to itself.")
        confidence = raw.get("confidence", 0.8)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise PlanValidationError(f"{context}.confidence must be between 0 and 1.")
        rationale = raw.get("rationale")
        edges.append(
            CandidateEdge(
                prereq=str(prereq),
                target=str(target),
                confidence=float(confidence),
                rationale=rationale if isinstance(rationale, str) else None,
            )
        )
    return tuple(edges)


# @spec CURR-GOAL-007, CURR-GOAL-008, CURR-GOAL-009, CURR-GOAL-010, CURR-GOAL-014
def definition_from_plan(plan: Mapping[str, object], *, instrument: str) -> CurriculumDefinition:
    """Validate a proposed plan and turn it into a curriculum definition.

    Refuses whole rather than repairing. Every failure names both what was wrong
    and what would have been acceptable, because the caller's fallback is to
    assemble deterministically and the message is the only record of why.
    """
    raw_concepts = plan.get("concepts")
    if not isinstance(raw_concepts, list):
        raise PlanValidationError("plan.concepts must be a list.")
    if not MIN_CONCEPTS <= len(raw_concepts) <= MAX_CONCEPTS:
        raise PlanValidationError(
            f"plan.concepts holds {len(raw_concepts)} concepts; a curriculum must have "
            f"between {MIN_CONCEPTS} and {MAX_CONCEPTS}."
        )

    catalogue = load_catalogue()
    concepts: list[CurriculumConcept] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_concepts):
        concept = _concept_from_plan(raw, index, catalogue)
        if concept.slug in seen:
            raise PlanValidationError(f"plan.concepts declares {concept.slug!r} more than once.")
        seen.add(concept.slug)
        concepts.append(concept)

    raw_edges = plan.get("edges", [])
    if not isinstance(raw_edges, list):
        raise PlanValidationError("plan.edges must be a list.")
    edges = _edges_from_plan(raw_edges, seen)

    slug = str(plan.get("instrument", instrument)).replace(" ", "-")
    if not _SLUG.fullmatch(slug):
        raise PlanValidationError(f"plan.instrument must be slug-like, got {slug!r}.")
    title = plan.get("instrument_title")
    return CurriculumDefinition(
        instrument=instrument,
        slug=slug,
        version=1,
        title=str(title) if isinstance(title, str) and title.strip() else _title_for(instrument),
        concepts=tuple(concepts),
        edges=edges,
    )


__all__ = [
    "MAX_CONCEPTS",
    "MIN_CONCEPTS",
    "PlanValidationError",
    "assemble",
    "catalogue_prompt_payload",
    "definition_from_plan",
    "known_instruments",
    "resolve_instrument",
    "CurriculumDefinitionError",
]

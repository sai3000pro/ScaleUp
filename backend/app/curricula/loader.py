"""Load and validate instrument curricula without instrument-specific code.

The compiler accepts the same payload shape whether it came from a checked-in
JSON file, a database draft, or a future reviewed source bundle. Instrument
modules should not contain graph logic; they should only provide curriculum data.

A concept may be authored inline, or drawn from the shared skill catalogue with
`"from": "<catalogue-id>"`. Catalogue-drawn concepts inherit the shared
definition and may override only the fields in `OVERRIDABLE_FIELDS` -- the
surface is fixed rather than open so that a catalogue cannot quietly decay into
one standalone curriculum per instrument wearing a shared name. A concept whose
meaning has to change to fit an instrument is a different skill, and belongs in
the catalogue as one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Mapping

from app.domain.dag import (
    CandidateEdge,
    RejectedEdge,
    build_acyclic_edges,
    topological_depths,
    transitive_reduction,
)

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: What an instrument may restate about a catalogue skill. Everything else --
#: most importantly the skill's identity -- belongs to the catalogue.
OVERRIDABLE_FIELDS = frozenset({"slug", "title", "summary", "difficulty", "key_terms"})

CATALOGUE_NAME = "catalogue"


class CurriculumDefinitionError(ValueError):
    """The curriculum payload cannot be safely compiled."""


@dataclass(frozen=True, slots=True)
class CatalogueSkill:
    """A skill defined once and reusable by any instrument."""

    id: str
    title: str
    summary: str
    difficulty: int
    key_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CurriculumConcept:
    slug: str
    title: str
    summary: str
    difficulty: int
    key_terms: tuple[str, ...]
    #: The catalogue skill this concept realises, or None when authored inline.
    catalogue_id: str | None = None


@dataclass(frozen=True, slots=True)
class CurriculumDefinition:
    instrument: str
    slug: str
    version: int
    title: str
    concepts: tuple[CurriculumConcept, ...]
    edges: tuple[CandidateEdge, ...]


@dataclass(frozen=True, slots=True)
class CompiledCurriculum:
    definition: CurriculumDefinition
    accepted_edges: tuple[CandidateEdge, ...]
    rejected_edges: tuple[RejectedEdge, ...]
    reduced_edges: tuple[CandidateEdge, ...]
    depths: dict[str, int]


def _string(payload: Mapping[str, object], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CurriculumDefinitionError(f"{context}.{key} must be a non-empty string.")
    return value.strip()


def _integer(payload: Mapping[str, object], key: str, context: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CurriculumDefinitionError(f"{context}.{key} must be an integer.")
    return value


def _float(payload: Mapping[str, object], key: str, context: str, default: float = 1.0) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CurriculumDefinitionError(f"{context}.{key} must be numeric.")
    result = float(value)
    if not 0 <= result <= 1:
        raise CurriculumDefinitionError(f"{context}.{key} must be between 0 and 1.")
    return result


def _list(payload: Mapping[str, object], key: str, context: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise CurriculumDefinitionError(f"{context}.{key} must be a list.")
    return value


# @spec CURR-CAT-001
def parse_catalogue_payload(payload: Mapping[str, object]) -> dict[str, CatalogueSkill]:
    """Parse the shared skill catalogue into skills keyed by stable id."""
    raw_skills = _list(payload, "skills", "catalogue")
    skills: dict[str, CatalogueSkill] = {}
    for index, raw in enumerate(raw_skills):
        context = f"catalogue.skills[{index}]"
        if not isinstance(raw, Mapping):
            raise CurriculumDefinitionError(f"{context} must be an object.")
        skill_id = _string(raw, "id", context)
        if not _SLUG.fullmatch(skill_id):
            raise CurriculumDefinitionError(f"{context}.id must be slug-like.")
        if skill_id in skills:
            raise CurriculumDefinitionError(f"Duplicate catalogue skill id: {skill_id!r}.")
        difficulty = _integer(raw, "difficulty", context)
        if not 1 <= difficulty <= 5:
            raise CurriculumDefinitionError(f"{context}.difficulty must be between 1 and 5.")
        raw_terms = raw.get("key_terms", [])
        if not isinstance(raw_terms, list) or not all(isinstance(term, str) and term.strip() for term in raw_terms):
            raise CurriculumDefinitionError(f"{context}.key_terms must contain non-empty strings.")
        skills[skill_id] = CatalogueSkill(
            id=skill_id,
            title=_string(raw, "title", context),
            summary=_string(raw, "summary", context),
            difficulty=difficulty,
            key_terms=tuple(term.strip() for term in raw_terms),
        )
    if not skills:
        raise CurriculumDefinitionError("catalogue.skills must not be empty.")
    return skills


def _catalogue_payload() -> Mapping[str, object]:
    try:
        resource = resources.files("app.curricula").joinpath(f"{CATALOGUE_NAME}.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CurriculumDefinitionError("Skill catalogue data was not found.") from exc
    except json.JSONDecodeError as exc:
        raise CurriculumDefinitionError("Skill catalogue data is not valid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise CurriculumDefinitionError("Skill catalogue data must be a JSON object.")
    return payload


def load_catalogue() -> dict[str, CatalogueSkill]:
    """Load the packaged shared skill catalogue."""
    return parse_catalogue_payload(_catalogue_payload())


# @spec CURR-GOAL-015
def parse_catalogue_edges(payload: Mapping[str, object]) -> tuple[CandidateEdge, ...]:
    """Parse the catalogue's suggested ordering between its own skills.

    These are a prior, not a constraint. They seed a tree for an instrument that
    has no curriculum of its own, and they tell a planner what generally comes
    before what -- but an instrument's published graph remains its own, because
    what must precede what is a claim about that instrument.
    """
    skills = parse_catalogue_payload(payload)
    raw_edges = payload.get("suggested_edges", [])
    if not isinstance(raw_edges, list):
        raise CurriculumDefinitionError("catalogue.suggested_edges must be a list.")
    edges: list[CandidateEdge] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_edges):
        context = f"catalogue.suggested_edges[{index}]"
        if not isinstance(raw, Mapping):
            raise CurriculumDefinitionError(f"{context} must be an object.")
        prereq = _string(raw, "prereq", context)
        target = _string(raw, "target", context)
        for end, value in (("prereq", prereq), ("target", target)):
            if value not in skills:
                raise CurriculumDefinitionError(f"{context}.{end} names no catalogue skill: {value!r}.")
        if prereq == target:
            raise CurriculumDefinitionError(f"{context} links a skill to itself.")
        if (prereq, target) in seen:
            raise CurriculumDefinitionError(f"{context} duplicates an earlier edge.")
        seen.add((prereq, target))
        edges.append(
            CandidateEdge(
                prereq=prereq,
                target=target,
                confidence=_float(raw, "confidence", context),
                rationale=raw.get("rationale") if isinstance(raw.get("rationale"), str) else None,
            )
        )
    return tuple(edges)


# @spec CURR-GOAL-015
def load_catalogue_edges() -> tuple[CandidateEdge, ...]:
    """The catalogue's suggested ordering, as candidate edges between skill ids."""
    return parse_catalogue_edges(_catalogue_payload())


# @spec CURR-CAT-002, CURR-CAT-003, CURR-CAT-004, CURR-CAT-005, CURR-CAT-006, CURR-CAT-008
def _resolve_concept(
    raw: Mapping[str, object],
    context: str,
    catalogue: Mapping[str, CatalogueSkill],
) -> Mapping[str, object]:
    """Apply a catalogue skill's definition beneath an instrument's overrides.

    Returns a plain mapping in the same shape an inline concept uses, so the
    parsing that follows does not need to know where the values came from.
    """
    reference = raw.get("from")
    if reference is None:
        return raw
    if not isinstance(reference, str) or not reference.strip():
        raise CurriculumDefinitionError(f"{context}.from must be a catalogue skill id.")
    skill = catalogue.get(reference.strip())
    if skill is None:
        known = ", ".join(sorted(catalogue)) or "none"
        raise CurriculumDefinitionError(
            f"{context}.from references unknown catalogue skill {reference!r}. Known skills: {known}."
        )
    overrides = {key: value for key, value in raw.items() if key != "from"}
    unknown = sorted(set(overrides) - OVERRIDABLE_FIELDS)
    if unknown:
        allowed = ", ".join(sorted(OVERRIDABLE_FIELDS))
        raise CurriculumDefinitionError(
            f"{context} may not override {', '.join(unknown)} on catalogue skill {skill.id!r}. "
            f"An instrument may restate only: {allowed}."
        )
    resolved: dict[str, object] = {
        "slug": skill.id,
        "title": skill.title,
        "summary": skill.summary,
        "difficulty": skill.difficulty,
        "key_terms": list(skill.key_terms),
    }
    resolved.update(overrides)
    return resolved


# @spec CURR-CAT-007, CURR-CAT-009
def parse_curriculum_payload(
    payload: Mapping[str, object],
    catalogue: Mapping[str, CatalogueSkill] | None = None,
) -> CurriculumDefinition:
    """Parse an untrusted curriculum mapping into a typed definition."""
    instrument = _string(payload, "instrument", "curriculum")
    slug = _string(payload, "slug", "curriculum")
    if not _SLUG.fullmatch(instrument) or not _SLUG.fullmatch(slug):
        raise CurriculumDefinitionError("curriculum.instrument and curriculum.slug must be slug-like.")
    version = _integer(payload, "version", "curriculum")
    if version < 1:
        raise CurriculumDefinitionError("curriculum.version must be positive.")
    title = _string(payload, "title", "curriculum")

    resolved_catalogue = load_catalogue() if catalogue is None else catalogue

    raw_concepts = _list(payload, "concepts", "curriculum")
    concepts: list[CurriculumConcept] = []
    seen_slugs: set[str] = set()
    for index, authored in enumerate(raw_concepts):
        context = f"curriculum.concepts[{index}]"
        if not isinstance(authored, Mapping):
            raise CurriculumDefinitionError(f"{context} must be an object.")
        catalogue_id = authored.get("from")
        raw = _resolve_concept(authored, context, resolved_catalogue)
        concept_slug = _string(raw, "slug", context)
        if not _SLUG.fullmatch(concept_slug):
            raise CurriculumDefinitionError(f"{context}.slug must be slug-like.")
        if concept_slug in seen_slugs:
            raise CurriculumDefinitionError(f"Duplicate curriculum concept slug: {concept_slug!r}.")
        seen_slugs.add(concept_slug)
        difficulty = _integer(raw, "difficulty", context)
        if not 1 <= difficulty <= 5:
            raise CurriculumDefinitionError(f"{context}.difficulty must be between 1 and 5.")
        raw_terms = raw.get("key_terms", [])
        if not isinstance(raw_terms, list) or not all(isinstance(term, str) and term.strip() for term in raw_terms):
            raise CurriculumDefinitionError(f"{context}.key_terms must contain non-empty strings.")
        concepts.append(
            CurriculumConcept(
                slug=concept_slug,
                title=_string(raw, "title", context),
                summary=_string(raw, "summary", context),
                difficulty=difficulty,
                key_terms=tuple(term.strip() for term in raw_terms),
                catalogue_id=catalogue_id if isinstance(catalogue_id, str) else None,
            )
        )

    if not concepts:
        raise CurriculumDefinitionError("curriculum.concepts must not be empty.")

    raw_edges = _list(payload, "edges", "curriculum")
    edges: list[CandidateEdge] = []
    for index, raw in enumerate(raw_edges):
        context = f"curriculum.edges[{index}]"
        if not isinstance(raw, Mapping):
            raise CurriculumDefinitionError(f"{context} must be an object.")
        prereq = _string(raw, "prereq", context)
        target = _string(raw, "target", context)
        if prereq not in seen_slugs or target not in seen_slugs:
            raise CurriculumDefinitionError(f"{context} references a concept that does not exist.")
        support = _integer(raw, "support", context) if "support" in raw else 1
        if support < 1:
            raise CurriculumDefinitionError(f"{context}.support must be positive.")
        rationale = raw.get("rationale", "")
        if not isinstance(rationale, str):
            raise CurriculumDefinitionError(f"{context}.rationale must be a string.")
        edges.append(
            CandidateEdge(
                prereq=prereq,
                target=target,
                confidence=_float(raw, "confidence", context),
                support=support,
                rationale=rationale.strip(),
            )
        )

    return CurriculumDefinition(
        instrument=instrument,
        slug=slug,
        version=version,
        title=title,
        concepts=tuple(concepts),
        edges=tuple(edges),
    )


def load_curriculum(name: str) -> CurriculumDefinition:
    """Load a packaged JSON curriculum by filename, then validate its shape."""
    if not _SLUG.fullmatch(name):
        raise CurriculumDefinitionError(f"Invalid curriculum name: {name!r}.")
    try:
        resource = resources.files("app.curricula").joinpath(f"{name}.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CurriculumDefinitionError(f"Curriculum data was not found: {name!r}.") from exc
    except json.JSONDecodeError as exc:
        raise CurriculumDefinitionError(f"Curriculum data is not valid JSON: {name!r}.") from exc
    if not isinstance(payload, Mapping):
        raise CurriculumDefinitionError(f"Curriculum data must be a JSON object: {name!r}.")
    return parse_curriculum_payload(payload)


def compile_curriculum(
    definition: CurriculumDefinition,
    min_confidence: float = 0.35,
) -> CompiledCurriculum:
    """Validate a curriculum's DAG and produce its renderable reduction."""
    slugs = {concept.slug for concept in definition.concepts}
    accepted, rejected = build_acyclic_edges(slugs, list(definition.edges), min_confidence=min_confidence)
    depths = topological_depths(slugs, accepted)
    reduced = transitive_reduction(slugs, accepted)
    return CompiledCurriculum(
        definition=definition,
        accepted_edges=tuple(accepted),
        rejected_edges=tuple(rejected),
        reduced_edges=tuple(reduced),
        depths=depths,
    )

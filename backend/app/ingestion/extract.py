"""Two-pass concept extraction: map over windows, then reconcile globally.

A single pass cannot see across windows, so cross-chapter prerequisites are
invisible to it and the same concept acquires a different slug in every chapter
that mentions it. The reduce pass sees the whole concept list at once and fixes
both.

Merging is deterministic-first and model-last, because each step is cheaper and
more predictable than the one after it:

    exact slug  ->  embedding cosine >= 0.90  ->  LLM, but only for 0.82-0.90

On a real textbook that sends 3-6 adjudication calls to a model instead of
thousands of pairs, and anything below 0.82 never reaches one at all.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.core.sync_bridge import run_sync
from app.domain.dag import CandidateEdge
from app.llm.base import LLMClient, LLMRole, SchemaValidationError
from app.services.graph_service import ConceptSpec

__all__ = [
    "WindowInput",
    "RawConcept",
    "ExtractionOutcome",
    "extract_window",
    "reduce_concepts",
    "MERGE_CERTAIN",
    "MERGE_FLOOR",
]

# Above this cosine, two concepts are the same thing and no model is consulted.
MERGE_CERTAIN = 0.90
# Below this, they are different and no model is consulted either. The band
# between the two is the only thing worth paying for.
MERGE_FLOOR = 0.82
ADJUDICATION_BATCH = 40


@dataclass(frozen=True, slots=True)
class WindowInput:
    index: int
    section_path: str
    chunk_ids: tuple[str, ...]
    text: str


@dataclass(slots=True)
class RawConcept:
    slug: str
    title: str
    summary: str
    difficulty: int
    assessable: bool
    key_terms: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    mentions: int = 1


@dataclass(slots=True)
class ExtractionOutcome:
    concepts: list[ConceptSpec] = field(default_factory=list)
    edges: list[CandidateEdge] = field(default_factory=list)
    windows_ok: int = 0
    windows_failed: int = 0
    raw_concept_count: int = 0
    merged_away: int = 0


def _normalise_slug(slug: str) -> str:
    """Fold trivial spelling variation before any similarity work.

    Cheap and deterministic: strips a leading article and a plural 's' when the
    stem is long enough that doing so is safe.
    """
    text = re.sub(r"[^a-z0-9-]+", "-", slug.strip().lower()).strip("-")
    text = re.sub(r"^(the|a|an)-", "", text)
    parts = text.split("-")
    if parts and len(parts[-1]) >= 5 and parts[-1].endswith("s") and not parts[-1].endswith("ss"):
        parts[-1] = parts[-1][:-1]
    return "-".join(p for p in parts if p) or slug


# @spec CURR-PARSE-005
def extract_window(client: LLMClient, book_title: str, window: WindowInput) -> tuple[list[RawConcept], list[CandidateEdge]]:
    """One LLM call over one window. Raises on failure; the caller absorbs it."""
    result = run_sync(
        client.structured(
            LLMRole.GRAPH_EXTRACT_MAP,
            {"book_title": book_title, "section_path": window.section_path, "chunks": window.text},
        )
    )

    concepts: list[RawConcept] = []
    for payload in result.data.get("concepts", []):
        slug = _normalise_slug(payload["slug"])
        ordinals = payload.get("evidence_ordinals") or []
        cited = [window.chunk_ids[o] for o in ordinals if 0 <= o < len(window.chunk_ids)]
        concepts.append(
            RawConcept(
                slug=slug,
                title=payload["title"],
                summary=payload["summary"],
                difficulty=int(payload["difficulty"]),
                assessable=bool(payload["assessable"]),
                key_terms=list(payload.get("key_terms") or []),
                # Fall back to the whole window when the model cites nothing --
                # a concept with no provenance cannot be drilled later.
                chunk_ids=cited or list(window.chunk_ids),
            )
        )

    known = {concept.slug for concept in concepts}
    edges = [
        CandidateEdge(
            prereq=_normalise_slug(payload["prereq_slug"]),
            target=_normalise_slug(payload["target_slug"]),
            confidence=float(payload["confidence"]),
            rationale=payload.get("rationale", ""),
        )
        for payload in result.data.get("prerequisites", [])
    ]
    # Within-window edges may only reference within-window concepts; anything
    # else is the model guessing at the cross-window structure that pass two owns.
    edges = [edge for edge in edges if edge.prereq in known and edge.target in known]

    return concepts, edges


def _fold_exact(raw: Iterable[RawConcept]) -> dict[str, RawConcept]:
    """Step one: merge on the normalised slug. Free and exact."""
    folded: dict[str, RawConcept] = {}
    for concept in raw:
        existing = folded.get(concept.slug)
        if existing is None:
            folded[concept.slug] = concept
        else:
            existing.mentions += 1
            existing.chunk_ids = list(dict.fromkeys(existing.chunk_ids + concept.chunk_ids))
            existing.key_terms = list(dict.fromkeys(existing.key_terms + concept.key_terms))
            # Keep the fullest summary; a one-line mention should not overwrite
            # a considered definition.
            if len(concept.summary) > len(existing.summary):
                existing.summary = concept.summary
                existing.title = concept.title
            existing.difficulty = max(existing.difficulty, concept.difficulty)
            existing.assessable = existing.assessable or concept.assessable
    return folded


# @spec LLM-EMBED-004
def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


# @spec CURR-PARSE-006
def reduce_concepts(
    client: LLMClient,
    book_title: str,
    raw_concepts: list[RawConcept],
    window_edges: list[CandidateEdge],
    embed: "callable[[Sequence[str]], list[list[float]]]",
) -> ExtractionOutcome:
    """Merge concepts across windows and propose the cross-window prerequisites."""
    outcome = ExtractionOutcome(raw_concept_count=len(raw_concepts))

    folded = _fold_exact(raw_concepts)
    if not folded:
        return outcome

    slugs = sorted(folded)
    alias: dict[str, str] = {}

    # ── step two: embedding similarity ────────────────────────────────────
    if len(slugs) > 1:
        vectors_list = embed([f"{folded[s].title}. {folded[s].summary}" for s in slugs])
        vectors = dict(zip(slugs, vectors_list))

        # Canonical order: most-mentioned first, so an incidental variant folds
        # into the well-attested concept rather than the reverse.
        ranked = sorted(slugs, key=lambda s: (-folded[s].mentions, s))
        for candidate in ranked:
            for canonical in ranked:
                if canonical == candidate:
                    break
                if canonical not in alias and candidate not in alias:
                    if _cosine(vectors[canonical], vectors[candidate]) >= MERGE_CERTAIN:
                        alias[candidate] = canonical
                        break

        # ── step three: the ambiguous band only ───────────────────────────
        undecided = [s for s in ranked if s not in alias]
        band = [
            (left, right)
            for index, left in enumerate(undecided)
            for right in undecided[index + 1 :]
            if MERGE_FLOOR <= _cosine(vectors[left], vectors[right]) < MERGE_CERTAIN
        ]
        for batch_start in range(0, len(band), ADJUDICATION_BATCH):
            batch = band[batch_start : batch_start + ADJUDICATION_BATCH]
            listing = "\n".join(
                f"- {left} :: {folded[left].title} — {folded[left].summary}\n"
                f"  {right} :: {folded[right].title} — {folded[right].summary}"
                for left, right in batch
            )
            try:
                verdict = run_sync(
                    client.structured(LLMRole.GRAPH_MERGE, {"book_title": book_title, "concepts": listing})
                )
            except SchemaValidationError:
                verdict = None

            if verdict is not None:
                for merge in verdict.data.get("merges", []):
                    canonical = _normalise_slug(merge["canonical_slug"])
                    for raw_alias in merge.get("alias_slugs", []):
                        aliased = _normalise_slug(raw_alias)
                        if aliased != canonical and aliased in folded and canonical in folded:
                            alias.setdefault(aliased, canonical)

    def resolve(slug: str) -> str:
        seen: set[str] = set()
        while slug in alias and slug not in seen:
            seen.add(slug)
            slug = alias[slug]
        return slug

    # Fold aliases into their canonical concept.
    for aliased, canonical in alias.items():
        target = folded[resolve(canonical)]
        source = folded[aliased]
        target.mentions += source.mentions
        target.chunk_ids = list(dict.fromkeys(target.chunk_ids + source.chunk_ids))
        target.key_terms = list(dict.fromkeys(target.key_terms + source.key_terms))

    survivors = {slug: concept for slug, concept in folded.items() if slug not in alias}
    outcome.merged_away = len(folded) - len(survivors)

    # ── cross-window prerequisites ────────────────────────────────────────
    listing = "\n".join(f"- {slug} :: {c.title} — {c.summary}" for slug, c in sorted(survivors.items()))
    global_edges: list[CandidateEdge] = []
    try:
        proposal = run_sync(client.structured(LLMRole.GRAPH_MERGE, {"book_title": book_title, "concepts": listing}))
    except SchemaValidationError:
        proposal = None

    if proposal is not None:
        global_edges = [
            CandidateEdge(
                prereq=resolve(_normalise_slug(edge["prereq_slug"])),
                target=resolve(_normalise_slug(edge["target_slug"])),
                confidence=float(edge["confidence"]),
                rationale=edge.get("rationale", ""),
            )
            for edge in proposal.data.get("edges", [])
        ]

    # Pool both passes, rewriting window edges through the alias map. Support
    # counts how many times an edge was independently proposed, which breaks
    # confidence ties in the DAG builder.
    pooled: dict[tuple[str, str], CandidateEdge] = {}
    for edge in [
        CandidateEdge(resolve(e.prereq), resolve(e.target), e.confidence, e.support, e.rationale)
        for e in window_edges
    ] + global_edges:
        if edge.prereq in survivors and edge.target in survivors and edge.prereq != edge.target:
            key = (edge.prereq, edge.target)
            existing = pooled.get(key)
            if existing is None:
                pooled[key] = edge
            else:
                pooled[key] = CandidateEdge(
                    prereq=edge.prereq,
                    target=edge.target,
                    confidence=max(existing.confidence, edge.confidence),
                    support=existing.support + edge.support,
                    rationale=existing.rationale or edge.rationale,
                )

    outcome.concepts = [
        ConceptSpec(
            slug=slug,
            title=concept.title,
            summary=concept.summary[:400],
            difficulty=concept.difficulty,
            assessable=concept.assessable,
            key_terms=tuple(concept.key_terms[:8]),
            # Provenance. Without it a node cannot be drilled later, because
            # question generation has no source material to retrieve against.
            source_chunk_ids=tuple(_as_uuid(cid) for cid in concept.chunk_ids if _as_uuid(cid) is not None),
            mention_count=concept.mentions,
        )
        for slug, concept in sorted(survivors.items())
    ]
    outcome.edges = list(pooled.values())
    return outcome

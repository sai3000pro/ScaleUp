"""Infer prerequisite edges from section CONTENT, over a closed skill vocabulary.

The table of contents gives the *nodes* and the parent-child nesting the author
wrote down. It cannot tell you that Strong Duality needs Weak Duality, or that
the Simplex Algorithm needs Canonical Forms -- those live in the prose.

The previous stand-in for that was "chapter N precedes chapter N+1". Measured on
CO 250 it put "The KKT Theorem" at depth 6, gated behind Integer Programs, which
it does not require: reading order is not a dependency relation. Dropping it left
the tree correct but flat. This module supplies the edges that were missing.

Why this is a good use of a model, where inventing structure was not: the skill
list is fixed before the call, so the model chooses *among known nodes* rather
than naming new ones. Everything it returns is checked against that list here --
the prompt asks, the code enforces.

## Two directions, because one question cannot find a foundation

The forward pass reads section B and asks "what does B depend on?". That question
can only surface a prerequisite B happens to *name*. Real prose does not say
"Inverse of a Matrix"; it says "since A_B is invertible". Measured on CO 250,
four of the five chapter-0 prerequisite skills were never proposed as anyone's
prerequisite at all -- not because the book does not use them, but because
nothing in the design ever asked.

So there is a second pass that asks the mirror question, "which sections use X?",
for the skills the forward pass never cited. The hard part is evidence. Asking
that question from X's own text alone is unanswerable: X's text does not contain
its dependents, so a model would have nothing to quote and would fill the gap by
guessing. The fix is to put the *candidates' text* in the prompt -- the reverse
call carries X's definition plus a bounded batch of other sections' excerpts, and
the quotation it must return comes from the excerpt of the section it is
accusing. Same discipline as the forward pass, mirrored.

Two properties fall out of doing it that way, both enforced in code rather than
asked for in the prompt:

* **Direction cannot invert.** The reverse call names one source and returns only
  targets, so `prereq` is fixed by the caller. The pass is structurally incapable
  of emitting a backwards edge.
* **The vocabulary stays closed, and gets smaller.** A reverse answer is checked
  against the batch it was shown, not the whole book.

## Cost

The forward pass is one call per section and its payload is dominated by the
skill listing, which is resent every time. The reverse pass is bounded
independently of book length: at most `REVERSE_MAX_SOURCES` (32) sources, each
shown at most `REVERSE_MAX_BATCHES * REVERSE_BATCH_SIZE` (72) candidates in
batches of 24, with every excerpt truncated to `REVERSE_EXCERPT_CHARS`. So the
hard ceiling is **96 reverse calls**, whatever the book, on top of one forward
call per section.

Two consequences worth knowing before quoting that number:

* Because excerpts are truncated, a 3000-page book with 25 sections costs *less*
  here than a 90-page book with 90 -- the opposite of how the forward pass
  scales, whose payload is a whole section.
* On a book with more than 72 sections, a source near the front cannot be shown
  all of its downstream candidates. That is real lost coverage, not a rounding
  error, so it is counted in `reverse_candidates_dropped` and logged rather than
  hidden. Buying full coverage on a 220-skill book means ~9 batches per source,
  i.e. ~288 reverse calls instead of 96.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from app.core.sync_bridge import run_sync
from app.domain.dag import CandidateEdge
from app.llm.base import LLMClient, LLMRole, RefusalError, SchemaValidationError

logger = logging.getLogger(__name__)

__all__ = ["SkillRef", "PrereqOutcome", "infer_prerequisites"]

# Below this the model is guessing from topic overlap rather than reading.
MIN_CONFIDENCE = 0.5
# The reverse question is answered from an excerpt rather than a whole section,
# so it gets a higher bar. A wrong prerequisite locks a learner out of content
# they are ready for; a missing one only fails to gate.
REVERSE_MIN_CONFIDENCE = 0.6
# A section with almost no prose cannot support an inference worth making.
MIN_SECTION_CHARS = 400
# The skill list is sent with every call, so it has to stay affordable.
MAX_SKILLS_LISTED = 220
SUMMARY_CHARS = 110

# ── reverse pass budget ───────────────────────────────────────────────────
# A book's foundational layer is a couple of dozen skills, not hundreds, so the
# sources are capped rather than scaled. Everything here bounds *calls*; none of
# it scales with page count.
REVERSE_MAX_SOURCES = 32
REVERSE_BATCH_SIZE = 24
REVERSE_MAX_BATCHES = 3
REVERSE_EXCERPT_CHARS = 2000
REVERSE_SOURCE_CHARS = 3000
# How many slices of a passage the excerpt is drawn from; 1 is plain head
# truncation. Measured on CO 250, sampling the CANDIDATES across several windows
# did not beat truncating them with the same budget (the score moved by an edge
# or two either way, with no trend -- noise), while sampling the SOURCE's own
# definition across two helped slightly. Both stay as constants because CO 250's
# sections are one to six pages: on a book whose outline gives 25 nodes for 3000
# pages, a 2000-character head is the opening two paragraphs of a 100-page
# chapter, and these are the levers for it.
REVERSE_EXCERPT_WINDOWS = 1
REVERSE_SOURCE_WINDOWS = 2
# A source needs enough prose to be *defined* before asking who uses it.
REVERSE_MIN_SOURCE_CHARS = 300
REVERSE_MIN_CANDIDATE_CHARS = 200
# Only skills the forward pass barely cited are worth re-asking about. A skill
# already named as two other sections' prerequisite is not the missing-foundation
# case this pass exists for.
REVERSE_OUTDEGREE_CEILING = 2

# ── keeping the answer size independent of the vocabulary size ────────────
#
# The forward pass asks one section about the whole skill list, so the number of
# prerequisites it comes back with scales with the list. Sub-section
# segmentation made that visible: the vocabulary went from 37 skills to 135 and
# the pass went from proposing ~1 prerequisite per section to ~3.6, while the
# number of real ones per section stayed where it was. Precision fell from 0.551
# to 0.340 measured at identical granularity.
#
# That is a property of asking, not of the book. A section has the prerequisites
# it has; splitting its neighbours into finer nodes cannot give it more. So cap
# what one section may claim, and rank by how selective each claim is: among
# equally confident proposals the informative one is the prerequisite few other
# sections also named.
#
# 2, because the hand-authored CO 250 reference averages 1.54 prerequisites per
# concept -- the cap is set at the density the material actually has, not at a
# round number. Measured, at both node counts: 2 costs no recall at all and is
# worth 0.04-0.06 precision over 3.
MAX_PREREQS_PER_SECTION = 2

# Reading order is not dependency -- that fallacy is what this module was built
# to replace, and the forward pass is still free to reach backwards. But an edge
# running against the book's order is a much stronger claim than one running
# with it, and should be evidenced accordingly rather than accepted on a passing
# lexical match. In the hand-authored 122-edge CO 250 reference, exactly zero
# edges have a prerequisite printed after their target; in the segmented run,
# all 10 backwards edges did, and all 10 were wrong.
#
# So this is a higher bar, not a ban: a pass that is genuinely confident can
# still say a later section is needed first.
BACKWARD_MIN_CONFIDENCE = 0.8

# Structural (outline) edges are 0.95 and must keep winning cycle contests
# against inference -- see `build_acyclic_edges`, which admits greedily by
# descending confidence. Inference stays below that, and a single direction
# stays below agreement so that agreement is worth something.
MAX_SINGLE_CONFIDENCE = 0.85
MAX_AGREED_CONFIDENCE = 0.9
AGREEMENT_BONUS = 0.1


@dataclass(frozen=True, slots=True)
class SkillRef:
    slug: str
    title: str
    summary: str
    # Where this skill sits in the book -- any monotonic measure will do; the
    # pipeline passes the ordinal of the first chunk the skill owns.
    #
    # It is not optional in spirit, only in signature. Two rules here read the
    # book's order: the reverse pass only offers a source its DOWNSTREAM
    # sections, and `_select` holds a backwards edge to a higher bar. Both used
    # to take the skill's index in the list as its position, which was true
    # until sub-section segmentation, and then quietly stopped being true --
    # `_toc_graph` returns every outline section first and every fragment
    # afterwards, so "The KKT Theorem" on page 82 sits at index 36 and "Affine
    # function" on page 9 sits at index 37. Left alone, that tells the reverse
    # pass that a page-9 fragment is downstream of a page-82 section.
    #
    # Defaults to 0 so an unaware caller gets exactly the old list-order
    # behaviour rather than a surprise.
    order: int = 0


@dataclass(slots=True)
class PrereqOutcome:
    edges: list[CandidateEdge]
    sections_ok: int = 0
    sections_failed: int = 0
    proposed: int = 0
    rejected_unknown: int = 0
    rejected_low_confidence: int = 0
    rejected_self: int = 0
    # reverse pass, counted separately so "did the second question help?" is
    # answerable from the ingest log alone.
    reverse_calls: int = 0
    reverse_failed: int = 0
    reverse_sources: int = 0
    reverse_proposed: int = 0
    reverse_candidates_dropped: int = 0
    reverse_rejected_unknown: int = 0
    reverse_rejected_low_confidence: int = 0
    reverse_only: int = 0
    agreed: int = 0
    rejected_contradicted: int = 0
    # What `_select` threw away. Both are monitorable: a book where most
    # proposals are crowded out is one whose vocabulary outgrew the question.
    rejected_crowded: int = 0
    rejected_backward: int = 0
    # Model-provided quotes that did not occur in the passage shown to it.
    rejected_unsupported: int = 0
    # Verified quotes are retained as the edge's learner-visible rationale.
    evidence_by_edge: dict[tuple[str, str], str] = field(default_factory=dict)


def _render_skill_list(skills: list[SkillRef]) -> str:
    """One line per skill: slug, title in bold, then a short summary.

    The title is delimited, not merely separated. It used to be rendered
    `Title: summary` and read back as everything before the first colon -- so a
    title that CONTAINS a colon was silently truncated to its first word. That
    was not hypothetical: `toc.py` deliberately qualifies generic sections as
    "Formulations: Overview", which came back as the bare word "Formulations"
    and then matched every section in the chapter. One node on a converted
    ebook carried 137 spurious edges this way.

    Bold is the delimiter because a title cannot contain `**`, and it still
    reads as ordinary markdown to a real model.
    """
    return "\n".join(
        f"- `{s.slug}` — **{s.title.replace('*', '')}** — {s.summary[:SUMMARY_CHARS]}"
        for s in skills[:MAX_SKILLS_LISTED]
    )


def _excerpt(text: str, budget: int, windows: int) -> str:
    """At most `budget` characters of a section, drawn from `windows` slices of it.

    Truncating is what makes this pass cost the same on a 90-page book and a
    3000-page one, and where a section's evidence lives decides how much has to
    be kept. On CO 250 the sentence "Since A_B is invertible, multiplying
    A_B^{-1} on both sides" -- the best single piece of evidence that canonical
    form needs matrix inverses -- sits past a 700-character head, and raising the
    budget to 2000 was worth 4 correct edges.

    Spreading the same budget over several slices instead of taking it off the
    top was the other thing tried, and on CO 250 it did not help. It is kept as a
    parameter because the books where it should help -- a section that is 100
    pages long -- are not represented in the measurement.
    """
    single_spaced = " ".join(text.split())
    if len(single_spaced) <= budget or windows < 2:
        return single_spaced[:budget]

    size = budget // windows
    stride = (len(single_spaced) - size) // (windows - 1)
    return " […] ".join(single_spaced[i * stride : i * stride + size] for i in range(windows))


def _render_candidates(batch: list[SkillRef], section_texts: dict[str, str]) -> str:
    """One block per candidate. The excerpt is what the model must quote from."""
    return "\n\n".join(
        f"### `{s.slug}` — {s.title}\n"
        f"{_excerpt(section_texts.get(s.slug, ''), REVERSE_EXCERPT_CHARS, REVERSE_EXCERPT_WINDOWS)}"
        for s in batch
    )


def _quote_is_in_passage(quote: str, passage: str) -> bool:
    """Check a model quote after applying the same whitespace folding as prompts."""
    wanted = " ".join(quote.split()).casefold()
    source = " ".join(passage.split()).casefold()
    return bool(wanted) and wanted in source


# @spec CURR-EDGE-001, CURR-EDGE-002, CURR-EDGE-003, CURR-EDGE-005, CURR-EDGE-006, CURR-EDGE-007
def infer_prerequisites(
    client: LLMClient,
    book_title: str,
    skills: list[SkillRef],
    section_texts: dict[str, str],
    course_id: str | None = None,
    *,
    reverse: bool = True,
) -> PrereqOutcome:
    """Forward pass over every section, then a bounded reverse pass, then merge.

    Failures are absorbed per call, exactly as window extraction is: losing the
    edges of one section still leaves a usable graph, and failing a whole ingest
    over it would be the wrong trade.

    `reverse=False` runs the original single-direction behaviour, which is what
    makes "how much did the second question buy?" measurable rather than
    asserted.
    """
    outcome = PrereqOutcome(edges=[])
    if len(skills) < 2:
        return outcome

    position = _positions(skills)
    forward = _forward_pass(client, book_title, skills, section_texts, course_id, outcome)
    backward: dict[tuple[str, str], float] = {}
    if reverse:
        backward = _reverse_pass(client, book_title, skills, section_texts, forward, course_id, outcome)

    forward = _select(forward, position, outcome)
    backward = _select(backward, position, outcome)
    outcome.edges = _merge(forward, backward, outcome)
    return outcome


def _positions(skills: list[SkillRef]) -> dict[str, int]:
    """Reading order, from `SkillRef.order`, falling back to the order given.

    Ranked rather than used raw, so callers can pass page numbers, chunk
    ordinals, or nothing at all and every comparison still means the same thing.
    """
    ranked = sorted(range(len(skills)), key=lambda i: (skills[i].order, i))
    return {skills[index].slug: rank for rank, index in enumerate(ranked)}


def _select(
    proposals: dict[tuple[str, str], float], position: dict[str, int], outcome: PrereqOutcome
) -> dict[tuple[str, str], float]:
    """Keep each section's best few prerequisites, and hold backwards edges to a higher bar.

    Ranked by confidence first, then by how *selective* the claim is: a
    prerequisite that only two other sections also named says something about
    this section, and one that forty sections named says something about the
    book's vocabulary. Ranking by selectivity rather than cutting on it outright
    was the version that worked -- cutting the common ones lost correct edges at
    the same rate it lost wrong ones, because the hubs are genuinely central.
    """
    fanout = Counter(prereq for prereq, _ in proposals)
    by_target: dict[str, list[tuple[str, float]]] = {}

    for (prereq, target), confidence in proposals.items():
        backwards = position.get(prereq, 0) > position.get(target, 0)
        if backwards and confidence < BACKWARD_MIN_CONFIDENCE:
            outcome.rejected_backward += 1
        else:
            by_target.setdefault(target, []).append((prereq, confidence))

    kept: dict[tuple[str, str], float] = {}
    for target, claims in by_target.items():
        claims.sort(key=lambda claim: (-claim[1], fanout[claim[0]], claim[0]))
        for prereq, confidence in claims[:MAX_PREREQS_PER_SECTION]:
            kept[(prereq, target)] = confidence
        outcome.rejected_crowded += max(0, len(claims) - MAX_PREREQS_PER_SECTION)

    return kept


def _forward_pass(
    client: LLMClient,
    book_title: str,
    skills: list[SkillRef],
    section_texts: dict[str, str],
    course_id: str | None,
    outcome: PrereqOutcome,
) -> dict[tuple[str, str], float]:
    """One call per section with enough prose to reason about: "what does this need?"."""
    known = {s.slug for s in skills}
    listing = _render_skill_list(skills)
    by_slug = {s.slug: s for s in skills}
    found: dict[tuple[str, str], float] = {}

    for slug, text in section_texts.items():
        if slug not in known or len(text) < MIN_SECTION_CHARS:
            skip_reason = "unknown slug" if slug not in known else "too little prose"
            logger.debug("skipping prerequisite inference for %s: %s", slug, skip_reason)
        else:
            try:
                result = run_sync(
                    client.structured(
                        LLMRole.PREREQ_INFER,
                        {
                            "book_title": book_title,
                            "skill_list": listing,
                            "section_title": by_slug[slug].title,
                            "section_slug": slug,
                            "section_text": text,
                        },
                        course_id=course_id,
                    )
                )
            except (SchemaValidationError, RefusalError) as exc:
                outcome.sections_failed += 1
                logger.warning("prerequisite inference failed for %s: %s", slug, exc)
            else:
                outcome.sections_ok += 1
                _absorb(result.data.get("edges", []), known, found, text, outcome)

    return found


def _absorb(
    proposed: list[dict],
    known: set[str],
    found: dict[tuple[str, str], float],
    passage: str,
    outcome: PrereqOutcome,
) -> None:
    """Keep only edges between known skills, above the confidence floor.

    The prompt states the vocabulary is closed; this is what makes it true. A
    model that names a plausible-sounding skill the book does not contain would
    otherwise create a node-less edge that `build_acyclic_edges` silently drops
    later, with no record of why.
    """
    for edge in proposed:
        outcome.proposed += 1
        prereq = str(edge.get("prereq_slug", ""))
        target = str(edge.get("target_slug", ""))
        confidence = float(edge.get("confidence", 0.0))
        evidence = str(edge.get("evidence", "")).strip()

        if prereq not in known or target not in known:
            outcome.rejected_unknown += 1
        elif prereq == target:
            outcome.rejected_self += 1
        elif confidence < MIN_CONFIDENCE:
            outcome.rejected_low_confidence += 1
        elif not _quote_is_in_passage(evidence, passage):
            outcome.rejected_unsupported += 1
        else:
            pair = (prereq, target)
            previous = found.get(pair)
            found[pair] = max(previous or 0.0, confidence)
            if previous is None or confidence >= previous:
                outcome.evidence_by_edge[pair] = evidence


def _reverse_sources(
    skills: list[SkillRef], section_texts: dict[str, str], forward: dict[tuple[str, str], float]
) -> list[SkillRef]:
    """The under-cited skills, in document order, capped.

    Document order rather than "most foundational by some score": in a textbook
    the material a later chapter leans on is the material printed first, and any
    cleverer ranking would need the very dependency information this pass exists
    to produce.
    """
    outdegree = Counter(prereq for prereq, _ in forward)
    eligible = [
        s
        for s in skills
        if len(section_texts.get(s.slug, "")) >= REVERSE_MIN_SOURCE_CHARS
        and outdegree[s.slug] < REVERSE_OUTDEGREE_CEILING
    ]
    return eligible[:REVERSE_MAX_SOURCES]


def _candidates_for(source: SkillRef, pool: list[SkillRef], position: dict[str, int]) -> list[SkillRef]:
    """Sections printed after the source, in order.

    This is a division of labour, not the reading-order fallacy coming back in
    through the side door. The forward pass reads a whole section and may name a
    prerequisite from anywhere in the book, later pages included; nothing here
    stops it. This pass exists for the *other* case -- a foundation that nothing
    downstream names by title -- and downstream is where its dependents are.

    Letting it look backwards as well was measured, and it is where the damage
    is: `basis` defines a basis as a set of columns whose submatrix is
    invertible, so a backwards-looking reverse pass reads that as "Inverse of a
    Matrix depends on Basis" and inverts the edge. In the run that allowed it,
    14 edges came out backwards and 13 of them were of exactly that shape;
    restricting candidates to downstream sections took the count to 1, which is
    what the outline-only baseline already had. The hand-authored CO 250
    reference contains no edge at all whose prerequisite is printed after its
    target.
    """
    at = position[source.slug]
    return [s for s in pool if position[s.slug] > at]


def _reverse_pass(
    client: LLMClient,
    book_title: str,
    skills: list[SkillRef],
    section_texts: dict[str, str],
    forward: dict[tuple[str, str], float],
    course_id: str | None,
    outcome: PrereqOutcome,
) -> dict[tuple[str, str], float]:
    """"Which of these sections use X?", asked of X's definition plus their text."""
    position = _positions(skills)
    pool = sorted(
        (s for s in skills if len(section_texts.get(s.slug, "")) >= REVERSE_MIN_CANDIDATE_CHARS),
        key=lambda s: position[s.slug],
    )
    sources = _reverse_sources(skills, section_texts, forward)
    found: dict[tuple[str, str], float] = {}

    reach = REVERSE_BATCH_SIZE * REVERSE_MAX_BATCHES
    for source in sources:
        downstream = [s for s in _candidates_for(source, pool, position) if s.slug != source.slug]
        candidates = downstream[:reach]
        # Counted, never silent. On a book with more sections than one source's
        # batch budget can cover, this is the coverage the pass is NOT buying,
        # and it belongs in the ingest stats rather than in a comment.
        outcome.reverse_candidates_dropped += len(downstream) - len(candidates)

        if not candidates:
            logger.debug("no reverse candidates for %s", source.slug)
        else:
            outcome.reverse_sources += 1
            for start in range(0, len(candidates), REVERSE_BATCH_SIZE):
                batch = candidates[start : start + REVERSE_BATCH_SIZE]
                _reverse_call(client, book_title, source, batch, section_texts, course_id, found, outcome)

    if outcome.reverse_candidates_dropped:
        logger.info(
            "reverse pass skipped %s candidate sections beyond the %s-per-source budget",
            outcome.reverse_candidates_dropped,
            reach,
        )

    return found


def _reverse_call(
    client: LLMClient,
    book_title: str,
    source: SkillRef,
    batch: list[SkillRef],
    section_texts: dict[str, str],
    course_id: str | None,
    found: dict[tuple[str, str], float],
    outcome: PrereqOutcome,
) -> None:
    outcome.reverse_calls += 1
    try:
        result = run_sync(
            client.structured(
                LLMRole.PREREQ_DEPENDENTS,
                {
                    "book_title": book_title,
                    "source_slug": source.slug,
                    "source_title": source.title,
                    "source_text": _excerpt(
                        section_texts.get(source.slug, ""), REVERSE_SOURCE_CHARS, REVERSE_SOURCE_WINDOWS
                    ),
                    "candidates": _render_candidates(batch, section_texts),
                },
                course_id=course_id,
            )
        )
    except (SchemaValidationError, RefusalError) as exc:
        outcome.reverse_failed += 1
        logger.warning("dependent inference failed for %s: %s", source.slug, exc)
    else:
        _absorb_reverse(result.data.get("dependents", []), source.slug, batch, section_texts, found, outcome)


def _absorb_reverse(
    proposed: list[dict],
    source_slug: str,
    shown: list[SkillRef],
    section_texts: dict[str, str],
    found: dict[tuple[str, str], float],
    outcome: PrereqOutcome,
) -> None:
    """`prereq` is the source, always. The model only gets to name the target.

    That is the whole reason this pass cannot invert a direction: the arrow is
    fixed by the caller and the answer is checked against the batch that was
    actually shown, which is a smaller closed vocabulary than the full book.
    """
    shown_slugs = {skill.slug for skill in shown}
    for item in proposed:
        outcome.reverse_proposed += 1
        target = str(item.get("target_slug", ""))
        confidence = float(item.get("confidence", 0.0))
        evidence = str(item.get("evidence", "")).strip()

        if target not in shown_slugs:
            outcome.reverse_rejected_unknown += 1
        elif target == source_slug:
            outcome.rejected_self += 1
        elif confidence < REVERSE_MIN_CONFIDENCE:
            outcome.reverse_rejected_low_confidence += 1
        elif not _quote_is_in_passage(
            evidence,
            _excerpt(section_texts.get(target, ""), REVERSE_EXCERPT_CHARS, REVERSE_EXCERPT_WINDOWS),
        ):
            outcome.rejected_unsupported += 1
        else:
            pair = (source_slug, target)
            previous = found.get(pair)
            found[pair] = max(previous or 0.0, confidence)
            if previous is None or pair not in outcome.evidence_by_edge:
                outcome.evidence_by_edge[pair] = evidence


def _merge(
    forward: dict[tuple[str, str], float],
    reverse: dict[tuple[str, str], float],
    outcome: PrereqOutcome,
) -> list[CandidateEdge]:
    """Union the two directions; agreement is evidence, contradiction is not.

    Two independent questions landing on the same arrow is the strongest signal
    this module produces, so it gets the higher confidence cap and `support=2`
    -- which is the tiebreaker `build_acyclic_edges` uses when confidences match.
    A contradiction is resolved in favour of the forward pass, which read the
    whole section rather than an excerpt of it.
    """
    edges: list[CandidateEdge] = []
    for pair in sorted(set(forward) | set(reverse)):
        prereq, target = pair
        forward_confidence = forward.get(pair)
        reverse_confidence = reverse.get(pair)
        opposite = (target, prereq)

        if forward_confidence is not None and reverse_confidence is not None:
            outcome.agreed += 1
            confidence = min(MAX_AGREED_CONFIDENCE, max(forward_confidence, reverse_confidence) + AGREEMENT_BONUS)
            edges.append(
                CandidateEdge(
                    prereq=prereq,
                    target=target,
                    confidence=confidence,
                    support=2,
                    rationale=outcome.evidence_by_edge.get(pair, ""),
                )
            )
        elif forward_confidence is not None:
            confidence = min(MAX_SINGLE_CONFIDENCE, forward_confidence)
            edges.append(
                CandidateEdge(
                    prereq=prereq,
                    target=target,
                    confidence=confidence,
                    support=1,
                    rationale=outcome.evidence_by_edge.get(pair, ""),
                )
            )
        elif opposite in forward:
            outcome.rejected_contradicted += 1
        elif reverse.get(opposite, -1.0) >= reverse_confidence:
            # Two sources each claiming the other depends on them. Keep the
            # stronger claim only, and on an exact tie keep neither.
            outcome.rejected_contradicted += 1
        else:
            outcome.reverse_only += 1
            confidence = min(MAX_SINGLE_CONFIDENCE, reverse_confidence)
            edges.append(
                CandidateEdge(
                    prereq=prereq,
                    target=target,
                    confidence=confidence,
                    support=1,
                    rationale=outcome.evidence_by_edge.get(pair, ""),
                )
            )

    return edges

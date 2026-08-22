"""Content-inferred prerequisites, over a closed skill vocabulary.

The table of contents supplies the nodes and the author's nesting. It cannot
know that Strong Duality needs Weak Duality -- that is in the prose. The stand-in
for that used to be "chapter N precedes chapter N+1", which put "The KKT Theorem"
at depth 6 behind Integer Programs, a chapter it does not require.

What makes this a safe use of a model is that the vocabulary is fixed before the
call: it chooses among known slugs rather than naming new ones. The prompt says
so; these tests are what make it true.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.ingestion.prereqs import (
    BACKWARD_MIN_CONFIDENCE,
    MAX_AGREED_CONFIDENCE,
    MAX_PREREQS_PER_SECTION,
    MAX_SINGLE_CONFIDENCE,
    MIN_CONFIDENCE,
    MIN_SECTION_CHARS,
    REVERSE_BATCH_SIZE,
    REVERSE_MAX_BATCHES,
    REVERSE_MAX_SOURCES,
    REVERSE_MIN_CONFIDENCE,
    REVERSE_OUTDEGREE_CEILING,
    PrereqOutcome,
    SkillRef,
    _excerpt,
    _merge,
    _positions,
    _select,
    infer_prerequisites,
)
from app.llm.base import LLMRole, RefusalError, SchemaValidationError, StructuredResult, Usage

SKILLS = [
    SkillRef("weak-duality", "Weak Duality", "Bounds the primal by the dual."),
    SkillRef("strong-duality", "Strong Duality", "Equality at optimality."),
    SkillRef("simplex", "Simplex Algorithm", "Pivoting to an optimal basis."),
]
PROSE = "recall that ... " + "x" * (MIN_SECTION_CHARS + 10)


class StubClient:
    """Implements app.llm.base.LLMClient, returning a canned edge list."""

    provider = "fake"

    def __init__(self, edges: list[dict[str, Any]] | Exception) -> None:
        self._edges = edges
        self.calls: list[str] = []

    def model_for(self, role: LLMRole) -> str:
        return "stub"

    async def structured(self, role, variables: Mapping[str, Any], *, course_id=None) -> StructuredResult:
        self.calls.append(str(variables.get("section_slug")))
        if isinstance(self._edges, Exception):
            raise self._edges
        return StructuredResult(
            data={"edges": self._edges},
            raw_text="",
            model="stub",
            provider="fake",
            prompt_id="prereq_infer",
            prompt_version="v1",
            prompt_sha256="0" * 64,
            request_fingerprint="0" * 64,
            usage=Usage(),
        )


def edge(prereq: str, target: str, confidence: float = 0.8) -> dict[str, Any]:
    return {"prereq_slug": prereq, "target_slug": target, "confidence": confidence, "evidence": "recall that ..."}


def run(edges, texts=None):
    client = StubClient(edges)
    texts = texts if texts is not None else {"strong-duality": PROSE}
    # The forward pass alone, so these assertions stay about the forward pass.
    return client, infer_prerequisites(client, "Book", SKILLS, texts, reverse=False)


# ── the closed vocabulary ─────────────────────────────────────────────────


def test_an_edge_between_known_skills_is_kept() -> None:
    _, outcome = run([edge("weak-duality", "strong-duality")])
    assert [(e.prereq, e.target) for e in outcome.edges] == [("weak-duality", "strong-duality")]


def test_a_slug_the_book_does_not_contain_is_discarded() -> None:
    """A model naming a plausible-sounding skill must not create a node-less edge."""
    _, outcome = run([edge("lagrangian-duality", "strong-duality")])
    assert outcome.edges == []
    assert outcome.rejected_unknown == 1


def test_a_self_edge_is_discarded() -> None:
    _, outcome = run([edge("strong-duality", "strong-duality")])
    assert outcome.edges == []
    assert outcome.rejected_self == 1


def test_low_confidence_is_discarded() -> None:
    """Below the floor the model is guessing from topic overlap, not reading."""
    _, outcome = run([edge("weak-duality", "strong-duality", MIN_CONFIDENCE - 0.01)])
    assert outcome.edges == []
    assert outcome.rejected_low_confidence == 1


def test_an_edge_without_a_verifiable_quote_is_discarded() -> None:
    _, outcome = run([edge("weak-duality", "strong-duality") | {"evidence": "not in the section"}])
    assert outcome.edges == []
    assert outcome.rejected_unsupported == 1


def test_verified_quote_is_retained_as_edge_rationale() -> None:
    _, outcome = run([edge("weak-duality", "strong-duality")])
    assert outcome.edges[0].rationale == "recall that ..."


def test_confidence_never_outranks_the_structural_edges() -> None:
    """Outline nesting is 0.95 and should win a cycle contest against inference."""
    _, outcome = run([edge("weak-duality", "strong-duality", 1.0)])
    assert outcome.edges[0].confidence <= 0.9


def test_duplicate_proposals_collapse() -> None:
    _, outcome = run([edge("weak-duality", "strong-duality"), edge("weak-duality", "strong-duality", 0.9)])
    assert len(outcome.edges) == 1


# ── which sections get read ───────────────────────────────────────────────


def test_sections_with_too_little_prose_are_skipped() -> None:
    """A heading with no body cannot support an inference worth making."""
    client, outcome = run([], texts={"strong-duality": "too short"})
    assert client.calls == []
    assert outcome.sections_ok == 0


def test_a_section_that_is_not_a_known_skill_is_skipped() -> None:
    client, _ = run([], texts={"not-a-skill": PROSE})
    assert client.calls == []


def test_nothing_runs_when_there_is_no_vocabulary_to_choose_from() -> None:
    client = StubClient([])
    outcome = infer_prerequisites(client, "Book", SKILLS[:1], {"weak-duality": PROSE})
    assert client.calls == []
    assert outcome.edges == []


# ── failures are absorbed per section ─────────────────────────────────────


def test_a_failed_section_does_not_fail_the_ingest() -> None:
    """Losing one section's edges still leaves a usable graph."""
    _, outcome = run(SchemaValidationError("bad json"))
    assert outcome.edges == []
    assert outcome.sections_failed == 1


def test_a_refusal_is_absorbed_too() -> None:
    _, outcome = run(RefusalError("declined"))
    assert outcome.sections_failed == 1


def test_an_empty_answer_is_a_real_answer() -> None:
    """Most sections depend on nothing; the prompt says so explicitly."""
    _, outcome = run([])
    assert outcome.edges == []
    assert outcome.sections_ok == 1
    assert outcome.sections_failed == 0


# ── the reverse pass ──────────────────────────────────────────────────────
#
# The forward pass can only ever find a prerequisite the section NAMES. A
# foundation that later chapters use without naming -- "since A_B is
# invertible", never "Inverse of a Matrix" -- is invisible to it, whatever the
# model. The reverse pass asks the mirror question of the skills nobody cited,
# with the candidates' own prose in the prompt so the answer can be quoted.

BOOK = [
    SkillRef("inverse", "Inverse of a Matrix", "A A^-1 = I."),
    SkillRef("basis", "Basis", "An invertible column submatrix."),
    SkillRef("canonical", "Canonical Form", "Computed as A_B^-1 A."),
    SkillRef("simplex", "Simplex", "Pivot to an optimal basis."),
]
TEXTS = {
    s.slug: f"{s.title}. {s.summary} since A_B is invertible; recall that ... " + "prose " * 120
    for s in BOOK
}


class TwoWayStub:
    """Implements app.llm.base.LLMClient for both prerequisite roles."""

    provider = "fake"

    def __init__(self, forward: list[dict[str, Any]], dependents: dict[str, list[dict[str, Any]]] | Exception) -> None:
        self._forward = forward
        self._dependents = dependents
        self.forward_calls: list[str] = []
        self.reverse_calls: list[tuple[str, tuple[str, ...]]] = []

    def model_for(self, role: LLMRole) -> str:
        return "stub"

    async def structured(self, role, variables: Mapping[str, Any], *, course_id=None) -> StructuredResult:
        if role is LLMRole.PREREQ_INFER:
            self.forward_calls.append(str(variables.get("section_slug")))
            payload: dict[str, Any] = {"edges": self._forward}
        else:
            source = str(variables.get("source_slug"))
            shown = tuple(re.findall(r"^### `([a-z0-9-]+)`", str(variables.get("candidates", "")), re.M))
            self.reverse_calls.append((source, shown))
            if isinstance(self._dependents, Exception):
                raise self._dependents
            payload = {"dependents": self._dependents.get(source, [])}

        return StructuredResult(
            data=payload,
            raw_text="",
            model="stub",
            provider="fake",
            prompt_id="stub",
            prompt_version="v1",
            prompt_sha256="0" * 64,
            request_fingerprint="0" * 64,
            usage=Usage(),
        )


def dependent(target: str, confidence: float = 0.8) -> dict[str, Any]:
    return {"target_slug": target, "confidence": confidence, "evidence": "since A_B is invertible"}


def both(forward: list[dict[str, Any]], dependents, skills=None, texts=None) -> tuple[TwoWayStub, PrereqOutcome]:
    client = TwoWayStub(forward, dependents)
    return client, infer_prerequisites(client, "Book", skills or BOOK, texts or TEXTS)


def pairs(outcome: PrereqOutcome) -> set[tuple[str, str]]:
    return {(e.prereq, e.target) for e in outcome.edges}


def test_the_reverse_pass_finds_what_nothing_named() -> None:
    """The whole reason this exists: no section cited `inverse`, so ask directly."""
    _, outcome = both([], {"inverse": [dependent("canonical")]})
    assert ("inverse", "canonical") in pairs(outcome)
    assert outcome.reverse_only == 1


def test_the_reverse_pass_runs_by_default() -> None:
    client, _ = both([], {})
    assert client.reverse_calls, "the call site passes no flag, so the default must be on"


def test_reverse_can_be_turned_off_for_measurement() -> None:
    client = TwoWayStub([], {"inverse": [dependent("canonical")]})
    outcome = infer_prerequisites(client, "Book", BOOK, TEXTS, reverse=False)
    assert client.reverse_calls == []
    assert outcome.edges == []


def test_the_reverse_pass_cannot_invert_a_direction() -> None:
    """The model names only the target; `prereq` is fixed by the caller.

    A backwards prerequisite edge locks a learner out of material they are ready
    for, which is worse than a missing one. This pass is structurally incapable
    of producing one, and that is worth a test rather than a comment.
    """
    _, outcome = both([], {"inverse": [dependent("canonical"), dependent("basis")]})
    assert pairs(outcome) == {("inverse", "canonical"), ("inverse", "basis")}
    assert all(edge.prereq == "inverse" for edge in outcome.edges)


def test_a_target_that_was_not_in_the_batch_is_discarded() -> None:
    """The vocabulary is closed, and for a reverse answer it is closed tighter:
    not "any skill in the book" but "one of the ones I was just shown"."""
    _, outcome = both([], {"inverse": [dependent("lagrangian-duality")]})
    assert outcome.edges == []
    assert outcome.reverse_rejected_unknown == 1


def test_a_reverse_self_edge_is_discarded() -> None:
    _, outcome = both([], {"inverse": [dependent("inverse")]})
    assert outcome.edges == []


def test_the_reverse_floor_is_higher_than_the_forward_one() -> None:
    """An excerpt is weaker evidence than a whole section, so it costs more."""
    assert REVERSE_MIN_CONFIDENCE > MIN_CONFIDENCE
    _, outcome = both([], {"inverse": [dependent("canonical", REVERSE_MIN_CONFIDENCE - 0.01)]})
    assert outcome.edges == []
    assert outcome.reverse_rejected_low_confidence == 1


def test_agreement_between_the_two_directions_raises_confidence_and_support() -> None:
    """Two independent questions landing on the same arrow is the strongest
    signal this module produces, and `support` is what breaks a confidence tie
    inside `build_acyclic_edges`."""
    _, outcome = both([edge("inverse", "canonical", 0.8)], {"inverse": [dependent("canonical", 0.8)]})
    agreed = next(e for e in outcome.edges if (e.prereq, e.target) == ("inverse", "canonical"))
    assert outcome.agreed == 1
    assert agreed.support == 2
    assert agreed.confidence > MAX_SINGLE_CONFIDENCE


def test_no_inference_can_outrank_a_structural_edge_even_when_both_agree() -> None:
    """Outline nesting is 0.95 and must keep winning cycle contests."""
    _, outcome = both([edge("inverse", "canonical", 1.0)], {"inverse": [dependent("canonical", 1.0)]})
    assert max(e.confidence for e in outcome.edges) <= MAX_AGREED_CONFIDENCE < 0.95


def test_a_contradiction_is_resolved_in_favour_of_the_forward_pass() -> None:
    """Forward read the whole section; reverse read an excerpt of it.

    `canonical -> basis` is a backward-in-page edge, which the forward pass is
    entirely free to propose. The reverse pass, reading basis's downstream
    candidates, claims the opposite. One of them has to lose, and it is the one
    that saw less text.
    """
    _, outcome = both([edge("canonical", "basis", 0.8)], {"basis": [dependent("canonical")]})
    assert pairs(outcome) == {("canonical", "basis")}
    assert outcome.rejected_contradicted == 1


def test_two_reverse_sources_each_claiming_the_other_cancel_out() -> None:
    """Unreachable through `infer_prerequisites` -- candidate sets are strictly
    downstream, so two sources cannot name each other -- but `_merge` must still
    be correct on its own inputs, or re-widening the candidate rule later would
    silently admit a contradiction."""
    outcome = PrereqOutcome(edges=[])
    merged = _merge({}, {("a", "b"): 0.8, ("b", "a"): 0.8}, outcome)
    assert merged == []
    assert outcome.rejected_contradicted == 2

    outcome = PrereqOutcome(edges=[])
    merged = _merge({}, {("a", "b"): 0.9, ("b", "a"): 0.7}, outcome)
    assert [(e.prereq, e.target) for e in merged] == [("a", "b")]


def test_a_failed_reverse_call_does_not_fail_the_ingest() -> None:
    _, outcome = both([edge("inverse", "canonical")], SchemaValidationError("bad json"))
    assert pairs(outcome) == {("inverse", "canonical")}
    assert outcome.reverse_failed == outcome.reverse_calls > 0


def test_a_reverse_refusal_is_absorbed_too() -> None:
    _, outcome = both([], RefusalError("declined"))
    assert outcome.edges == []
    assert outcome.reverse_failed > 0


# ── what the reverse pass is allowed to cost ──────────────────────────────


def test_only_the_sections_printed_after_the_source_are_offered_as_candidates() -> None:
    """Not the reading-order fallacy: the forward pass may still name a
    prerequisite from anywhere. This pass hunts foundations, and a foundation's
    dependents are downstream. Letting it look backwards was measured on CO 250
    and produced 13 of 14 backwards edges."""
    client, _ = both([], {})
    for source, shown in client.reverse_calls:
        order = [s.slug for s in BOOK]
        assert all(order.index(slug) > order.index(source) for slug in shown), (source, shown)


def test_a_well_cited_skill_is_not_re_asked_about() -> None:
    """Budget goes to the skills the forward pass missed, not the ones it found."""
    cited = [edge("simplex", target) for target in ("basis", "canonical")]
    client, _ = both(cited, {})
    assert REVERSE_OUTDEGREE_CEILING == 2
    assert "simplex" not in {source for source, _ in client.reverse_calls}


def test_the_number_of_reverse_calls_is_bounded_whatever_the_book() -> None:
    """The forward pass costs one call per section; this must not cost n^2."""
    many = [SkillRef(f"s{i:03d}", f"Skill {i}", "summary") for i in range(300)]
    texts = {s.slug: "prose " * 200 for s in many}
    client = TwoWayStub([], {})
    infer_prerequisites(client, "Book", many, texts)
    assert len(client.reverse_calls) <= REVERSE_MAX_SOURCES * REVERSE_MAX_BATCHES
    assert all(len(shown) <= REVERSE_BATCH_SIZE for _, shown in client.reverse_calls)


def test_truncated_candidate_coverage_is_counted_not_hidden() -> None:
    """Silently capping coverage is worse than reporting it."""
    many = [SkillRef(f"s{i:03d}", f"Skill {i}", "summary") for i in range(300)]
    texts = {s.slug: "prose " * 200 for s in many}
    outcome = infer_prerequisites(TwoWayStub([], {}), "Book", many, texts)
    assert outcome.reverse_candidates_dropped > 0


def test_an_excerpt_stays_within_its_budget_however_long_the_section() -> None:
    """This is what keeps a 3000-page book cheaper here than a 90-page one."""
    long_section = "sentence. " * 5000
    assert len(_excerpt(long_section, 400, 1)) <= 400
    sampled = _excerpt(long_section, 400, 4)
    assert len(sampled) <= 400 + len(" […] ") * 3
    assert _excerpt("short", 400, 4) == "short"


# ── reading order ─────────────────────────────────────────────────────────
#
# Two rules read the book's order, and both took a skill's index in the list as
# its position. That was true until sub-section segmentation, at which point
# `_toc_graph` began returning every outline section first and every fragment
# afterwards -- so a page-82 section sat at index 36 and a page-9 fragment at
# index 37, and "downstream" started meaning the opposite of what it says.


def test_position_comes_from_the_order_field_when_the_caller_supplies_one() -> None:
    listed = [
        SkillRef("late-section", "Late", "s", order=900),
        SkillRef("early-fragment", "Early", "s", order=10),
    ]
    position = _positions(listed)
    assert position["early-fragment"] < position["late-section"]


def test_position_falls_back_to_list_order_for_a_caller_that_sets_nothing() -> None:
    """An unaware caller must get the old behaviour, not a surprise."""
    listed = [SkillRef(f"s{i}", f"S{i}", "s") for i in range(4)]
    assert _positions(listed) == {"s0": 0, "s1": 1, "s2": 2, "s3": 3}


def test_the_reverse_pass_reads_order_not_list_position() -> None:
    """The regression that segmentation introduced, pinned.

    `late` is listed first but printed last, so it has no downstream candidates
    at all and must never be offered `early` as one.
    """
    listed = [
        SkillRef("late", "Late Section", "s", order=900),
        SkillRef("early", "Early Fragment", "s", order=10),
    ]
    texts = {s.slug: "prose " * 200 for s in listed}
    client = TwoWayStub([], {})
    infer_prerequisites(client, "Book", listed, texts)
    assert [(source, shown) for source, shown in client.reverse_calls] == [("early", ("late",))]


# ── selection: keeping the answer size independent of the vocabulary ──────


def positions(*slugs: str) -> dict[str, int]:
    return {slug: i for i, slug in enumerate(slugs)}


def test_a_section_may_only_claim_so_many_prerequisites() -> None:
    """A section has the prerequisites it has. Splitting its neighbours into
    finer nodes cannot give it more, but asking against a longer list did."""
    order = positions(*[f"p{i}" for i in range(10)], "target")
    proposals = {(f"p{i}", "target"): 0.6 + i / 100 for i in range(10)}
    outcome = PrereqOutcome(edges=[])
    kept = _select(proposals, order, outcome)
    assert len(kept) == MAX_PREREQS_PER_SECTION
    assert outcome.rejected_crowded == 10 - MAX_PREREQS_PER_SECTION
    # The most confident survive, whatever the cap is set to.
    survivors = {f"p{i}" for i in range(10 - MAX_PREREQS_PER_SECTION, 10)}
    assert {prereq for prereq, _ in kept} == survivors


def test_the_more_selective_claim_wins_a_confidence_tie() -> None:
    """Among equally confident proposals the informative one is the prerequisite
    that few other sections also named; the one forty sections named is telling
    you about the book's vocabulary, not about this section."""
    order = positions("everywhere", "rare", "a", "b", "c", "target")
    proposals: dict[tuple[str, str], float] = {("everywhere", slug): 0.7 for slug in ("a", "b", "c", "target")}
    proposals[("rare", "target")] = 0.7
    kept = _select(proposals, order, PrereqOutcome(edges=[]))
    assert ("rare", "target") in kept


def test_an_edge_running_against_the_book_needs_more_than_a_passing_mention() -> None:
    order = positions("earlier", "later")
    outcome = PrereqOutcome(edges=[])
    kept = _select({("later", "earlier"): BACKWARD_MIN_CONFIDENCE - 0.01}, order, outcome)
    assert kept == {}
    assert outcome.rejected_backward == 1


def test_a_confident_backwards_edge_is_still_allowed() -> None:
    """A higher bar, not a ban. A book that genuinely forward-references -- "we
    will need the KKT theorem from chapter 5" -- must stay expressible, or this
    becomes the reading-order fallacy the module was built to replace."""
    order = positions("earlier", "later")
    kept = _select({("later", "earlier"): BACKWARD_MIN_CONFIDENCE}, order, PrereqOutcome(edges=[]))
    assert kept == {("later", "earlier"): BACKWARD_MIN_CONFIDENCE}


def test_an_edge_running_with_the_book_is_not_held_to_that_bar() -> None:
    order = positions("earlier", "later")
    outcome = PrereqOutcome(edges=[])
    kept = _select({("earlier", "later"): MIN_CONFIDENCE}, order, outcome)
    assert kept == {("earlier", "later"): MIN_CONFIDENCE}
    assert outcome.rejected_backward == 0

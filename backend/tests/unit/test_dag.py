"""Cycle rejection, topological layering, and transitive reduction.

These are the tests that matter most in the project: a subtle bug here silently
corrupts every skill tree the product will ever build, and it will look
plausible while doing so.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.dag import (
    CandidateEdge,
    CycleError,
    build_acyclic_edges,
    topological_depths,
    transitive_reduction,
)


def edge(prereq: str, target: str, confidence: float = 0.9, support: int = 1) -> CandidateEdge:
    return CandidateEdge(prereq=prereq, target=target, confidence=confidence, support=support)


def reasons(rejected) -> dict[tuple[str, str], str]:
    return {(r.prereq, r.target): r.reason for r in rejected}


# ── rejection cases ───────────────────────────────────────────────────────


def test_self_loop_is_rejected() -> None:
    accepted, rejected = build_acyclic_edges({"a"}, [edge("a", "a")])
    assert accepted == []
    assert reasons(rejected) == {("a", "a"): "self_loop"}


def test_two_cycle_keeps_the_confident_direction() -> None:
    slugs = {"limits", "derivatives"}
    candidates = [
        edge("limits", "derivatives", confidence=0.95),
        edge("derivatives", "limits", confidence=0.41),
    ]
    accepted, rejected = build_acyclic_edges(slugs, candidates)

    assert [(e.prereq, e.target) for e in accepted] == [("limits", "derivatives")]
    assert reasons(rejected) == {("derivatives", "limits"): "cycle"}


def test_three_cycle_is_broken_at_the_weakest_edge() -> None:
    slugs = {"a", "b", "c"}
    candidates = [
        edge("a", "b", confidence=0.9),
        edge("b", "c", confidence=0.8),
        edge("c", "a", confidence=0.6),
    ]
    accepted, rejected = build_acyclic_edges(slugs, candidates)

    assert len(accepted) == 2
    assert reasons(rejected) == {("c", "a"): "cycle"}
    topological_depths(slugs, accepted)  # must not raise


def test_rejected_cycle_records_the_actual_path() -> None:
    slugs = {"a", "b", "c"}
    candidates = [edge("a", "b", 0.9), edge("b", "c", 0.8), edge("c", "a", 0.6)]
    _, rejected = build_acyclic_edges(slugs, candidates)

    (offender,) = rejected
    # c -> a was refused because a already reaches c via a -> b -> c.
    assert offender.cycle_path == ("a", "b", "c")


def test_diamond_survives_intact() -> None:
    """A diamond is not a cycle. This is the case people get wrong."""
    slugs = {"a", "b", "c", "d"}
    candidates = [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")]
    accepted, rejected = build_acyclic_edges(slugs, candidates)

    assert len(accepted) == 4
    assert rejected == []


def test_duplicate_edges_are_rejected_once() -> None:
    slugs = {"a", "b"}
    accepted, rejected = build_acyclic_edges(slugs, [edge("a", "b", 0.9), edge("a", "b", 0.7)])

    assert len(accepted) == 1
    assert reasons(rejected) == {("a", "b"): "duplicate"}


def test_unknown_nodes_are_rejected() -> None:
    accepted, rejected = build_acyclic_edges({"a"}, [edge("a", "ghost")])
    assert accepted == []
    assert reasons(rejected) == {("a", "ghost"): "unknown_node"}


def test_low_confidence_edges_are_dropped() -> None:
    accepted, rejected = build_acyclic_edges({"a", "b"}, [edge("a", "b", confidence=0.2)], min_confidence=0.35)
    assert accepted == []
    assert reasons(rejected) == {("a", "b"): "low_confidence"}


def test_output_is_deterministic_across_input_orderings() -> None:
    """Re-ingesting an unchanged document must produce a byte-identical graph."""
    slugs = {"a", "b", "c", "d"}
    candidates = [edge("a", "b", 0.9), edge("b", "c", 0.9), edge("c", "a", 0.9), edge("a", "d", 0.5)]

    first, _ = build_acyclic_edges(slugs, candidates)
    second, _ = build_acyclic_edges(slugs, list(reversed(candidates)))

    assert first == second


# ── topological depth ─────────────────────────────────────────────────────


def test_topological_depths_layers_a_chain() -> None:
    slugs = {"a", "b", "c"}
    depths = topological_depths(slugs, [edge("a", "b"), edge("b", "c")])
    assert depths == {"a": 0, "b": 1, "c": 2}


def test_topological_depths_raises_on_a_cycle() -> None:
    slugs = {"a", "b"}
    with pytest.raises(CycleError):
        topological_depths(slugs, [edge("a", "b"), edge("b", "a")])


# ── transitive reduction ──────────────────────────────────────────────────


def test_transitive_reduction_drops_the_implied_shortcut() -> None:
    slugs = {"a", "b", "c"}
    edges = [edge("a", "b"), edge("b", "c"), edge("a", "c")]
    kept = {(e.prereq, e.target) for e in transitive_reduction(slugs, edges)}
    assert kept == {("a", "b"), ("b", "c")}


def test_transitive_reduction_preserves_a_diamond() -> None:
    slugs = {"a", "b", "c", "d"}
    edges = [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")]
    kept = {(e.prereq, e.target) for e in transitive_reduction(slugs, edges)}
    assert kept == {("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")}


def test_transitive_reduction_preserves_reachability() -> None:
    slugs = {"a", "b", "c", "d"}
    edges = [edge("a", "b"), edge("b", "c"), edge("c", "d"), edge("a", "d"), edge("a", "c")]
    kept = transitive_reduction(slugs, edges)
    depths = topological_depths(slugs, kept)
    assert depths["d"] == 3  # the long path survived; only shortcuts were dropped


# ── property: the accepted set is always a DAG ────────────────────────────


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from("abcdef"),
            st.sampled_from("abcdef"),
            st.floats(min_value=0.35, max_value=1.0, allow_nan=False),
        ),
        min_size=0,
        max_size=30,
    )
)
def test_accepted_edges_are_always_acyclic(raw: list[tuple[str, str, float]]) -> None:
    slugs = set("abcdef")
    candidates = [edge(p, t, c) for p, t, c in raw]
    accepted, _ = build_acyclic_edges(slugs, candidates)

    # Must not raise, no matter what the extractor threw at us.
    topological_depths(slugs, accepted)
    # And reduction of an acyclic set stays acyclic.
    topological_depths(slugs, transitive_reduction(slugs, accepted))


# @spec CURR-VERSION-009
def test_a_rejection_keeps_the_claim_it_rejected() -> None:
    """Two slugs and a reason code are not enough to review an overruled edge.

    The rationale is the extractor's argument for the edge. Dropping it on
    rejection leaves the one case where someone actually needs it -- deciding
    whether the compiler was right to overrule -- with the least information.
    """
    slugs = {"long-tones", "major-arpeggios", "simple-trumpet-melody"}
    claim = "The melody exercise is where long tones are actually used."
    candidates = [
        edge("long-tones", "major-arpeggios", 0.95),
        edge("major-arpeggios", "simple-trumpet-melody", 0.93),
        CandidateEdge("simple-trumpet-melody", "long-tones", 0.38, support=3, rationale=claim),
    ]

    _, rejected = build_acyclic_edges(slugs, candidates)

    (rejection,) = rejected
    assert rejection.reason == "cycle"
    assert rejection.rationale == claim
    assert rejection.support == 3
    assert rejection.confidence == 0.38

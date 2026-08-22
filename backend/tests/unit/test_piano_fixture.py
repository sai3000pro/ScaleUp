"""The first instrument curriculum stays deterministic and acyclic."""

from __future__ import annotations

from app.domain.dag import build_acyclic_edges, topological_depths
from app.piano_fixture import PIANO_CONCEPTS, PIANO_EDGES


def test_piano_fixture_has_unique_slugs_and_complete_edges() -> None:
    slugs = {concept.slug for concept in PIANO_CONCEPTS}
    edge_pairs = {(edge.prereq, edge.target) for edge in PIANO_EDGES}

    assert len(slugs) == len(PIANO_CONCEPTS)
    assert edge_pairs
    assert all(edge.prereq in slugs and edge.target in slugs for edge in PIANO_EDGES)
    assert all(concept.summary and concept.key_terms for concept in PIANO_CONCEPTS)


def test_piano_fixture_is_a_valid_prerequisite_dag() -> None:
    slugs = {concept.slug for concept in PIANO_CONCEPTS}
    accepted, rejected = build_acyclic_edges(slugs, list(PIANO_EDGES))

    assert len(accepted) == len(PIANO_EDGES)
    assert rejected == []

    depths = topological_depths(slugs, accepted)
    assert depths["keyboard-layout"] == 0
    assert depths["quarter-note-rhythm"] == 0
    assert depths["simple-chord-progression"] > depths["basic-triad"]
    assert depths["sight-reading-basics"] > depths["stepwise-melody"]

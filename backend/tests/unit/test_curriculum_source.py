"""A new instrument can start from source sections, not a Python DAG module."""

from __future__ import annotations

from app.curricula.source import SourceSection, compile_source_sections, load_source_sections
from app.domain.dag import build_acyclic_edges


def test_source_sections_generate_a_closed_dag_proposal() -> None:
    bundle = compile_source_sections(
        [
            SourceSection(
                slug="instrument-setup",
                title="Instrument Setup",
                summary="Hold the instrument safely.",
                text="Instrument setup establishes a balanced posture.",
            ),
            SourceSection(
                slug="bow-hold",
                title="Bow Hold",
                summary="Shape the hand around the bow.",
                text="Prerequisites: instrument-setup. Shape the hand around the bow.",
            ),
            SourceSection(
                slug="open-string-bow",
                title="Open-String Bow",
                summary="Draw a straight bow across an open string.",
                text="Prerequisites: bow-hold. Draw a straight bow across an open string.",
            ),
        ]
    )

    slugs = {concept.slug for concept in bundle.concepts}
    accepted, rejected = build_acyclic_edges(slugs, list(bundle.edges))

    assert {(edge.prereq, edge.target) for edge in accepted} == {
        ("instrument-setup", "bow-hold"),
        ("bow-hold", "open-string-bow"),
    }
    assert rejected == []
    assert bundle.evidence_quotes[("instrument-setup", "bow-hold")] == "Prerequisites: instrument-setup"


def test_violin_source_bundle_loads_and_generates_without_instrument_code() -> None:
    instrument, slug, title, sections = load_source_sections("violin-source")
    bundle = compile_source_sections(sections)

    assert instrument == "violin"
    assert slug == "violin-source-foundations"
    assert title == "Violin Foundations from Source"
    assert len(bundle.concepts) == 5
    assert ("open-string-bow", "simple-violin-melody") in {
        (edge.prereq, edge.target) for edge in bundle.edges
    }


def test_source_sections_ignore_edges_to_unknown_skills() -> None:
    bundle = compile_source_sections(
        [
            SourceSection(
                slug="first-note",
                title="First Note",
                summary="Produce a first note.",
                text="Prerequisites: missing-skill.",
            )
        ]
    )

    assert bundle.edges == ()
    assert bundle.evidence_quotes == {}

"""Instrument curricula are data inputs to one compiler."""

from __future__ import annotations

import pytest

from app.curricula.loader import (
    CurriculumDefinitionError,
    compile_curriculum,
    load_curriculum,
    parse_curriculum_payload,
)


@pytest.mark.parametrize("name", ["piano", "guitar", "violin"])
def test_packaged_instrument_curriculum_compiles_without_instrument_branches(name: str) -> None:
    definition = load_curriculum(name)
    compiled = compile_curriculum(definition)

    assert definition.instrument == name
    assert definition.version == 1
    assert compiled.accepted_edges
    assert compiled.rejected_edges == ()
    assert set(compiled.depths) == {concept.slug for concept in definition.concepts}
    assert len(compiled.reduced_edges) <= len(compiled.accepted_edges)


def test_a_new_curriculum_can_be_compiled_from_data_without_a_new_module() -> None:
    definition = parse_curriculum_payload(
        {
            "instrument": "flute",
            "slug": "flute-foundations",
            "version": 1,
            "title": "Flute Foundations",
            "concepts": [
                {
                    "slug": "breath",
                    "title": "Breath",
                    "summary": "Support a steady stream of air.",
                    "difficulty": 1,
                    "key_terms": ["air"],
                },
                {
                    "slug": "first-note",
                    "title": "First Note",
                    "summary": "Produce a stable first note.",
                    "difficulty": 2,
                    "key_terms": ["tone"],
                },
            ],
            "edges": [
                {"prereq": "breath", "target": "first-note", "confidence": 0.9},
            ],
        }
    )

    compiled = compile_curriculum(definition)

    assert compiled.depths == {"breath": 0, "first-note": 1}


def test_invalid_curriculum_references_are_rejected_before_dag_building() -> None:
    with pytest.raises(CurriculumDefinitionError, match="does not exist"):
        parse_curriculum_payload(
            {
                "instrument": "guitar",
                "slug": "broken",
                "version": 1,
                "title": "Broken",
                "concepts": [
                    {
                        "slug": "one",
                        "title": "One",
                        "summary": "One.",
                        "difficulty": 1,
                        "key_terms": [],
                    }
                ],
                "edges": [{"prereq": "ghost", "target": "one"}],
            }
        )

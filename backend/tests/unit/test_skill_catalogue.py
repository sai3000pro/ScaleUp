"""The shared skill catalogue: one definition per skill, narrow specialisation.

Instruments overlap far more than they differ. These tests pin the two halves of
that: a catalogue skill is defined once and inherited whole, and an instrument
may restate only a fixed, declared set of fields -- because an open override
surface turns a catalogue back into one standalone curriculum per instrument
wearing a shared name.
"""

from __future__ import annotations

import pytest

from app.curricula.loader import (
    OVERRIDABLE_FIELDS,
    CurriculumDefinitionError,
    compile_curriculum,
    load_catalogue,
    load_curriculum,
    parse_curriculum_payload,
)

INSTRUMENTS = ("piano", "guitar", "violin", "trumpet", "drums", "banjo")


def _payload(concepts: list[dict], edges: list[dict] | None = None) -> dict:
    return {
        "instrument": "testinstrument",
        "slug": "testinstrument",
        "version": 1,
        "title": "Test Instrument",
        "concepts": concepts,
        "edges": edges or [],
    }


# @spec CURR-CAT-001
def test_the_catalogue_defines_each_skill_once_under_a_stable_id() -> None:
    catalogue = load_catalogue()
    assert catalogue, "the catalogue must not be empty"
    for skill_id, skill in catalogue.items():
        assert skill.id == skill_id
        assert skill.title.strip()
        assert skill.summary.strip()
        assert 1 <= skill.difficulty <= 5


# @spec CURR-CAT-002, CURR-CAT-003
def test_a_concept_drawn_from_the_catalogue_inherits_the_shared_definition() -> None:
    catalogue = load_catalogue()
    skill = catalogue["strumming"]

    definition = parse_curriculum_payload(
        _payload([{"from": "strumming", "slug": "banjo-strumming"}]),
        catalogue=catalogue,
    )

    concept = definition.concepts[0]
    assert concept.slug == "banjo-strumming"
    assert concept.title == skill.title
    assert concept.summary == skill.summary
    assert concept.difficulty == skill.difficulty
    assert concept.key_terms == skill.key_terms


# @spec CURR-CAT-004
def test_an_instrument_may_restate_the_declared_fields() -> None:
    catalogue = load_catalogue()

    definition = parse_curriculum_payload(
        _payload(
            [
                {
                    "from": "instrument-orientation",
                    "slug": "banjo-orientation",
                    "title": "Banjo Orientation",
                    "summary": "Identify the head, bridge, neck, and the short fifth string.",
                    "difficulty": 2,
                    "key_terms": ["head", "fifth string"],
                }
            ]
        ),
        catalogue=catalogue,
    )

    concept = definition.concepts[0]
    assert concept.title == "Banjo Orientation"
    assert concept.summary.startswith("Identify the head")
    assert concept.difficulty == 2
    assert concept.key_terms == ("head", "fifth string")
    # The link to the shared skill survives the restatement.
    assert concept.catalogue_id == "instrument-orientation"


# @spec CURR-CAT-005
def test_an_override_outside_the_declared_set_is_refused() -> None:
    catalogue = load_catalogue()

    with pytest.raises(CurriculumDefinitionError) as excinfo:
        parse_curriculum_payload(
            _payload([{"from": "strumming", "slug": "banjo-strumming", "evaluator": "guitar-chords-v1"}]),
            catalogue=catalogue,
        )

    message = str(excinfo.value)
    assert "evaluator" in message
    # The refusal names what IS permitted, so the author can act on it.
    for field in OVERRIDABLE_FIELDS:
        assert field in message


# @spec CURR-CAT-006
def test_an_unknown_catalogue_skill_is_refused_and_the_known_ones_are_listed() -> None:
    catalogue = load_catalogue()

    with pytest.raises(CurriculumDefinitionError) as excinfo:
        parse_curriculum_payload(
            _payload([{"from": "sturmming", "slug": "banjo-strumming"}]),
            catalogue=catalogue,
        )

    message = str(excinfo.value)
    assert "sturmming" in message
    assert "strumming" in message, "a typo should be recoverable from the error"


# @spec CURR-CAT-007, CURR-CAT-008
def test_an_inline_concept_is_unaffected_by_the_catalogue() -> None:
    definition = parse_curriculum_payload(
        _payload(
            [
                {
                    "slug": "open-g-tuning",
                    "title": "Open G Tuning",
                    "summary": "Tune the five strings to open G.",
                    "difficulty": 1,
                    "key_terms": ["tuning"],
                }
            ]
        ),
        catalogue=load_catalogue(),
    )

    concept = definition.concepts[0]
    assert concept.catalogue_id is None
    assert concept.title == "Open G Tuning"


# @spec CURR-CAT-009
def test_prerequisite_edges_are_owned_by_the_instrument_not_the_catalogue() -> None:
    """What must come before what is a claim about one instrument."""
    catalogue = load_catalogue()
    payload = _payload(
        [
            {"from": "steady-pulse", "slug": "pulse"},
            {"from": "strumming", "slug": "strum"},
        ],
        edges=[{"prereq": "pulse", "target": "strum", "confidence": 0.9, "rationale": "Pulse precedes pattern."}],
    )

    definition = parse_curriculum_payload(payload, catalogue=catalogue)

    assert len(definition.edges) == 1
    assert (definition.edges[0].prereq, definition.edges[0].target) == ("pulse", "strum")


# @spec CURR-CAT-010
def test_two_instruments_realising_one_skill_are_identifiable_as_the_same_skill() -> None:
    guitar = {c.catalogue_id for c in load_curriculum("guitar").concepts if c.catalogue_id}
    banjo = {c.catalogue_id for c in load_curriculum("banjo").concepts if c.catalogue_id}

    shared = guitar & banjo
    assert "strumming" in shared, "guitar and banjo both strum, and the system should know it"


@pytest.mark.parametrize("instrument", INSTRUMENTS)
# @spec CURR-CAT-002, CURR-CAT-009
def test_every_shipped_curriculum_still_compiles(instrument: str) -> None:
    definition = load_curriculum(instrument)
    compiled = compile_curriculum(definition)

    assert definition.concepts
    assert compiled.accepted_edges
    # Every declared edge names concepts the curriculum actually defines.
    slugs = {concept.slug for concept in definition.concepts}
    for edge in definition.edges:
        assert edge.prereq in slugs
        assert edge.target in slugs


# @spec CURR-CAT-011
def test_the_catalogue_is_realised_by_at_least_one_instrument() -> None:
    """A skill nobody can play is a taxonomy entry, not a curriculum skill."""
    catalogue = load_catalogue()
    realised: set[str] = set()
    for instrument in INSTRUMENTS:
        realised.update(c.catalogue_id for c in load_curriculum(instrument).concepts if c.catalogue_id)

    orphans = sorted(set(catalogue) - realised)
    assert not orphans, f"catalogue skills no instrument realises: {orphans}"

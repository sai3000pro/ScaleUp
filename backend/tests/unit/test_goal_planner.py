"""A learner's sentence becomes a tree, and the catalogue is what makes it one.

The planner is pure: goal text in, a `CurriculumDefinition` out, with no session,
no provider and no clock. That is what lets the two things worth asserting be
asserted cheaply -- that the deterministic floor produces a real tree for any
goal, and that a model's proposal is checked before anything is written.

The distinction the file turns on is between *selecting* from the catalogue and
*inventing* a syllabus. A plan that names catalogue skills produces concepts
carrying catalogue identity, so the same skill on two instruments is the same
entity. A plan that names something else is refused rather than repaired.
"""

from __future__ import annotations

import pytest

from app.curricula.loader import OVERRIDABLE_FIELDS, load_catalogue, load_curriculum
from app.curricula.planner import (
    MAX_CONCEPTS,
    MIN_CONCEPTS,
    PlanValidationError,
    assemble,
    catalogue_prompt_payload,
    definition_from_plan,
    known_instruments,
    resolve_instrument,
)

CATALOGUE = load_catalogue()


def _plan(concepts: list[dict], edges: list[dict] | None = None) -> dict:
    return {"instrument": "cello", "instrument_title": "Cello", "concepts": concepts, "edges": edges or []}


def _spine_plan(count: int) -> dict:
    """A plan of `count` catalogue-drawn concepts, all valid."""
    ids = list(CATALOGUE)
    picked = [ids[i % len(ids)] for i in range(count)]
    return _plan([{"from": skill, "slug": f"cello-{index}"} for index, skill in enumerate(picked)])


# ── reading the instrument out of the sentence ────────────────────────────


# @spec CURR-GOAL-003
@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("I want to learn how to play Guitar", "guitar"),
        ("i want to learn guitar", "guitar"),
        ("teach me the PIANO please", "piano"),
        ("I'd like to get good at the drums", "drums"),
        ("learn cello", "cello"),
        ("I want to play the saxophone in a band", "saxophone"),
    ],
)
def test_the_instrument_is_read_from_the_learners_own_words(goal: str, expected: str) -> None:
    assert resolve_instrument(goal) == expected


# @spec CURR-GOAL-003
@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("I want to learn the fiddle", "violin"),
        ("teach me keys", "piano"),
        ("I want to play the drum kit", "drums"),
    ],
)
def test_an_instrument_called_by_another_name_still_resolves(goal: str, expected: str) -> None:
    """A learner says "fiddle"; the curriculum is filed under "violin"."""
    assert resolve_instrument(goal) == expected


# @spec CURR-GOAL-005
@pytest.mark.parametrize("goal", ["", "   ", "asdfgh", "I want to get better at things", "learn to cook"])
def test_a_goal_naming_no_instrument_resolves_to_nothing(goal: str) -> None:
    assert resolve_instrument(goal) is None


# ── the deterministic floor ───────────────────────────────────────────────


# @spec CURR-GOAL-004
@pytest.mark.parametrize("instrument", sorted(known_instruments()))
def test_a_shipped_instrument_assembles_to_its_own_published_curriculum(instrument: str) -> None:
    """Where the project already authored the answer, no model is asked for one."""
    assembled = assemble(instrument)
    shipped = load_curriculum(instrument)

    assert assembled.instrument == shipped.instrument
    assert [c.slug for c in assembled.concepts] == [c.slug for c in shipped.concepts]
    assert [(e.prereq, e.target) for e in assembled.edges] == [(e.prereq, e.target) for e in shipped.edges]


# @spec CURR-GOAL-006
def test_an_instrument_nothing_covers_still_gets_a_tree_from_the_catalogue() -> None:
    """No provider, no curriculum, and the learner still gets a playable spine."""
    definition = assemble("cello")

    assert definition.instrument == "cello"
    assert len(definition.concepts) >= MIN_CONCEPTS
    # Every concept is a real catalogue skill, not an invention.
    assert all(concept.catalogue_id in CATALOGUE for concept in definition.concepts)


# @spec CURR-GOAL-006, CURR-GOAL-015
def test_the_spine_arrives_ordered_rather_than_as_a_pile_of_nodes() -> None:
    """A tree with nodes and no edges is a list. The catalogue supplies the order."""
    definition = assemble("cello")
    slugs = {concept.slug for concept in definition.concepts}

    assert definition.edges, "the catalogue's suggested ordering should seed the spine"
    for edge in definition.edges:
        assert edge.prereq in slugs
        assert edge.target in slugs


# @spec CURR-GOAL-015
def test_the_catalogue_declares_an_ordering_between_its_own_skills() -> None:
    from app.curricula.loader import load_catalogue_edges

    edges = load_catalogue_edges()
    assert edges, "the catalogue should carry suggested prerequisite edges"
    for edge in edges:
        assert edge.prereq in CATALOGUE
        assert edge.target in CATALOGUE
        assert edge.prereq != edge.target


# ── what the model is handed ──────────────────────────────────────────────


# @spec CURR-GOAL-002
def test_the_whole_catalogue_is_offered_to_the_planner_as_a_closed_vocabulary() -> None:
    payload = catalogue_prompt_payload()

    for skill_id, skill in CATALOGUE.items():
        assert skill_id in payload, f"{skill_id} must be selectable"
        assert skill.title in payload
    # The ordering is a prior worth telling the planner about.
    assert "steady-pulse" in payload


# ── a proposal is checked before anything is written ──────────────────────


# @spec CURR-GOAL-007
def test_a_plan_naming_a_skill_the_catalogue_does_not_have_is_refused() -> None:
    plan = _spine_plan(MIN_CONCEPTS)
    plan["concepts"][0] = {"from": "sturmming", "slug": "cello-strum"}

    with pytest.raises(PlanValidationError) as excinfo:
        definition_from_plan(plan, instrument="cello")

    assert "sturmming" in str(excinfo.value)


# @spec CURR-GOAL-008
def test_a_plan_overriding_a_field_outside_the_declared_set_is_refused() -> None:
    plan = _spine_plan(MIN_CONCEPTS)
    plan["concepts"][0]["evaluator"] = "guitar-chords-v1"

    with pytest.raises(PlanValidationError) as excinfo:
        definition_from_plan(plan, instrument="cello")

    message = str(excinfo.value)
    assert "evaluator" in message
    for field in OVERRIDABLE_FIELDS:
        assert field in message, "the refusal should name what IS permitted"


# @spec CURR-GOAL-009
def test_a_plan_with_two_concepts_sharing_a_slug_is_refused() -> None:
    plan = _plan(
        [
            {"from": "steady-pulse", "slug": "cello-pulse"},
            {"from": "sustained-tone", "slug": "cello-pulse"},
            {"from": "first-melody", "slug": "cello-tune"},
            {"from": "tempo-control", "slug": "cello-tempo"},
        ]
    )

    with pytest.raises(PlanValidationError, match="cello-pulse"):
        definition_from_plan(plan, instrument="cello")


# @spec CURR-GOAL-009
def test_a_plan_whose_edge_names_a_concept_it_never_defined_is_refused() -> None:
    plan = _spine_plan(MIN_CONCEPTS)
    plan["edges"] = [{"prereq": "cello-0", "target": "not-a-concept", "confidence": 0.9}]

    with pytest.raises(PlanValidationError, match="not-a-concept"):
        definition_from_plan(plan, instrument="cello")


# @spec CURR-GOAL-010
def test_a_plan_smaller_than_a_curriculum_is_refused() -> None:
    with pytest.raises(PlanValidationError):
        definition_from_plan(_spine_plan(MIN_CONCEPTS - 1), instrument="cello")


# @spec CURR-GOAL-010
def test_a_plan_larger_than_a_learner_can_face_is_refused() -> None:
    with pytest.raises(PlanValidationError):
        definition_from_plan(_spine_plan(MAX_CONCEPTS + 1), instrument="cello")


# ── what a valid plan produces ────────────────────────────────────────────


# @spec CURR-GOAL-014
def test_a_catalogue_drawn_concept_keeps_catalogue_identity() -> None:
    """The property that makes two instruments share a skill rather than a word."""
    plan = _plan(
        [
            {"from": "instrument-orientation", "slug": "cello-orientation"},
            {"from": "steady-pulse", "slug": "cello-pulse"},
            {"from": "sustained-tone", "slug": "cello-tone", "title": "Drawing a Long Bow"},
            {"from": "first-melody", "slug": "cello-tune"},
        ],
        edges=[{"prereq": "cello-orientation", "target": "cello-pulse", "confidence": 0.9}],
    )

    definition = definition_from_plan(plan, instrument="cello")

    by_slug = {c.slug: c for c in definition.concepts}
    assert by_slug["cello-orientation"].catalogue_id == "instrument-orientation"
    # An override restates wording; it does not sever identity.
    assert by_slug["cello-tone"].catalogue_id == "sustained-tone"
    assert by_slug["cello-tone"].title == "Drawing a Long Bow"
    assert by_slug["cello-tone"].summary == CATALOGUE["sustained-tone"].summary


# @spec CURR-GOAL-014
def test_a_concept_particular_to_the_instrument_needs_no_catalogue_entry() -> None:
    plan = _plan(
        [
            {"from": "instrument-orientation", "slug": "cello-orientation"},
            {"from": "steady-pulse", "slug": "cello-pulse"},
            {"from": "first-melody", "slug": "cello-tune"},
            {
                "slug": "thumb-position",
                "title": "Thumb Position",
                "summary": "Play above the neck with the thumb stopping the string.",
                "difficulty": 5,
                "key_terms": ["thumb position"],
            },
        ]
    )

    definition = definition_from_plan(plan, instrument="cello")

    thumb = next(c for c in definition.concepts if c.slug == "thumb-position")
    assert thumb.catalogue_id is None
    assert thumb.difficulty == 5


# @spec CURR-GOAL-001
def test_a_planned_definition_compiles_like_any_other_curriculum() -> None:
    """Goal-first output is the same shape every other construction path emits."""
    from app.curricula.loader import compile_curriculum

    definition = definition_from_plan(_spine_plan(6), instrument="cello")
    compiled = compile_curriculum(definition)

    assert compiled.definition.concepts
    assert compiled.depths

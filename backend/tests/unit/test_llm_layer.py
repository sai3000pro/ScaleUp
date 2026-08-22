"""Prompt registry, schema validation, and the FakeProvider."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from app.ingestion.prereqs import SkillRef, _render_skill_list
from app.llm.base import LLMRole, SchemaValidationError
from app.llm.fake_provider import FakeEmbeddingProvider, FakeLLMClient
from app.llm.registry import PRICES, ROLES, price_for
from app.llm.support import parse_json_or_raise, prepare, validate_or_raise
from app.prompts.registry import available_prompts, load_prompt, load_schema
from app.services.drill_service import _grade_mcq, _render_rubric

CHUNKS = """
[0] A vector is an ordered list of numbers. Vectors add componentwise and scale by a real number.
[1] The dot product multiplies matching components and sums them, producing a single number.
    The dot product is zero exactly when two vectors are perpendicular.
"""


# ── prompt registry ───────────────────────────────────────────────────────


# @spec LLM-PROMPT-003
def test_every_prompt_on_disk_loads_and_hashes() -> None:
    prompts = available_prompts()
    assert prompts, "no prompts found"
    for prompt_id, version in prompts:
        prompt = load_prompt(prompt_id, version)
        assert prompt.text.strip()
        assert len(prompt.sha256) == 64


def test_hashing_is_stable_across_calls() -> None:
    assert load_prompt("grade", "v1").sha256 == load_prompt("grade", "v1").sha256


def test_render_substitutes_every_placeholder() -> None:
    rendered = load_prompt("graph_extract", "v1").render(
        {"book_title": "Linear Algebra", "section_path": "1 / 1.1", "chunks": CHUNKS}
    )
    assert "{{" not in rendered
    assert "Linear Algebra" in rendered


def test_render_refuses_to_leave_a_placeholder_unfilled() -> None:
    """A silently unsubstituted `{{answer}}` would be sent to the model verbatim."""
    with pytest.raises(KeyError, match="unsubstituted"):
        load_prompt("grade", "v1").render({"question": "q"})


# @spec LLM-ROLE-002, LLM-PROMPT-001
def test_every_role_points_at_a_prompt_and_schema_that_exist() -> None:
    for role, config in ROLES.items():
        assert load_prompt(config.prompt_id, config.prompt_version).text
        assert load_schema(config.schema_id, config.schema_version)["type"] == "object", role


def test_every_configured_model_has_a_price() -> None:
    """An unpriced model silently reports a zero-cost ingest."""
    for config in ROLES.values():
        assert config.anthropic_model in PRICES
        assert config.openai_model in PRICES


def test_price_scales_with_tokens() -> None:
    assert price_for("claude-haiku-4-5", 1_000_000, 0) == PRICES["claude-haiku-4-5"][0]
    assert price_for("fake", 999_999, 999_999) == 0


# ── schema validation ─────────────────────────────────────────────────────


def test_validation_rejects_a_bad_slug() -> None:
    schema = load_schema("concept_map", "v1")
    bad = {"concepts": [{"slug": "Not A Slug", "title": "X", "summary": "y" * 30, "difficulty": 2,
                         "assessable": True}], "prerequisites": []}
    with pytest.raises(SchemaValidationError):
        validate_or_raise(bad, schema)


def test_validation_rejects_unknown_fields() -> None:
    schema = load_schema("grade", "v1")
    payload = {
        "score": 0.5, "verdict": "partial", "feedback": "some feedback here",
        "points_hit": [], "points_missed": ["kp1"], "smuggled": True,
    }
    with pytest.raises(SchemaValidationError):
        validate_or_raise(payload, schema)


def test_fenced_json_is_tolerated() -> None:
    assert parse_json_or_raise('```json\n{"a": 1}\n```') == {"a": 1}


def test_non_json_raises_a_typed_error() -> None:
    with pytest.raises(SchemaValidationError):
        parse_json_or_raise("Sure! Here is your answer:")


def test_fingerprint_changes_with_input_but_not_between_identical_calls() -> None:
    a = prepare(LLMRole.GRADE, {"question": "q", "rubric": "kp1 x", "context": "c", "answer": "a"}, "m")
    b = prepare(LLMRole.GRADE, {"question": "q", "rubric": "kp1 x", "context": "c", "answer": "a"}, "m")
    c = prepare(LLMRole.GRADE, {"question": "q", "rubric": "kp1 x", "context": "c", "answer": "different"}, "m")
    assert a.request_fingerprint == b.request_fingerprint
    assert a.request_fingerprint != c.request_fingerprint


# ── fake LLM ──────────────────────────────────────────────────────────────


# @spec LLM-FAKE-004
async def test_fake_extraction_is_schema_valid_and_has_structure() -> None:
    result = await FakeLLMClient().structured(
        LLMRole.GRAPH_EXTRACT_MAP,
        {"book_title": "LA", "section_path": "1 / 1.1", "chunks": CHUNKS},
    )
    concepts = result.data["concepts"]
    assert concepts, "fake must produce a usable graph, not an empty one"
    assert len({c["slug"] for c in concepts}) == len(concepts)
    # Chained, so a fake ingest yields depth rather than a row of orphans.
    assert len(result.data["prerequisites"]) == len(concepts) - 1


# @spec LLM-FAKE-003, LLM-FAKE-006
async def test_fake_is_deterministic() -> None:
    variables = {"book_title": "LA", "section_path": "1", "chunks": CHUNKS}
    first = await FakeLLMClient().structured(LLMRole.GRAPH_EXTRACT_MAP, variables)
    second = await FakeLLMClient().structured(LLMRole.GRAPH_EXTRACT_MAP, variables)
    assert first.data == second.data


async def test_fake_mcq_has_four_options_and_one_correct_answer() -> None:
    result = await FakeLLMClient().structured(
        LLMRole.QUESTION_GEN,
        {
            "node_title": "Dot Product",
            "node_summary": "Multiply matching components and sum them.",
            "context": CHUNKS,
            "requested_type": "mcq",
        },
    )
    assert result.data["question_type"] == "mcq"
    assert len(result.data["options"]) == 4
    assert len({option["id"] for option in result.data["options"]}) == 4
    assert result.data["correct_option_id"] in {option["id"] for option in result.data["options"]}


async def test_fake_question_rubric_weights_sum_to_one() -> None:
    result = await FakeLLMClient().structured(
        LLMRole.QUESTION_GEN,
        {"node_title": "Dot Product", "node_summary": "Multiply matching components and sum.", "context": CHUNKS},
    )
    assert abs(sum(point["weight"] for point in result.data["rubric"]) - 1.0) < 1e-6


def test_mcq_grading_compares_option_ids_and_exposes_feedback() -> None:
    question = SimpleNamespace(
        correct_option_id="option-b",
        options=[
            {"id": "option-a", "text": "Wrong"},
            {"id": "option-b", "text": "Right"},
        ],
        rubric=[{"id": "kp1", "point": "The key idea", "weight": 1.0}],
    )
    correct = _grade_mcq(question, " OPTION-B ")
    incorrect = _grade_mcq(question, "option-a")

    assert correct["score"] == 1.0
    assert correct["points_hit"] == ["kp1"]
    assert incorrect["score"] == 0.0
    assert incorrect["points_missed"] == ["kp1"]
    assert "Right" in str(incorrect["feedback"])


async def test_fake_grader_is_monotonic_in_answer_quality() -> None:
    """Without this the entire drill / EXP / SRS loop is untestable."""
    rubric = "kp1: Explains that the dot product multiplies matching components and sums them.\n" \
             "kp2: Explains that a zero dot product means the vectors are perpendicular."
    base = {"question": "Explain the dot product.", "rubric": rubric, "context": CHUNKS}
    client = FakeLLMClient()

    good = await client.structured(
        LLMRole.GRADE,
        {**base, "answer": "It multiplies matching components and sums them; zero means perpendicular vectors."},
    )
    poor = await client.structured(LLMRole.GRADE, {**base, "answer": "It multiplies components somehow."})
    junk = await client.structured(LLMRole.GRADE, {**base, "answer": "banana banana banana"})

    assert good.data["score"] > poor.data["score"] >= junk.data["score"]
    assert junk.data["score"] == 0.0
    assert good.data["verdict"] == "correct"
    assert junk.data["verdict"] == "incorrect"


async def test_fake_grader_names_what_was_missed() -> None:
    rubric = "kp1: Explains componentwise multiplication.\nkp2: Explains perpendicularity."
    result = await FakeLLMClient().structured(
        LLMRole.GRADE,
        {"question": "q", "rubric": rubric, "context": "", "answer": "banana"},
    )
    assert set(result.data["points_missed"]) == {"kp1", "kp2"}


async def test_a_generated_rubric_is_answerable_by_a_human() -> None:
    """The seam the other grader tests miss.

    Every test above hands the grader a *hand-written* rubric. The drill loop
    hands it a rubric `_question` generated and `_render_rubric` formatted, and
    for a while that combination was unpassable: the template's own framing
    ("Explains the role of...") and the "(weight N)" suffix were counted as
    required content, so a correct paraphrase covered one word in five and
    scored zero. Feeding the rubric text back verbatim -- which is what the
    integration tests do -- hid it completely.

    Use a single-word title and an answer that says "vector" where the rubric
    says "Vectors" -- the exact shape that failed. A two-word title such as
    "Dot Product" accidentally passes even the broken grader, because the answer
    naturally repeats both title words.
    """
    client = FakeLLMClient()
    question = await client.structured(
        LLMRole.QUESTION_GEN,
        {
            "node_title": "Vectors",
            "node_summary": "Represent a quantity with both magnitude and direction as an ordered list.",
            "context": CHUNKS,
        },
    )
    rubric = _render_rubric(question.data["rubric"])

    # No rubric point may be about the node's own title, or it asserts nothing.
    assert not any("of vectors in" in point["point"].lower() for point in question.data["rubric"]), rubric

    graded = await client.structured(
        LLMRole.GRADE,
        {
            "question": question.data["question"],
            "rubric": rubric,
            "context": CHUNKS,
            "answer": "A vector is a quantity with both magnitude and direction, written as an ordered list of numbers.",
        },
    )
    assert graded.data["verdict"] == "correct", (rubric, graded.data)
    # Point ids are internal. They must never reach the learner.
    assert "kp1" not in graded.data["feedback"]


# ── the fake's prerequisite matching ──────────────────────────────────────
#
# The old rule was "the section prints the other skill's title verbatim", and
# real prose never does -- it writes "since A_B is invertible", not "Inverse of a
# Matrix". A fake that can only see titles under-fires on exactly the
# foundational skills, so the measured recall of the edge-inference stage was
# partly the fake's ceiling rather than the design's. These tests pin the
# behaviour that fixed it, and the honesty constraints that keep it a stand-in
# for a reader rather than an edge generator.

# Rendered by the SHIPPING renderer, never hand-written. Spelling the wire
# format out here is what let it drift: `prereqs` wrote `Title: summary`, the
# fake read back everything before the first colon, and a title that contained
# one was silently truncated to its first word with no test noticing.
SKILL_LIST = _render_skill_list(
    [
        SkillRef(
            "inverse-of-a-matrix",
            "Inverse of a Matrix",
            "If an n x n matrix A is invertible we call B the inverse.",
        ),
        SkillRef(
            "bipartite-graphs",
            "Bipartite Graphs",
            "A graph whose vertices split into two independent sets.",
        ),
        SkillRef(
            "photosynthesis",
            "Photosynthesis",
            "Plants convert light into chemical energy in chloroplasts.",
        ),
    ]
)
BASIS_TEXT = (
    "Let B be a subset of column indices. B is a basis if the matrix A_B is invertible. "
    "Since the matrix A_B is invertible, multiplying by its inverse on both sides gives the basic solution. "
    "Not every set of columns is a basis: consider the all-zero case, where every choice is singular."
)
DUAL_TEXT = (
    "The dual of a minimisation problem is a maximisation problem. Weak duality bounds the primal "
    "objective below by every feasible dual solution, and the bound is attained at optimality."
)


async def prereq_edges(section_text: str, section_slug: str = "basis") -> list[dict]:
    result = await FakeLLMClient().structured(
        LLMRole.PREREQ_INFER,
        {
            "book_title": "Optimization",
            "skill_list": SKILL_LIST,
            "section_title": "Basis",
            "section_slug": section_slug,
            "section_text": section_text,
        },
    )
    return result.data["edges"]


async def test_the_fake_recognises_a_skill_that_is_never_named_by_title() -> None:
    """"since A_B is invertible" is how a book actually cites matrix inverses."""
    edges = await prereq_edges(BASIS_TEXT)
    assert "inverse-of-a-matrix" in {e["prereq_slug"] for e in edges}


async def test_the_fake_does_not_fire_on_unrelated_prose() -> None:
    """The point of a fake is to be honest about absence. If it fabricated an
    edge here, every recall number measured against it would be flattering."""
    assert await prereq_edges("Chloroplasts absorb light. The stroma hosts the Calvin cycle.") == []


async def test_the_fake_quotes_the_section_it_read() -> None:
    edges = await prereq_edges(BASIS_TEXT)
    normalized = " ".join(BASIS_TEXT.split()).lower()
    assert edges and all(e["evidence"] in normalized for e in edges)


async def test_the_fake_is_deterministic_across_both_prerequisite_roles() -> None:
    """Tests must never flake on a re-run."""
    assert await prereq_edges(BASIS_TEXT) == await prereq_edges(BASIS_TEXT)
    assert await fake_dependents() == await fake_dependents()


async def fake_dependents() -> list[dict]:
    result = await FakeLLMClient().structured(
        LLMRole.PREREQ_DEPENDENTS,
        {
            "book_title": "Optimization",
            "source_slug": "inverse-of-a-matrix",
            "source_title": "Inverse of a Matrix",
            "source_text": (
                "If an n x n matrix A is invertible we refer to the matrix B with AB = I as the inverse of A. "
                "The inverse satisfies A A^-1 = I. A matrix is invertible exactly when its determinant is nonzero."
            ),
            "candidates": (
                f"### `basis` — Basis\n{BASIS_TEXT}\n\n"
                f"### `weak-duality` — Weak Duality\n{DUAL_TEXT}\n\n"
                "### `photosynthesis` — Photosynthesis\n"
                "Chloroplasts absorb light. The stroma hosts the Calvin cycle and fixes carbon."
            ),
        },
    )
    return result.data["dependents"]


async def test_the_reverse_fake_names_the_candidate_that_uses_the_source() -> None:
    dependents = await fake_dependents()
    assert {d["target_slug"] for d in dependents} == {"basis"}


async def test_only_the_reverse_role_can_see_a_dependency_stated_in_other_words() -> None:
    """The asymmetry the reverse role exists for, in one test.

    This passage relies on matrix inverses and never says so near the word
    "matrix": it says "invertible" and "nonsingular". The forward prompt
    describes each skill with its title and ~110 characters of summary, which is
    not enough to know those are the words that matter, nor enough to tell them
    from vocabulary the whole book shares. The reverse prompt carries the
    skill's whole defining passage and the other candidates' prose, so both of
    those become measurable.
    """
    oblique = (
        "A subset B of the column indices is a basis when A_B is invertible. Because A_B is invertible "
        "we may multiply through on both sides, and a nonsingular choice makes the solution unique."
    )
    assert await prereq_edges(oblique) == []

    result = await FakeLLMClient().structured(
        LLMRole.PREREQ_DEPENDENTS,
        {
            "book_title": "Optimization",
            "source_slug": "inverse-of-a-matrix",
            "source_title": "Inverse of a Matrix",
            "source_text": (
                "A is invertible, or nonsingular, when there is a B with AB = I. "
                "The inverse satisfies A A^-1 = I, and a nonsingular A has exactly one inverse."
            ),
            "candidates": (
                f"### `basis` — Basis\n{oblique}\n\n"
                f"### `weak-duality` — Weak Duality\n{DUAL_TEXT}\n\n"
                "### `photosynthesis` — Photosynthesis\nChloroplasts absorb light in the stroma."
            ),
        },
    )
    assert {d["target_slug"] for d in result.data["dependents"]} == {"basis"}


async def test_the_reverse_fake_quotes_the_candidate_not_the_source() -> None:
    """The prompt demands evidence from the accused section's own excerpt. A
    quotation lifted from the source would prove nothing about the candidate."""
    dependents = await fake_dependents()
    candidate = " ".join(BASIS_TEXT.split()).lower()
    assert dependents and all(d["evidence"] in candidate for d in dependents)


# ── fake embeddings ───────────────────────────────────────────────────────


# @spec LLM-EMBED-004
async def test_fake_embeddings_are_unit_length_and_correctly_sized() -> None:
    provider = FakeEmbeddingProvider(dimensions=256)
    vectors = await provider.embed(["alpha beta", "gamma delta"])
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == 256
        assert abs(math.sqrt(sum(v * v for v in vector)) - 1.0) < 1e-9


async def test_fake_embeddings_are_deterministic() -> None:
    provider = FakeEmbeddingProvider(dimensions=128)
    assert await provider.embed(["same text"]) == await provider.embed(["same text"])


# @spec LLM-EMBED-002
async def test_fake_embeddings_put_shared_vocabulary_closer() -> None:
    """Directionally sane, so merge-by-similarity code is exercised meaningfully."""
    provider = FakeEmbeddingProvider(dimensions=512)
    a, b, c = await provider.embed(
        ["matrix multiplication rows columns", "matrix multiplication columns rows", "photosynthesis chlorophyll"]
    )
    related = sum(x * y for x, y in zip(a, b))
    unrelated = sum(x * y for x, y in zip(a, c))
    assert related > unrelated


async def test_embedding_empty_batch_is_a_noop() -> None:
    assert await FakeEmbeddingProvider().embed([]) == []


# ── fake performance feedback ─────────────────────────────────────────────


async def test_fake_performance_feedback_echoes_the_deterministic_floor() -> None:
    """The fake has nothing to add to coaching prose, so it returns the
    deterministic floor verbatim -- the merge path and schema contract still run
    for real, and the wording stays coherent."""
    from app.evaluation.feedback import generate_feedback
    from app.evaluation.musicxml import parse_musicxml
    from app.evaluation.piano import PerformedNote, score_performance
    from app.evaluation.reference_scores import PIANO_STEPWISE_SCORE_XML
    from app.services.performance_service import _feedback_block

    result = score_performance(
        parse_musicxml(PIANO_STEPWISE_SCORE_XML),
        [PerformedNote(60, 0.0), PerformedNote(62, 0.5), PerformedNote(64, 1.0), PerformedNote(65, 1.5)],
    )
    deterministic = generate_feedback(result, exercise_title="Stepwise C Major", instrument="piano")

    first = await FakeLLMClient().structured(
        LLMRole.PERFORMANCE_FEEDBACK,
        {
            "exercise_title": "Stepwise C Major",
            "instrument": "piano",
            "difficulty": "2",
            "metrics": "Overall score: 1.00",
            "deterministic_feedback": _feedback_block(deterministic),
        },
    )
    second = await FakeLLMClient().structured(
        LLMRole.PERFORMANCE_FEEDBACK,
        {
            "exercise_title": "Stepwise C Major",
            "instrument": "piano",
            "difficulty": "2",
            "metrics": "Overall score: 1.00",
            "deterministic_feedback": _feedback_block(deterministic),
        },
    )

    assert first.data["summary"] == deterministic.summary
    assert first.data["tone"] == deterministic.tone
    assert first.data["strengths"] == list(deterministic.strengths)
    assert first.data["corrections"] == list(deterministic.corrections)
    assert first.data["next_step"] == deterministic.next_step
    assert first.data == second.data


# ── every role must be answerable offline ────────────────────────────────────
#
# `FakeLLMClient.structured` looks its builder up in a plain dict. A role added
# to the enum and the registry but not to that dict raises `KeyError` at call
# time -- in a Celery task, or halfway through creating an exercise -- and
# nothing before this test would have caught it. `LLM_PROVIDER=fake` is the
# default, so a role without a fake handler is a role that does not work in the
# default configuration.

_MINIMAL_VARIABLES: dict[str, dict[str, object]] = {
    "graph_extract_map": {
        "book_title": "A Book",
        "chunks": "[chunk 1] Vectors add componentwise.",
        "section_path": "Chapter 1",
    },
    "graph_merge": {"book_title": "A Book", "concepts": "- `vectors` — **Vectors** — adding vectors"},
    "prereq_infer": {
        "book_title": "A Book",
        "section_slug": "dot-product",
        "section_text": "The dot product needs vectors.",
        "section_title": "Dot Product",
        "skill_list": "- `vectors` — **Vectors** — the basics",
    },
    "prereq_dependents": {
        "book_title": "A Book",
        "candidates": "### `dot-product` — Dot Product",
        "source_slug": "vectors",
        "source_text": "Vectors add componentwise.",
        "source_title": "Vectors",
    },
    "section_segment": {
        "book_title": "A Book",
        "fragment_count": 1,
        "fragments": "[fragment 1] lead-in: Definition: Norm\nThe norm measures length.",
        "section_slug": "norms",
        "section_title": "Norms",
    },
    "node_summary": {"book_title": "A Book", "node_count": 1, "nodes": "- `vectors` — **Vectors**\nVectors add."},
    "campaign_outcome_eval": {"outcome": "play a song", "skills": "- `chords` — Chords"},
    "course_qa": {
        "book_title": "A Book",
        "passages": "[1] Vectors add componentwise.",
        "question": "How do vectors add?",
    },
    "question_gen": {
        "context": "Vectors add componentwise.",
        "node_summary": "Adding vectors.",
        "node_title": "Vectors",
        "requested_type": "short_answer",
    },
    "grade": {
        "answer": "Componentwise.",
        "context": "Vectors add componentwise.",
        "question": "How do vectors add?",
        "rubric": "kp1: Says componentwise (weight 1.0)",
    },
    "performance_feedback": {
        "deterministic_feedback": (
            "Persona: Professor Cadenza\nTone: encouraging\nSummary: A tidy run.\n"
            "Strengths:\n- Steady pulse\nCorrections:\n- Watch the third note\nNext step: Play it again slowly."
        ),
        "difficulty": 2,
        "exercise_title": "Stepwise C Major",
        "instrument": "piano",
        "metrics": "pitch_accuracy: 0.95",
    },
    "live_coach_cue": {
        "cue": "rushing",
        "deterministic_cue": "You're getting ahead of the beat - let the pulse come to you.",
        "exercise_title": "Stepwise C Major",
        "instrument": "piano",
        "metric_words": "running ahead of the beat",
        "recent_utterances": "(none)",
        "severity": "nudge",
    },
    "curriculum_plan": {
        "goal": "I want to learn how to play guitar",
        "instrument": "guitar",
        "catalogue": '{"skills": [], "suggested_order": []}',
    },
    "score_compose": {
        "bars": 2,
        "beats_per_bar": 4,
        "constraints": "- At most 64 notes.",
        "difficulty": 2,
        "instrument": "piano",
        "key": "C major",
        "pattern": "scale_ascending",
        "procedural_notes": (
            '[{"beats": 1.0, "step": "C", "alter": 0, "octave": 4}, '
            '{"beats": 1.0, "step": "D", "alter": 0, "octave": 4}, '
            '{"beats": 1.0, "step": "E", "alter": 0, "octave": 4}, '
            '{"beats": 1.0, "step": "F", "alter": 0, "octave": 4}]'
        ),
        "skill_summary": "Play four adjacent notes.",
        "skill_title": "Stepwise Melody",
        "tempo_bpm": 84,
        "time_signature": "4/4",
    },
}


@pytest.mark.parametrize("role", list(LLMRole))
def test_every_role_has_a_fake_handler(role: LLMRole) -> None:
    variables = _MINIMAL_VARIABLES.get(role.value)
    assert variables is not None, f"add minimal variables for the new role {role.value!r}"
    result = asyncio.run(FakeLLMClient().structured(role, variables))
    assert result.data, f"the fake handler for {role.value!r} returned nothing"
    assert result.prompt_id == ROLES[role].prompt_id

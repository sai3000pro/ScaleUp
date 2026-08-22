"""Cloze and code drills stay grounded without executing learner code."""

from __future__ import annotations

from types import SimpleNamespace

from app.llm.base import LLMRole
from app.llm.fake_provider import FakeLLMClient
from app.services.drill_service import _grade_cloze, _grade_code

VARIABLES = {
    "node_title": "Dot Product",
    "node_summary": "Multiply matching components and sum them to produce a scalar.",
    "context": "The dot product multiplies matching components and sums them.",
}


async def test_fake_cloze_contains_one_blank_and_hidden_answers() -> None:
    result = await FakeLLMClient().structured(
        LLMRole.QUESTION_GEN,
        {**VARIABLES, "requested_type": "cloze"},
    )

    assert result.data["question_type"] == "cloze"
    assert result.data["question"].count("_____") == 1
    assert result.data["accepted_answers"]
    assert result.data["options"] == []


def test_cloze_grading_is_case_and_punctuation_tolerant() -> None:
    question = SimpleNamespace(
        accepted_answers=["orthogonal vectors", "orthogonal"],
        rubric=[{"id": "kp1", "point": "the key term", "weight": 1.0}],
    )

    result = _grade_cloze(question, " Orthogonal-vectors! ")

    assert result["score"] == 1.0
    assert result["points_hit"] == ["kp1"]


async def test_fake_code_drill_declares_static_requirements() -> None:
    result = await FakeLLMClient().structured(
        LLMRole.QUESTION_GEN,
        {**VARIABLES, "requested_type": "code"},
    )

    assert result.data["question_type"] == "code"
    assert result.data["code_language"] == "python"
    assert "return" in result.data["code_requirements"]


def test_code_grading_checks_requirements_without_execution() -> None:
    question = SimpleNamespace(
        code_requirements=["return", "dot product"],
        rubric=[{"id": "kp1", "point": "uses the operation", "weight": 1.0}],
    )

    result = _grade_code(question, "def dot_product(a, b):\n    return dot_product")

    assert result["score"] == 1.0
    assert "not executed" in str(result["feedback"])


def test_code_grading_reports_partial_static_coverage() -> None:
    question = SimpleNamespace(
        code_requirements=["return", "normalize"],
        rubric=[{"id": "kp1", "point": "uses normalization", "weight": 1.0}],
    )

    result = _grade_code(question, "return values")

    assert result["verdict"] == "partial"
    assert result["points_hit"] == ["return"]
    assert result["points_missed"] == ["normalize"]

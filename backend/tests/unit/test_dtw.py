"""DTW must preserve enough path information to explain misses and extras."""

from __future__ import annotations

from app.evaluation.dtw import align


def token_distance(left: object, right: object) -> float:
    return 0.0 if left == right else 2.0


def test_dtw_returns_exact_matches_without_gaps() -> None:
    result = align(["a", "b", "c"], ["a", "b", "c"], token_distance)

    assert result.distance == 0
    assert [step.operation for step in result.steps] == ["match", "match", "match"]
    assert result.matches[1].expected_index == 1


def test_dtw_exposes_missing_expected_and_extra_observed_events() -> None:
    result = align(
        ["a", "b"],
        ["a", "x", "b"],
        token_distance,
        deletion_cost=0.5,
        insertion_cost=0.5,
    )

    assert len(result.deletions) == 0
    assert len(result.insertions) == 1
    assert result.insertions[0].observed_index == 1

    missing = align(["a", "b"], ["a"], token_distance, deletion_cost=0.5)
    assert len(missing.deletions) == 1
    assert missing.deletions[0].expected_index == 1

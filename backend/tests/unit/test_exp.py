"""The published level curves are the ones the code produces."""

from __future__ import annotations

from app.domain.exp import account_level_for_exp, exp_for_node_level, node_level_for_exp


# @spec PROG-EXP-003, PROG-EXP-006
def test_node_level_thresholds_match_the_published_table() -> None:
    assert [exp_for_node_level(level) for level in range(5)] == [0, 100, 303, 580, 919]


# @spec PROG-EXP-003, PROG-EXP-006
def test_account_thresholds_are_the_same_curve_at_ten_times_scale() -> None:
    assert [round(1000 * level**1.6) for level in range(4)] == [0, 1000, 3031, 5800]
    assert account_level_for_exp(0) == 0
    assert account_level_for_exp(1000) == 1
    assert account_level_for_exp(3030) == 1
    assert account_level_for_exp(3031) == 2
    assert node_level_for_exp(919) == 4

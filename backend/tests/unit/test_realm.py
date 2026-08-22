"""Walking a skill's lesson run, and earning its test.

The rule is small, and the two ways it goes wrong are both quiet. Sending a
learner past a lesson they never cleared puts them at the test unprepared and
looks like generosity. Opening the test on an empty run makes every skill
instantly testable and looks like the feature working.
"""

from __future__ import annotations

from app.domain.realm import LessonProgress, is_lesson_open, is_test_open, open_lesson_step
from app.domain.srs import quality_from_score


def lesson(step: int, best: float | None) -> LessonProgress:
    return LessonProgress(
        exercise_id=f"e{step}",
        title=f"Lesson {step}",
        instructions="Play it.",
        difficulty=step,
        step=step,
        attempts=0 if best is None else 1,
        best_score=best,
    )


# @spec PROG-REALM-002
def test_a_lesson_clears_at_the_same_score_everything_else_calls_a_pass() -> None:
    """Half marks. A realm with its own bar would disagree with the EXP awarded."""
    assert quality_from_score(0.5) >= 3
    assert lesson(1, 0.5).cleared
    assert not lesson(1, 0.49).cleared
    assert not lesson(1, None).cleared


# @spec PROG-REALM-002
def test_the_open_lesson_is_the_first_one_not_cleared() -> None:
    run = (lesson(1, 0.8), lesson(2, None), lesson(3, None))
    assert open_lesson_step(run) == 2


# @spec PROG-REALM-002
def test_clearing_out_of_order_does_not_skip_the_middle() -> None:
    """Somebody who cleared one and three still owes two.

    The run is ordered by difficulty; letting a lucky take on the hardest
    lesson stand in for the one before it is how a learner reaches the test
    without the ground under it.
    """
    run = (lesson(1, 0.9), lesson(2, None), lesson(3, 0.9))
    assert open_lesson_step(run) == 2
    assert not is_test_open(run)


# @spec PROG-REALM-002
def test_a_cleared_lesson_can_still_be_replayed() -> None:
    """Skills decay, so going back has to stay possible."""
    run = (lesson(1, 0.9), lesson(2, None), lesson(3, None))
    assert is_lesson_open(run, 1)
    assert is_lesson_open(run, 2)
    assert not is_lesson_open(run, 3), "the ground ahead of the frontier stays closed"


# @spec PROG-REALM-003
def test_the_test_opens_only_when_every_lesson_is_cleared() -> None:
    assert not is_test_open((lesson(1, 0.9), lesson(2, 0.4)))
    assert is_test_open((lesson(1, 0.9), lesson(2, 0.6), lesson(3, 0.5)))


# @spec PROG-REALM-003
def test_an_empty_run_does_not_open_the_test() -> None:
    """`all([])` is True, which would make a skill with no lessons instantly testable."""
    assert not is_test_open(())
    assert open_lesson_step(()) is None


# @spec PROG-REALM-002
def test_a_finished_run_leaves_every_lesson_open() -> None:
    run = (lesson(1, 0.9), lesson(2, 0.9))
    assert open_lesson_step(run) is None
    assert is_lesson_open(run, 1) and is_lesson_open(run, 2)

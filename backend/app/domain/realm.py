"""When a skill's lessons are cleared, and when its test opens.

A skill is not one exercise. It is a short run of them at rising difficulty,
and then a test. This module is the rule for walking that run: which lesson is
open, which are done, and whether the learner has earned the right to be tested.

Pure, and it imports nothing from the rest of the application, because it is a
statement about progress rather than about storage — and because the same
question is asked from a canvas, from a service and from a test.

It invents no threshold. A lesson is cleared at exactly the score the rest of
the system already calls a pass: `quality_from_score(score) >= PASS_QUALITY`,
which is a half-marks boundary. A realm with its own idea of "good enough"
would disagree with the EXP the learner was awarded for the very same take.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.srs import PASS_QUALITY, quality_from_score


@dataclass(frozen=True, slots=True)
class LessonProgress:
    """One lesson in a skill's run, and how far the learner has got with it."""

    exercise_id: str
    title: str
    instructions: str
    difficulty: int
    #: Ordinal within the run, from 1. The run is a sequence, not a set.
    step: int
    attempts: int
    #: The learner's best take, or None where they have never played it.
    best_score: float | None

    @property
    def cleared(self) -> bool:
        return self.best_score is not None and quality_from_score(self.best_score) >= PASS_QUALITY


def is_cleared(best_score: float | None) -> bool:
    """Whether a best take clears a lesson."""
    return best_score is not None and quality_from_score(best_score) >= PASS_QUALITY


def open_lesson_step(lessons: tuple[LessonProgress, ...]) -> int | None:
    """The step the learner should play next, or None when the run is done.

    The first lesson they have not cleared — so a learner who cleared one and
    three is sent back to two rather than being told they are finished. The run
    is ordered by difficulty for a reason, and skipping the middle of it is how
    somebody arrives at the test unprepared.
    """
    for lesson in lessons:
        if not lesson.cleared:
            return lesson.step
    return None


def is_lesson_open(lessons: tuple[LessonProgress, ...], step: int) -> bool:
    """Whether a given step can be played now.

    Everything up to and including the frontier is open, so a learner can go
    back and replay something they already cleared -- which is the whole point
    of a skill that decays. What is closed is the ground ahead of them.
    """
    frontier = open_lesson_step(lessons)
    return frontier is None or step <= frontier


# @spec PROG-REALM-003
def is_test_open(lessons: tuple[LessonProgress, ...]) -> bool:
    """Whether the skill's test has been earned.

    Every lesson cleared, and there has to BE a lesson: a skill with an empty
    run would otherwise vacuously pass, and the test would be the only thing in
    the realm — which is exactly the state the run exists to prevent.
    """
    return len(lessons) > 0 and all(lesson.cleared for lesson in lessons)

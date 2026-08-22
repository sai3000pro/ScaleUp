"""A skill owns a run of lessons, and the run has to be a run.

The point of generating three instead of one is that a learner needs somewhere
to stand between never having attempted a skill and being tested on it. That
only works if the three actually differ — three renderings of the same score
under three names is the failure this guards against, and it is invisible from
the outside because the titles would still read 1, 2, 3.
"""

from __future__ import annotations

from app.evaluation.score_generator import spec_for_node
from app.services.score_service import LESSONS_PER_SKILL


def _graded(difficulty: int) -> list[int]:
    """The difficulties `ensure_lesson_set_for_node` derives for one skill."""
    return [max(1, min(5, difficulty + step - 1)) for step in range(1, LESSONS_PER_SKILL + 1)]


# @spec CURR-VERSION-011
def test_a_lesson_run_starts_at_the_skill_and_climbs() -> None:
    """Lesson one IS the skill, not an easier cousin of it.

    A node generated before lesson runs existed carries the skill's own
    difficulty and becomes lesson one. Starting the run below the skill would
    force that row to be relabelled as easier than the music it actually holds.
    """
    assert _graded(3) == [3, 4, 5]
    assert _graded(1) == [1, 2, 3]
    # Clamped at the top: a skill already at the ceiling still gets a run, and
    # the last two lessons differ in nothing but name. That is honest -- there
    # is no harder setting to give them.
    assert _graded(5) == [5, 5, 5]


# @spec CURR-VERSION-011
def test_the_lessons_differ_in_the_playing_rather_than_the_naming() -> None:
    """Tempo and length are what `spec_for_node` moves with difficulty."""
    specs = [
        spec_for_node(instrument="guitar", node_slug="basic-strumming", node_title="Basic Strumming", difficulty=d)
        for d in _graded(3)
    ]

    tempos = [spec.tempo_bpm for spec in specs]
    bars = [spec.bars for spec in specs]
    assert tempos == sorted(tempos), "a later lesson should not be slower than an earlier one"
    assert bars == sorted(bars), "a later lesson should not be shorter than an earlier one"
    assert len(set(zip(tempos, bars))) > 1, "three identical scores under three names is not a progression"


# @spec CURR-VERSION-011
def test_a_skill_at_the_ceiling_still_gets_a_run() -> None:
    """Clamping must not raise; the run just stops getting harder."""
    specs = [
        spec_for_node(instrument="piano", node_slug="cadences", node_title="Cadences", difficulty=d)
        for d in _graded(5)
    ]
    assert len(specs) == LESSONS_PER_SKILL


# @spec CURR-VERSION-011
def test_every_lesson_in_a_run_plays_the_same_pattern() -> None:
    """The run is one skill getting harder, not three different exercises.

    Pattern comes from the node's title, so this holds by construction -- which
    is worth pinning, because deriving it from difficulty instead would make
    lesson three a different skill wearing the same name.
    """
    patterns = {
        spec_for_node(
            instrument="piano", node_slug="major-scale", node_title="Major Scale", difficulty=d
        ).pattern
        for d in _graded(3)
    }
    assert len(patterns) == 1


# @spec CURR-VERSION-011
def test_a_run_is_long_enough_to_be_a_run() -> None:
    """Two is a pair. The chain in a realm needs a middle."""
    assert LESSONS_PER_SKILL >= 3

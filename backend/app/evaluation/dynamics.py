"""Scoring how loudly a learner played, relative to what was written.

Dynamics are the axis an examiner grades that error counts cannot reach: a run
with every note right and no shape is not a good performance. But loudness is
also the measurement most easily faked, so two rules govern everything here.

**Everything is relative.** Absolute dBFS is a function of microphone gain,
distance from the instrument, and the room. It carries no information about the
player. A learner who moves the laptop closer would "get louder" without
touching the instrument. So the observed levels are median-centred before they
are compared, and the single most trustworthy number this module produces --
`dynamics_contrast` -- is a *rank* agreement, which survives any monotonic gain
change at all.

**Inapplicable is not zero.** A score with no dynamic markings, or a take with
too few measured notes, yields `None` rather than 0.0. This is the same
discipline `drums.py` applies to `pitch_accuracy`: a drum has no pitch, so
reporting 0.0 would be a fabricated failure. A piece with no dynamics has no
dynamics to get wrong.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

__all__ = ["DYNAMIC_RANGE_DB", "DynamicsScore", "score_dynamics"]

# How many decibels separate the softest from the loudest a beginner actually
# plays across one short exercise. A GUESS, and flagged as one: it scales the
# mapping from measured dB onto the written 0..1 level scale. Too small and
# every take reads as over-dynamic; too large and nothing registers as contrast.
# It is the first constant to calibrate once real takes exist.
DYNAMIC_RANGE_DB = 24.0

# Below this, the sample is too small for a median to mean anything.
MIN_DYNAMIC_NOTES = 4
# A score whose written levels are all within this of each other is not asking
# for dynamic contrast, so there is nothing to score.
MIN_EXPECTED_SPREAD = 0.10


@dataclass(frozen=True, slots=True)
class DynamicsScore:
    """All None when dynamics are inapplicable, never 0.0."""

    dynamics_accuracy: float | None
    dynamic_range_db: float | None
    dynamics_contrast: float | None
    measured_note_count: int


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _inapplicable(count: int) -> DynamicsScore:
    return DynamicsScore(
        dynamics_accuracy=None,
        dynamic_range_db=None,
        dynamics_contrast=None,
        measured_note_count=count,
    )


# @spec EVAL-DYN-001, EVAL-DYN-002, EVAL-DYN-003, EVAL-DYN-004
def score_dynamics(
    expected_levels: Sequence[float | None],
    observed_levels_db: Sequence[float | None],
) -> DynamicsScore:
    """Compare written levels (0..1) against measured levels (dBFS).

    The two sequences are positionally paired: index *i* of each describes the
    same note. A None on either side means that note contributes nothing, which
    is how an unmeasured note and an unmarked passage both stay out of the
    average instead of being scored as silence.
    """
    if len(expected_levels) != len(observed_levels_db):
        raise ValueError("Expected and observed dynamics must describe the same notes.")

    pairs = [
        (expected, observed)
        for expected, observed in zip(expected_levels, observed_levels_db)
        if expected is not None and observed is not None and math.isfinite(observed)
    ]
    if len(pairs) < MIN_DYNAMIC_NOTES:
        return _inapplicable(len(pairs))

    expected_values = [pair[0] for pair in pairs]
    observed_values = [pair[1] for pair in pairs]
    if max(expected_values) - min(expected_values) < MIN_EXPECTED_SPREAD:
        return _inapplicable(len(pairs))

    # Centre both sides on their own median, then put the observation on the
    # written scale. Centring is what makes the comparison gain-invariant.
    observed_median = _median(observed_values)
    expected_median = _median(expected_values)
    normalised = [
        max(0.0, min(1.0, expected_median + (value - observed_median) / DYNAMIC_RANGE_DB))
        for value in observed_values
    ]
    error = sum(abs(actual - written) for actual, written in zip(normalised, expected_values)) / len(pairs)
    accuracy = max(0.0, min(1.0, 1.0 - error))

    # Rank agreement on consecutive written increases: "did the crescendo
    # happen?". Immune to gain, and it is what an examiner actually checks.
    rises = [
        (expected_values[index] > expected_values[index - 1], observed_values[index] > observed_values[index - 1])
        for index in range(1, len(pairs))
        if abs(expected_values[index] - expected_values[index - 1]) > 1e-9
    ]
    contrast = None if not rises else sum(1.0 for written, played in rises if written == played) / len(rises)

    return DynamicsScore(
        dynamics_accuracy=round(accuracy, 4),
        dynamic_range_db=round(max(observed_values) - min(observed_values), 2),
        dynamics_contrast=None if contrast is None else round(contrast, 4),
        measured_note_count=len(pairs),
    )

"""Spaced repetition: scheduling, mastery, and time decay.

Pure. `now` is always a parameter and the jitter source is injectable, which is
what lets the whole retention system be tested without waiting a month.

See docs/srs_and_exp.md for the reasoning behind each constant.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Callable

__all__ = [
    "ReviewState",
    "EASE_FLOOR",
    "EASE_CEILING",
    "MAX_INTERVAL_DAYS",
    "quality_from_score",
    "schedule",
    "update_mastery",
    "proficiency",
]

EASE_FLOOR = 1.3
EASE_CEILING = 2.8
MAX_INTERVAL_DAYS = 180.0
LAPSE_INTERVAL_DAYS = 0.5
PASS_QUALITY = 3
MASTERY_ALPHA = 0.4  # weight of the newest score in the EMA


@dataclass(frozen=True, slots=True)
class ReviewState:
    """Everything stored about a user's relationship with one node.

    Deliberately contains no derived values: `proficiency` and the node's visual
    state are computed on read from these fields plus the current time. Storing
    them would guarantee drift the moment a threshold changed, and would need a
    cron job to stay fresh as the clock moves.
    """

    ease: float = 2.5
    interval_days: float = 0.0
    reps: int = 0
    lapses: int = 0
    mastery: float = 0.0
    last_reviewed_at: datetime | None = None
    due_at: datetime | None = None


def quality_from_score(score: float) -> int:
    """Map a grader score in [0, 1] onto SM-2's 0-5 quality scale.

    Rounds half UP, deliberately. Python's built-in round() is banker's rounding,
    so round(2.5) == 2 -- which would silently place the pass/fail boundary at
    0.6 while every document in this repo says 0.5. A user scoring exactly half
    marks would fail, and nothing in the code would look wrong.
    """
    clamped = max(0.0, min(1.0, score))
    return int(math.floor(5 * clamped + 0.5))


# @spec PROG-SRS-003
def update_mastery(previous: float, score: float) -> float:
    """Exponential moving average of graded scores. Does not decay with time."""
    blended = (1.0 - MASTERY_ALPHA) * previous + MASTERY_ALPHA * max(0.0, min(1.0, score))
    return max(0.0, min(1.0, blended))


# @spec PROG-SRS-001, PROG-SRS-002, PROG-SRS-003, PROG-SRS-004
def schedule(
    state: ReviewState,
    score: float,
    now: datetime,
    jitter: Callable[[], float] = lambda: random.uniform(0.9, 1.1),
) -> ReviewState:
    """Advance a node's review state after a graded attempt (SM-2 derived).

    The jitter on `due_at` is not cosmetic. Without it, a user who ingests a
    course and drills thirty nodes on day one gets all thirty back on the same
    day, repeatedly -- a lumpy, punishing board. A +/-10% spread turns that into
    a daily habit. Tests pass `lambda: 1.0`.
    """
    quality = quality_from_score(score)
    passed = quality >= PASS_QUALITY

    if passed:
        reps = state.reps + 1
        # Ease is updated BEFORE it is applied, so a strong answer widens its own
        # next gap rather than the one after. (SM-2's original write-up is
        # ambiguous on the ordering; this matches Anki and is the more intuitive
        # reading of "you did well, so wait longer".)
        delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        ease = min(EASE_CEILING, max(EASE_FLOOR, state.ease + delta))
        if reps == 1:
            interval = 1.0
        elif reps == 2:
            interval = 6.0
        else:
            interval = state.interval_days * ease
        lapses = state.lapses
    else:
        reps = 0
        interval = LAPSE_INTERVAL_DAYS
        ease = max(EASE_FLOOR, state.ease - 0.20)
        lapses = state.lapses + 1

    interval = min(interval, MAX_INTERVAL_DAYS)

    return replace(
        state,
        ease=ease,
        interval_days=interval,
        reps=reps,
        lapses=lapses,
        mastery=update_mastery(state.mastery, score),
        last_reviewed_at=now,
        due_at=now + timedelta(days=interval * jitter()),
    )


# @spec PROG-SRS-005, PROG-SRS-006
def proficiency(state: ReviewState, now: datetime) -> float:
    """Mastery after time decay -- the number the UI draws as a ring.

    Invariant: proficiency halves every review interval, so at the exact moment
    a node comes due its ring is half full. That is legible to the user ("this
    is fading") and needs no maintenance job, because it is a function of the
    clock rather than a stored value.
    """
    if state.last_reviewed_at is None or state.mastery <= 0.0:
        return 0.0

    elapsed_days = max(0.0, (now - state.last_reviewed_at).total_seconds() / 86400.0)
    half_life = max(state.interval_days, 0.5)
    decayed = state.mastery * (2.0 ** (-elapsed_days / half_life))
    return max(0.0, min(1.0, decayed))

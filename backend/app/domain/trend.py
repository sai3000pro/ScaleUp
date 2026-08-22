"""Day-over-day movement in a learner's metrics.

Pure, and imports nothing -- including the metric definitions. Polarity is
*passed in* rather than looked up, because `domain/` may not import
`app/evaluation/`, and because the distinction it encodes is worth being
explicit about anyway:

    `trend`    -- which way the number moved.
    `improved` -- whether that is good news.

Those are different facts. Intonation deviation going down is an improvement;
pitch accuracy going down is not. Conflating them is how a coach ends up
congratulating someone for getting worse.

Nothing here is stored. The whole report is computed on read from the attempts
table, which is the same rule the rest of this system follows: a stored trend is
wrong the moment another attempt lands, and would need a job to keep it honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping, Sequence

__all__ = [
    "DailyMetrics",
    "MetricComparison",
    "SessionMetrics",
    "compare",
    "daily_metrics",
    "summarise",
]


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    at: datetime
    exercise_id: str
    values: Mapping[str, float | None]


@dataclass(frozen=True, slots=True)
class DailyMetrics:
    day: date
    attempts: int
    means: Mapping[str, float | None]


@dataclass(frozen=True, slots=True)
class MetricComparison:
    key: str
    current: float
    previous: float | None
    change: float
    trend: str  # up | down | baseline
    improvement_percentage: float | None
    # None when the caller supplied no polarity for this metric: "we do not know
    # whether this is good" is a real answer and better than a guess.
    improved: bool | None


# @spec COACH-EXAM-009
def daily_metrics(sessions: Sequence[SessionMetrics]) -> tuple[DailyMetrics, ...]:
    """Group attempts into calendar days, averaging each metric present.

    A metric that was `None` in an attempt contributes nothing rather than
    counting as zero, so a day of takes with the camera off does not read as a
    day of terrible posture.
    """
    buckets: dict[date, list[SessionMetrics]] = {}
    for session in sessions:
        buckets.setdefault(session.at.date(), []).append(session)

    days: list[DailyMetrics] = []
    for day in sorted(buckets):
        entries = buckets[day]
        keys = {key for entry in entries for key in entry.values}
        means: dict[str, float | None] = {}
        for key in sorted(keys):
            present = [
                float(entry.values[key])
                for entry in entries
                if entry.values.get(key) is not None
            ]
            means[key] = sum(present) / len(present) if present else None
        days.append(DailyMetrics(day=day, attempts=len(entries), means=means))
    return tuple(days)


# @spec COACH-EXAM-002
def compare(
    current: DailyMetrics,
    previous: DailyMetrics | None,
    *,
    better_when_lower: Mapping[str, bool],
) -> tuple[MetricComparison, ...]:
    """Compare one day against the one before it."""
    comparisons: list[MetricComparison] = []
    for key in sorted(current.means):
        value = current.means[key]
        if value is None:
            pass
        else:
            earlier = None if previous is None else previous.means.get(key)
            if earlier is None:
                comparisons.append(
                    MetricComparison(
                        key=key,
                        current=round(value, 4),
                        previous=None,
                        change=0.0,
                        trend="baseline",
                        improvement_percentage=None,
                        improved=None,
                    )
                )
            else:
                change = value - earlier
                lower_is_better = better_when_lower.get(key)
                comparisons.append(
                    MetricComparison(
                        key=key,
                        current=round(value, 4),
                        previous=round(earlier, 4),
                        change=round(change, 4),
                        trend="baseline" if abs(change) < 1e-9 else ("down" if change < 0 else "up"),
                        improvement_percentage=(
                            None if abs(earlier) < 1e-9 else round(abs(change) / abs(earlier) * 100.0, 2)
                        ),
                        improved=(
                            None
                            if lower_is_better is None or abs(change) < 1e-9
                            else (change < 0 if lower_is_better else change > 0)
                        ),
                    )
                )
    return tuple(comparisons)


# Which metric to lead with when several moved. Ordered by how directly a
# learner experiences it.
_HEADLINE_ORDER = (
    "overall_score",
    "pitch_accuracy",
    "rhythm_accuracy",
    "intonation_deviation_cents",
    "dynamics_accuracy",
    "posture_accuracy",
)

_LABELS = {
    "overall_score": "your overall score",
    "pitch_accuracy": "pitch accuracy",
    "rhythm_accuracy": "rhythm",
    "intonation_deviation_cents": "intonation",
    "dynamics_accuracy": "dynamic shaping",
    "posture_accuracy": "posture",
    "technique_accuracy": "fretboard position",
}


def summarise(comparisons: Sequence[MetricComparison]) -> tuple[str, tuple[str, ...]]:
    """A deterministic headline plus one line per metric that actually moved.

    This is the floor a coaching model rewords. It never claims a direction it
    cannot justify: a metric with no polarity is reported as movement, not as
    progress.
    """
    by_key = {comparison.key: comparison for comparison in comparisons}
    if not by_key:
        return "No practice recorded in this window yet.", ()

    if all(comparison.trend == "baseline" for comparison in comparisons):
        return "This is your baseline - come back tomorrow and there will be something to compare.", ()

    headline = "Your practice held steady."
    for key in _HEADLINE_ORDER:
        comparison = by_key.get(key)
        if comparison is not None and comparison.improved is not None:
            label = _LABELS.get(key, key.replace("_", " "))
            percentage = comparison.improvement_percentage
            movement = "" if percentage is None else f" by {percentage:.0f}%"
            headline = (
                f"{label.capitalize()} improved{movement} since your last session."
                if comparison.improved
                else f"{label.capitalize()} slipped{movement} since your last session."
            )
            break

    insights: list[str] = []
    for comparison in comparisons:
        if comparison.improved is None or comparison.trend == "baseline":
            pass
        else:
            label = _LABELS.get(comparison.key, comparison.key.replace("_", " "))
            direction = "better" if comparison.improved else "worse"
            insights.append(f"{label}: {comparison.previous} -> {comparison.current} ({direction})")
    return headline, tuple(insights[:5])

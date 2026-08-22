"""Practice progress across sessions, computed on read.

The examiner sees one take. A teacher sees a month. This service is the second
one: it reads the attempts a learner has already made and reports how the
numbers moved, so the coach can say "your rhythm is steadier than last week"
rather than starting from zero every time.

Nothing is stored. The report is a query over `performance_attempts` and
`performance_metric_bundles`, both of which already carry the indexes it needs.
A stored trend is wrong the moment the next attempt lands.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.coach_policy import BETTER_WHEN_LOWER
from app.domain.trend import DailyMetrics, SessionMetrics, compare, daily_metrics, summarise
from app.models import PerformanceAttempt, PerformanceMetricBundle, User
from app.schemas.progress import (
    DailyMetricsOut,
    MetricComparisonOut,
    PracticeReport,
)

# Which bundle columns are worth trending. Deliberately not "all of them": note
# counts move with the exercise rather than with the learner, so charting them
# would show effort as if it were progress.
TRENDED_METRICS = (
    "overall_score",
    "pitch_accuracy",
    "rhythm_accuracy",
    "technique_accuracy",
    "intonation_accuracy",
    "intonation_deviation_cents",
    "dynamics_accuracy",
    "posture_accuracy",
    "alignment_confidence",
)

# The polarity table the coach already uses, extended with the bundle's own
# fields. Declared rather than inferred -- see `domain/trend.py`.
BETTER_WHEN_LOWER_METRICS: dict[str, bool] = {
    **{key: value for key, value in BETTER_WHEN_LOWER.items()},
    "overall_score": False,
    "pitch_accuracy": False,
    "rhythm_accuracy": False,
    "technique_accuracy": False,
    "intonation_accuracy": False,
    "intonation_deviation_cents": True,
    "dynamics_accuracy": False,
    "posture_accuracy": False,
    "alignment_confidence": False,
}


def _out(day: DailyMetrics) -> DailyMetricsOut:
    return DailyMetricsOut(
        day=day.day,
        attempts=day.attempts,
        means={key: value for key, value in day.means.items() if value is not None},
    )


async def build_practice_report(
    session: AsyncSession,
    *,
    user: User,
    course_id: uuid.UUID,
    exercise_id: uuid.UUID | None = None,
    days: int = 30,
) -> PracticeReport:
    """How this learner's practice has moved over the last `days` days."""
    window = max(1, min(365, days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window)

    statement = (
        select(PerformanceAttempt, PerformanceMetricBundle)
        .join(PerformanceMetricBundle, PerformanceMetricBundle.attempt_id == PerformanceAttempt.id)
        .where(
            PerformanceAttempt.user_id == user.id,
            PerformanceAttempt.course_id == course_id,
            PerformanceAttempt.created_at >= cutoff,
        )
        .order_by(PerformanceAttempt.created_at)
    )
    if exercise_id is not None:
        statement = statement.where(PerformanceAttempt.exercise_id == exercise_id)

    rows = (await session.execute(statement)).all()
    sessions = [
        SessionMetrics(
            at=attempt.created_at,
            exercise_id=str(attempt.exercise_id),
            values={key: getattr(bundle, key, None) for key in TRENDED_METRICS},
        )
        for attempt, bundle in rows
    ]

    days_out = daily_metrics(sessions)
    latest = days_out[-1] if days_out else None
    previous = days_out[-2] if len(days_out) > 1 else None
    comparisons = () if latest is None else compare(latest, previous, better_when_lower=BETTER_WHEN_LOWER_METRICS)
    headline, insights = summarise(comparisons)

    return PracticeReport(
        course_id=course_id,
        exercise_id=exercise_id,
        window_days=window,
        attempt_count=len(sessions),
        practice_days=len(days_out),
        summary=headline,
        insights=list(insights),
        daily=[_out(day) for day in days_out],
        comparisons=[
            MetricComparisonOut(
                key=comparison.key,
                current=comparison.current,
                previous=comparison.previous,
                change=comparison.change,
                trend=comparison.trend,
                improvement_percentage=comparison.improvement_percentage,
                improved=comparison.improved,
            )
            for comparison in comparisons
        ],
    )

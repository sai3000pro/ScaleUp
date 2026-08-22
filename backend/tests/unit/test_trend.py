"""Progress across sessions, and the one distinction that matters in it.

`trend` is which way a number moved. `improved` is whether that is good news.
They are different facts, and a coach that conflates them congratulates a
learner for getting worse.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.trend import SessionMetrics, compare, daily_metrics, summarise

POLARITY = {
    "overall_score": False,
    "pitch_accuracy": False,
    "intonation_deviation_cents": True,
}

DAY_ONE = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def _session(offset_days: int, **values) -> SessionMetrics:
    return SessionMetrics(at=DAY_ONE + timedelta(days=offset_days), exercise_id="ex", values=values)


class TestGrouping:
    def test_attempts_group_into_calendar_days(self) -> None:
        days = daily_metrics(
            [
                _session(0, overall_score=0.5),
                _session(0, overall_score=0.7),
                _session(1, overall_score=0.9),
            ]
        )
        assert len(days) == 2
        assert days[0].attempts == 2
        assert days[0].means["overall_score"] == pytest.approx(0.6)
        assert days[1].means["overall_score"] == pytest.approx(0.9)

    def test_an_unmeasured_metric_does_not_count_as_zero(self) -> None:
        """A day of takes with the camera off is not a day of terrible posture."""
        days = daily_metrics(
            [
                _session(0, overall_score=0.8, posture_accuracy=None),
                _session(0, overall_score=0.8, posture_accuracy=0.9),
            ]
        )
        assert days[0].means["posture_accuracy"] == pytest.approx(0.9)

    def test_a_day_with_nothing_measured_reports_none(self) -> None:
        days = daily_metrics([_session(0, posture_accuracy=None)])
        assert days[0].means["posture_accuracy"] is None

    def test_no_attempts_produce_no_days(self) -> None:
        assert daily_metrics([]) == ()


class TestComparison:
    def test_the_first_day_is_a_baseline_not_a_regression(self) -> None:
        days = daily_metrics([_session(0, overall_score=0.6)])
        comparisons = compare(days[0], None, better_when_lower=POLARITY)
        assert comparisons[0].trend == "baseline"
        assert comparisons[0].previous is None
        assert comparisons[0].improved is None

    def test_polarity_decides_whether_movement_is_progress(self) -> None:
        days = daily_metrics(
            [
                _session(0, pitch_accuracy=0.9, intonation_deviation_cents=30.0),
                _session(1, pitch_accuracy=0.8, intonation_deviation_cents=20.0),
            ]
        )
        comparisons = {c.key: c for c in compare(days[1], days[0], better_when_lower=POLARITY)}

        # Both numbers went DOWN.
        assert comparisons["pitch_accuracy"].trend == "down"
        assert comparisons["intonation_deviation_cents"].trend == "down"
        # Only one of them is good news.
        assert comparisons["pitch_accuracy"].improved is False
        assert comparisons["intonation_deviation_cents"].improved is True

    def test_an_undeclared_metric_reports_movement_but_not_judgement(self) -> None:
        days = daily_metrics([_session(0, mystery=1.0), _session(1, mystery=2.0)])
        comparison = compare(days[1], days[0], better_when_lower=POLARITY)[0]
        assert comparison.trend == "up"
        assert comparison.improved is None

    def test_improvement_percentage_is_relative_to_the_earlier_value(self) -> None:
        days = daily_metrics([_session(0, overall_score=0.5), _session(1, overall_score=0.6)])
        comparison = compare(days[1], days[0], better_when_lower=POLARITY)[0]
        assert comparison.improvement_percentage == pytest.approx(20.0)


class TestSummary:
    def test_a_first_session_says_so(self) -> None:
        days = daily_metrics([_session(0, overall_score=0.6)])
        headline, insights = summarise(compare(days[0], None, better_when_lower=POLARITY))
        assert "baseline" in headline
        assert insights == ()

    def test_improvement_leads_the_headline(self) -> None:
        days = daily_metrics([_session(0, overall_score=0.5), _session(1, overall_score=0.75)])
        headline, insights = summarise(compare(days[1], days[0], better_when_lower=POLARITY))
        assert "improved" in headline
        assert len(insights) == 1

    def test_a_slip_is_reported_honestly(self) -> None:
        days = daily_metrics([_session(0, overall_score=0.9), _session(1, overall_score=0.6)])
        headline, _ = summarise(compare(days[1], days[0], better_when_lower=POLARITY))
        assert "slipped" in headline

    def test_nothing_recorded_is_not_an_error(self) -> None:
        headline, insights = summarise(())
        assert "No practice recorded" in headline
        assert insights == ()

    def test_it_never_claims_a_direction_it_cannot_justify(self) -> None:
        days = daily_metrics([_session(0, mystery=1.0), _session(1, mystery=5.0)])
        headline, insights = summarise(compare(days[1], days[0], better_when_lower=POLARITY))
        assert "improved" not in headline
        assert "slipped" not in headline
        assert insights == ()

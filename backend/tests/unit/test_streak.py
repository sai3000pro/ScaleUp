"""Consecutive-day streaks: the one walk, fed whatever days count."""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.streak import streak_days

TODAY = date(2026, 10, 3)


def ago(days: int) -> date:
    return TODAY - timedelta(days=days)


# @spec PROG-META-006, PROG-META-007
def test_no_active_days_is_zero() -> None:
    assert streak_days(set(), TODAY) == 0


# @spec PROG-META-006, PROG-META-007
def test_today_only_is_one() -> None:
    assert streak_days({TODAY}, TODAY) == 1


# @spec PROG-META-006, PROG-META-007
def test_a_streak_ending_yesterday_survives() -> None:
    """Today has not happened yet; midnight must not zero the counter."""
    assert streak_days({ago(1), ago(2)}, TODAY) == 2


# @spec PROG-META-006, PROG-META-007
def test_a_gap_stops_the_count() -> None:
    assert streak_days({TODAY, ago(1), ago(3), ago(4)}, TODAY) == 2
    assert streak_days({ago(2), ago(3)}, TODAY) == 0

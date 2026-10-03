"""Consecutive-day study streaks.

Pure. The walk is deliberately here and nowhere else: a streak is a statement
about which days were active, and "active" is whatever the caller unions in --
drill attempts, instrument takes, anything else a day should count for.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

__all__ = ["streak_days"]


# @spec PROG-META-006, PROG-META-007
def streak_days(active_days: Iterable[date], today: date) -> int:
    """Consecutive days, walking back from today, with at least one activity.

    A streak may legitimately end yesterday -- today's activity has not
    happened yet, and zeroing the counter at midnight would be punishing.
    """
    active = set(active_days)
    if not active:
        return 0
    cursor = today if today in active else today - timedelta(days=1)
    count = 0
    while cursor in active:
        count += 1
        cursor -= timedelta(days=1)
    return count

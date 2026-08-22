from __future__ import annotations

import uuid

from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    """One learner's standing inside a shared course's cohort.

    Deliberately no email and no user id: the leaderboard is a scoreboard, and
    the only identity it needs is the display name the learner chose.
    """

    display_name: str
    level: int
    total_exp: int
    streak_days: int
    # Within THIS course: nodes this learner has mastered / started.
    mastered_count: int
    started_count: int
    me: bool


class CourseLeaderboard(BaseModel):
    course_id: uuid.UUID
    # The cohort is the original course plus every copy made from its share
    # link. One learner per course, because copying is idempotent.
    cohort_size: int
    entries: list[LeaderboardEntry]
    # 1-based rank of the caller in `entries`; always present for the owner.
    my_rank: int

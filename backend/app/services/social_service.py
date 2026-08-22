"""Social progression: the cohort leaderboard.

Every course that was created by copying a share link points back at the
original via `copied_from_id`. That provenance makes a *cohort* a pure
derivation: the original course plus every copy of it. No new table, no
membership bookkeeping -- a cohort is exactly the set of courses that share a
root, and a course with no copies is a cohort of one.

The scoreboard is EXP inside the cohort, not across the whole app: the point
is that all these learners are working the SAME tree, so the comparison is
apples to apples. It is owner-scoped like every course endpoint -- you can only
see the cohort of a course you own -- and reveals only display names and
progress aggregates, never emails.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exp import level_progress
from app.domain.states import MASTERED_LEVEL, MASTERED_MASTERY
from app.models import Attempt, Course, NodeProgress, SkillNode, User
from app.schemas.social import CourseLeaderboard, LeaderboardEntry


async def _streaks_for_users(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Compute all cohort streaks from one grouped attempt query."""
    active_by_user: defaultdict[uuid.UUID, set[object]] = defaultdict(set)
    if user_ids:
        rows = await session.execute(
            select(Attempt.user_id, func.date(Attempt.created_at))
            .where(Attempt.user_id.in_(user_ids))
            .group_by(Attempt.user_id, func.date(Attempt.created_at))
        )
        for row in rows:
            active_by_user[row[0]].add(row[1])

    today = datetime.now(timezone.utc).date()
    streaks: dict[uuid.UUID, int] = {}
    for user_id in user_ids:
        active = active_by_user.get(user_id, set())
        if not active:
            streaks[user_id] = 0
        else:
            cursor = today if today in active else today - timedelta(days=1)
            count = 0
            while cursor in active:
                count += 1
                cursor -= timedelta(days=1)
            streaks[user_id] = count
    return streaks


# @spec PROG-META-003, PROG-META-007
async def build_leaderboard(session: AsyncSession, course: Course) -> CourseLeaderboard:
    root_id = course.copied_from_id or course.id
    cohort_ids = (
        await session.scalars(
            select(Course.id).where(or_(Course.id == root_id, Course.copied_from_id == root_id))
        )
    ).all()

    if not cohort_ids:
        # The root course was deleted; the caller's course is the only member.
        cohort_ids = [course.id]

    # One grouped query for every member's within-course stats. Per-learner
    # scalar counts would be N+1 and a viral course deserves better.
    rows = await session.execute(
        select(
            SkillNode.course_id,
            func.count(func.distinct(NodeProgress.node_id))
            .filter(NodeProgress.last_reviewed_at.is_not(None))
            .label("started"),
            func.count(func.distinct(NodeProgress.node_id))
            .filter(NodeProgress.level >= MASTERED_LEVEL, NodeProgress.mastery >= MASTERED_MASTERY)
            .label("mastered"),
        )
        .join(NodeProgress, NodeProgress.node_id == SkillNode.id)
        .where(SkillNode.course_id.in_(cohort_ids))
        .group_by(SkillNode.course_id)
    )
    stats = {row.course_id: (row.started, row.mastered) for row in rows}

    members = (await session.scalars(select(Course).where(Course.id.in_(cohort_ids)))).all()
    owner_by_id = {
        owner.id: owner
        for owner in (await session.scalars(select(User).where(User.id.in_([m.owner_id for m in members])))).all()
    }
    streaks = await _streaks_for_users(session, list(owner_by_id))

    entries: list[LeaderboardEntry] = []
    for member in members:
        owner = owner_by_id.get(member.owner_id)
        if owner is not None:
            started, mastered = stats.get(member.id, (0, 0))
            entries.append(
                LeaderboardEntry(
                    display_name=owner.display_name,
                    # Account level and streak are derived, never stored -- same
                    # curve and same definition as the HUD, so the leaderboard
                    # cannot drift from what the learner sees about themselves.
                    level=level_progress(owner.total_exp)[0],
                    total_exp=owner.total_exp,
                    streak_days=streaks.get(owner.id, 0),
                    mastered_count=mastered,
                    started_count=started,
                    me=member.id == course.id,
                )
            )

    entries.sort(key=lambda entry: (-entry.total_exp, -entry.level, entry.display_name.lower()))
    my_rank = next((index for index, entry in enumerate(entries, start=1) if entry.me), None)
    if my_rank is None:
        # The caller owns this course, so their entry is in the cohort by
        # construction; if it is missing something is wrong, and a 500 is the
        # honest answer rather than a fabricated rank.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "The leaderboard could not place the caller.")

    return CourseLeaderboard(course_id=course.id, cohort_size=len(entries), entries=entries, my_rank=my_rank)

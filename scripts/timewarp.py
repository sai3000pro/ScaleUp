r"""Rewind a user's review history so decay becomes observable.

You cannot test spaced repetition without a time machine. Everything the SRS
does is a function of elapsed time, so without this the only way to see a node
reach `decaying` is to wait days -- which means the quest board, the rescue
bonus, and the whole retention half of the product go untested.

Shifts `last_reviewed_at` and `due_at` backwards, which is equivalent to moving
the clock forwards without touching the system clock.

    cd backend
    .\.venv\Scripts\python.exe ..\scripts\timewarp.py --days 30
    .\.venv\Scripts\python.exe ..\scripts\timewarp.py --days 30 --slug keyboard-layout
    .\.venv\Scripts\python.exe ..\scripts\timewarp.py --reset
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db.session import sync_session  # noqa: E402
from app.domain.srs import ReviewState, proficiency  # noqa: E402
from app.domain.states import derive_state, overdue_days  # noqa: E402
from app.models import NodeProgress, SkillNode, User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Rewind review timestamps to make decay visible.")
    parser.add_argument("--email", default="dev@example.com", help="whose progress to shift")
    parser.add_argument("--days", type=float, default=30.0, help="how far to rewind")
    parser.add_argument("--slug", help="limit to one skill (default: all)")
    parser.add_argument("--reset", action="store_true", help="mark everything reviewed just now instead")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    shift = timedelta(days=args.days)

    with sync_session() as session:
        user = session.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            print(f"no user {args.email!r}. Run: python -m app.seed")
            return 1

        query = (
            select(NodeProgress, SkillNode)
            .join(SkillNode, SkillNode.id == NodeProgress.node_id)
            .where(NodeProgress.user_id == user.id, NodeProgress.reps > 0)
        )
        if args.slug:
            query = query.where(SkillNode.slug == args.slug)

        rows = list(session.execute(query))
        if not rows:
            print("nothing to shift -- drill something first (only reviewed nodes have a schedule).")
            return 1

        print(f"{'skill':<26} {'state':<10} {'prof':>6}  {'overdue':>8}")
        print("-" * 56)

        for progress, node in rows:
            if args.reset:
                progress.last_reviewed_at = now
                progress.due_at = now + timedelta(days=progress.interval_days)
            else:
                if progress.last_reviewed_at is not None:
                    progress.last_reviewed_at = progress.last_reviewed_at - shift
                if progress.due_at is not None:
                    progress.due_at = progress.due_at - shift

            state = ReviewState(
                ease=progress.ease,
                interval_days=progress.interval_days,
                reps=progress.reps,
                lapses=progress.lapses,
                mastery=progress.mastery,
                last_reviewed_at=progress.last_reviewed_at,
                due_at=progress.due_at,
            )
            derived = derive_state(state, progress.level, [], now)
            print(
                f"{node.title[:25]:<26} {derived.value:<10} "
                f"{proficiency(state, now):>6.2f}  {overdue_days(state, now):>8.1f}d"
            )

    verb = "reset to now" if args.reset else f"rewound {args.days:g} days"
    print(f"\n{len(rows)} skill(s) {verb} for {args.email}.")
    print("Reload the tree, or check GET /api/quests/daily.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

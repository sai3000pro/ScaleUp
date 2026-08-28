r"""Regenerate a course's exercises so they carry what the current generator writes.

`ensure_lesson_set_for_node` never regenerates a score under a stable exercise
id, and that rule is right: attempt history is grouped by exercise, so swapping
the music turns "you improved" into a comparison between two different pieces.

The consequence is that a database seeded before a generator change keeps the
older scores forever. That is correct for a learner's database and wrong for a
demo one -- written dynamics, for instance, only reach exercises generated after
the generator learned to write them, so a long-lived demo shows three of the four
scored dimensions and no amount of re-seeding changes it.

So this is the explicit, operator-invoked way to say "this is demo content, throw
it away and build it again". It does not quietly reinterpret history: it DELETES
the attempts, practice sessions and coach sessions belonging to the exercises it
replaces, because leaving them attached to new music is the dishonesty the rule
above exists to prevent. EXP already awarded is not clawed back.

    # See what would change. Touches nothing.
    python ..\scripts\refresh_exercises.py

    # Do it.
    python ..\scripts\refresh_exercises.py --yes

    # One course, by id or by title.
    python ..\scripts\refresh_exercises.py --course Piano --yes

Point it at another database the same way everything else here does, by setting
SYNC_DATABASE_URL for the process.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import delete, select  # noqa: E402

from app.db.session import sync_session  # noqa: E402
from app.evaluation.musicxml import parse_musicxml  # noqa: E402
from app.models import (  # noqa: E402
    CoachSession,
    CoachUtterance,
    Course,
    Exercise,
    PerformanceAttempt,
    PerformanceMetricBundle,
    PracticeSession,
    ScoreAsset,
    SkillNode,
)
from app.services.score_service import ensure_lesson_set_for_node, instrument_for_course  # noqa: E402


def _courses(session, wanted: str | None) -> list[Course]:
    courses = list(session.scalars(select(Course)))
    if wanted is None:
        return courses
    needle = wanted.lower()
    return [c for c in courses if needle in c.title.lower() or str(c.id) == wanted]


def _shaped(session, exercise_ids: list) -> int:
    """How many of these exercises carry written dynamics."""
    if not exercise_ids:
        return 0
    rows = session.execute(
        select(ScoreAsset.content)
        .join(Exercise, Exercise.score_asset_id == ScoreAsset.id)
        .where(Exercise.id.in_(exercise_ids))
    )
    shaped = 0
    for (content,) in rows:
        try:
            if parse_musicxml(content).dynamics:
                shaped += 1
        except Exception:  # noqa: BLE001 -- a score that will not parse is not a shaped one
            pass
    return shaped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", help="Only this course, by id or by a substring of its title.")
    parser.add_argument("--yes", action="store_true", help="Actually delete and rebuild. Without it, nothing changes.")
    args = parser.parse_args()

    # Which database, before anything else. This deletes rows, and the only thing
    # standing between "the demo" and "the one someone is using" is an environment
    # variable that is easy to forget you did not set. The password is never printed.
    from app.db.session import _sync_engine

    target = _sync_engine().url.render_as_string(hide_password=True)
    print(f"\ndatabase   {target}")

    with sync_session() as session:
        courses = _courses(session, args.course)
        if not courses:
            total = len(list(session.scalars(select(Course.id))))
            if total == 0:
                print(
                    "\nThis database has no courses at all.\n"
                    "\n  A local one that pytest has run against is empty by design -- it"
                    " truncates every table. Run `python -m app.seed` first.\n"
                    "\n  A deployed one is not what this points at unless you say so:\n"
                    "    $env:SYNC_DATABASE_URL = 'postgresql+psycopg://...'\n"
                )
            else:
                titles = ", ".join(sorted(c.title for c in session.scalars(select(Course))))
                print(f"\nNo course matches {args.course!r}. This database has: {titles}\n")
            return 1

        print(f"\n{'COURSE':<28} {'EXERCISES':>9} {'SHAPED':>7} {'ATTEMPTS':>9}")
        print(f"{'-' * 28} {'-' * 9} {'-' * 7} {'-' * 9}")
        planned: list[tuple[Course, list]] = []
        for course in courses:
            ids = list(session.scalars(select(Exercise.id).where(Exercise.course_id == course.id)))
            attempts = session.scalar(
                select(PerformanceAttempt.id).where(PerformanceAttempt.course_id == course.id).limit(1)
            )
            attempt_count = len(
                list(session.scalars(select(PerformanceAttempt.id).where(PerformanceAttempt.course_id == course.id)))
            ) if attempts is not None else 0
            print(f"{course.title[:28]:<28} {len(ids):>9} {_shaped(session, ids):>7} {attempt_count:>9}")
            planned.append((course, ids))

        if not args.yes:
            print("\nDry run. Nothing was changed. Re-run with --yes to rebuild these.")
            print("That DELETES the attempts, practice sessions and coach sessions above.\n")
            return 0

        rebuilt = 0
        for course, exercise_ids in planned:
            instrument = instrument_for_course(session, course.id)
            if instrument is None:
                # No published curriculum, so nothing to generate against.
                continue
            if exercise_ids:
                attempt_ids = list(
                    session.scalars(select(PerformanceAttempt.id).where(PerformanceAttempt.exercise_id.in_(exercise_ids)))
                )
                coach_ids = list(
                    session.scalars(select(CoachSession.take_id).where(CoachSession.exercise_id.in_(exercise_ids)))
                )
                # Children first: nothing here relies on a cascade being declared.
                if coach_ids:
                    session.execute(delete(CoachUtterance).where(CoachUtterance.take_id.in_(coach_ids)))
                    session.execute(delete(CoachSession).where(CoachSession.take_id.in_(coach_ids)))
                if attempt_ids:
                    session.execute(
                        delete(PerformanceMetricBundle).where(PerformanceMetricBundle.attempt_id.in_(attempt_ids))
                    )
                    session.execute(delete(PerformanceAttempt).where(PerformanceAttempt.id.in_(attempt_ids)))
                session.execute(delete(PracticeSession).where(PracticeSession.exercise_id.in_(exercise_ids)))
                session.execute(delete(Exercise).where(Exercise.id.in_(exercise_ids)))
                # Score assets are content-addressed and shared, so drop only the
                # ones this course owns that nothing points at any more.
                orphans = list(
                    session.scalars(
                        select(ScoreAsset.id)
                        .outerjoin(Exercise, Exercise.score_asset_id == ScoreAsset.id)
                        .where(ScoreAsset.course_id == course.id, Exercise.id.is_(None))
                    )
                )
                if orphans:
                    session.execute(delete(ScoreAsset).where(ScoreAsset.id.in_(orphans)))
                session.flush()

            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)):
                rebuilt += len(
                    ensure_lesson_set_for_node(session, course=course, node=node, instrument=instrument)
                )
        session.commit()

        print(f"\nRebuilt {rebuilt} exercise(s).\n")
        with sync_session() as check:
            for course, _ in planned:
                ids = list(check.scalars(select(Exercise.id).where(Exercise.course_id == course.id)))
                print(f"  {course.title[:28]:<28} {len(ids):>3} exercise(s), {_shaped(check, ids):>3} now shaped")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

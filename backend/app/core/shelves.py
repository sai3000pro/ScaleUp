"""Which shelf a course sits on, and the fixed ids of the ones this project ships.

A learner's course list is theirs. It fills up with the trees they asked for, and
anything else standing in it is noise they did not create and cannot explain. But
the seed also writes courses -- two the project offers as a starting point, and
several more that exist so the practice loop, the scheduler and the admin paths
are developable with no provider and no upload. All of them are owned by the same
development user, so ownership cannot tell them apart.

So the shelf is declared, not guessed. The alternative -- reading it off a title
suffix, or off which compiler built the version -- makes the learner's list depend
on a naming habit, and a habit is not an invariant.

Split out of `app.seed` for the same reason `app.core.dev_user` was: `app.seed`
imports `app.services.graph_service`, so a service reaching back into the seed for
these ids would close an import cycle. `app.seed` re-exports every name here, so
`from app.seed import GUITAR_COURSE_ID` keeps working.
"""

from __future__ import annotations

import uuid

#: The learner made this one -- from a stated goal, from an upload, or empty.
LEARNER = "learner"
#: The project offers this one, ready to play, before the learner asks for anything.
PREBUILT = "prebuilt"
#: Seeded so the system is developable offline. Real, playable, and not on offer.
INTERNAL = "internal"

SHELVES = (LEARNER, PREBUILT, INTERNAL)

# Fixed so the ids are copy-pasteable and re-seeding is idempotent.
#: A linear-algebra tree from before this was a music product. The course is
#: gone; the id remains because the seed still has to retire it from databases
#: that already hold the row.
RETIRED_LINEAR_ALGEBRA_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
PIANO_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000004")
GUITAR_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000006")
VIOLIN_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000008")
TRUMPET_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000014")
DRUMS_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000016")
BANJO_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000018")

#: What a learner is offered. Deliberately two: the shelf is a way in, not an
#: inventory, and a wall of trees nobody chose is the thing it exists to prevent.
PREBUILT_COURSE_IDS: tuple[uuid.UUID, ...] = (GUITAR_COURSE_ID, PIANO_COURSE_ID)

#: Seeded and kept, because the admin, cost, scheduling and evaluation paths are
#: developed against them. Never offered.
INTERNAL_COURSE_IDS: tuple[uuid.UUID, ...] = (
    VIOLIN_COURSE_ID,
    TRUMPET_COURSE_ID,
    DRUMS_COURSE_ID,
    BANJO_COURSE_ID,
)


# @spec CURR-SHELF-001, CURR-SHELF-004
def shelf_for(course_id: uuid.UUID) -> str:
    """The shelf a course belongs on. Anything unlisted is the learner's own."""
    if course_id in PREBUILT_COURSE_IDS:
        return PREBUILT
    elif course_id in INTERNAL_COURSE_IDS:
        return INTERNAL
    else:
        return LEARNER

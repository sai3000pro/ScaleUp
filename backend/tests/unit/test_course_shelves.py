"""Which shelf a course sits on is declared, and the declaration is the test.

The whole point of the shelf is that it does not depend on a title, a description
or the compiler that built the version -- so what is worth asserting is the
declaration itself: that the offered set is small and deliberate, that the
development fixtures are named rather than implied, and that anything unlisted
falls through to the learner.
"""

from __future__ import annotations

import uuid

from app.core import shelves


# @spec CURR-SHELF-001
def test_a_course_nobody_declared_belongs_to_the_learner() -> None:
    assert shelves.shelf_for(uuid.uuid4()) == shelves.LEARNER


# @spec CURR-SHELF-003
def test_the_offered_shelf_is_guitar_and_piano() -> None:
    assert set(shelves.PREBUILT_COURSE_IDS) == {shelves.GUITAR_COURSE_ID, shelves.PIANO_COURSE_ID}
    for course_id in shelves.PREBUILT_COURSE_IDS:
        assert shelves.shelf_for(course_id) == shelves.PREBUILT


# @spec CURR-SHELF-005
def test_an_internal_course_is_never_the_learners_and_never_offered() -> None:
    for course_id in shelves.INTERNAL_COURSE_IDS:
        assert shelves.shelf_for(course_id) == shelves.INTERNAL
    assert shelves.RETIRED_LINEAR_ALGEBRA_COURSE_ID not in shelves.INTERNAL_COURSE_IDS, (
        "the linear-algebra tree is retired, not shelved"
    )


# @spec CURR-SHELF-004
def test_no_course_is_declared_on_two_shelves() -> None:
    assert not set(shelves.PREBUILT_COURSE_IDS) & set(shelves.INTERNAL_COURSE_IDS)

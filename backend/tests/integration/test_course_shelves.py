"""A learner's list is theirs, and the seeded trees do not stand in it.

The unit test proves the declaration; this proves it survives the round trip --
that the shelf reaches the client on the same payload the list is drawn from, and
that a tree the learner asked for is labelled as theirs while the seeded ones are
not.

These run as the seeded development user rather than a freshly registered one,
because the courses under test are the ones `seed()` writes and a course listing
is owner-scoped. A fresh user's list is correctly empty, which would make every
assertion here vacuous.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.core import shelves
from app.seed import seed


async def _dev_client(client: AsyncClient) -> AsyncClient:
    seed()
    response = await client.post("/api/auth/dev-login")
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


# @spec CURR-SHELF-001, CURR-SHELF-002
async def test_the_listing_labels_every_course_with_its_shelf(client: AsyncClient) -> None:
    dev = await _dev_client(client)

    created = await dev.post("/api/courses/from-goal", json={"goal": "I want to learn how to play the flute"})
    assert created.status_code == 201, created.text

    listing = await dev.get("/api/courses")
    assert listing.status_code == 200
    by_id = {course["id"]: course for course in listing.json()["courses"]}

    assert by_id[created.json()["id"]]["shelf"] == shelves.LEARNER
    assert by_id[str(shelves.GUITAR_COURSE_ID)]["shelf"] == shelves.PREBUILT
    assert by_id[str(shelves.PIANO_COURSE_ID)]["shelf"] == shelves.PREBUILT
    assert by_id[str(shelves.TRUMPET_COURSE_ID)]["shelf"] == shelves.INTERNAL

    mine = [course for course in by_id.values() if course["shelf"] == shelves.LEARNER]
    assert [course["id"] for course in mine] == [created.json()["id"]], (
        "a freshly seeded database has exactly one course the learner made"
    )


# @spec CURR-SHELF-005
async def test_the_retired_linear_algebra_tree_is_gone_from_the_listing(client: AsyncClient) -> None:
    """It predates the instrument product, and seeding retires it rather than hiding it."""
    dev = await _dev_client(client)

    courses = (await dev.get("/api/courses")).json()["courses"]
    ids = {course["id"] for course in courses}

    assert str(shelves.RETIRED_LINEAR_ALGEBRA_COURSE_ID) not in ids
    assert not any("Linear Algebra" in course["title"] for course in courses)


# @spec CURR-SHELF-006
async def test_an_offered_course_opens_the_same_way_a_learners_does(client: AsyncClient) -> None:
    """The shelf says where a course came from, never what it is."""
    dev = await _dev_client(client)

    graph = await dev.get(f"/api/courses/{shelves.GUITAR_COURSE_ID}/graph")
    assert graph.status_code == 200, graph.text
    nodes = graph.json()["nodes"]
    assert nodes, "an offered course with no skills is not somewhere to start"
    assert any(node["progress"]["state"] == "available" for node in nodes)

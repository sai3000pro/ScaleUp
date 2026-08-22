"""The admin surface: reindex, projection health, rejections, cancellation.

The two tests this file exists for are `test_reindex_does_not_move_graph_version`
and `test_reindex_leaves_node_progress_intact`. Everything else here is ordinary
endpoint coverage; those two are the guard rail.

They exist because there is an obvious wrong way to build reindex -- route it
through `extract_graph`, on the reasoning that "rebuild from source" means
re-running the pipeline. That path reaches `persist_graph`, which full-replaces
`skill_nodes`; the cascade takes each node's edges *and its `node_progress`
rows*, and `course.graph_version` increments. So a reindex written that way would
delete the user's EXP and review history (the same shape of bug already cost 1325
EXP once -- see `ingest_pipeline._course_toc_graph`) and would move the very
`graph_version` that `is_stale` compares against, making the staleness answer
meaningless.

If someone "simplifies" reindex into the extraction pipeline, these two fail.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import Attempt, Course, IngestJob, NodeProgress, Question, SkillEdgeRejection, SkillNode
from app.repositories import neo4j_repo
from app.seed import PIANO_COURSE_ID, TRUMPET_COURSE_ID, seed
from app.vector.chroma_store import get_vector_store


@pytest.fixture
def seeded(clean_db: None) -> uuid.UUID:
    """The piano course, with Neo4j and Chroma left empty.

    `clean_db` wipes both derived stores and `seed()` writes only Postgres, so
    the starting state is exactly the one reindex exists to repair: a correct
    source of truth with nothing projected from it.
    """
    seed()
    with sync_session() as session:
        node = session.scalar(
            select(SkillNode).where(SkillNode.course_id == PIANO_COURSE_ID, SkillNode.slug == "keyboard-layout")
        )
        return node.id


@pytest.fixture
async def dev_headers(client: AsyncClient, seeded: uuid.UUID) -> dict[str, str]:
    response = await client.post("/api/auth/dev-login")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def graph_version() -> int:
    with sync_session() as session:
        return session.get(Course, PIANO_COURSE_ID).graph_version


def node_ids() -> set[uuid.UUID]:
    with sync_session() as session:
        return set(session.scalars(select(SkillNode.id).where(SkillNode.course_id == PIANO_COURSE_ID)))


def covering_answer(attempt_id: str) -> str:
    with sync_session() as session:
        attempt = session.get(Attempt, uuid.UUID(attempt_id))
        question = session.get(Question, attempt.question_id)
        return " ".join(point["point"] for point in question.rubric)


async def drill_and_grade(client: AsyncClient, headers: dict[str, str], node_id: uuid.UUID) -> None:
    drill = await client.post(f"/api/nodes/{node_id}/drill", headers=headers)
    assert drill.status_code == 201, drill.text
    attempt_id = drill.json()["attempt_id"]
    graded = await client.post(
        f"/api/attempts/{attempt_id}/grade",
        headers=headers,
        json={"answer": covering_answer(attempt_id)},
    )
    assert graded.status_code == 200, graded.text


# ── the two guards ────────────────────────────────────────────────────────


async def test_reindex_does_not_move_graph_version(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """`graph_version` is the goalpost. A reindex restores the score, never moves it.

    `is_stale` asks "does the projection's version equal the course's?". If a
    reindex incremented the course's version it would be comparing against a
    number it had just changed, and "the projection is fresh" would mean only
    "the projection was written recently" -- true of a projection built from
    nothing.
    """
    before = graph_version()

    response = await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)
    assert response.status_code == 202, response.text

    assert graph_version() == before


async def test_reindex_leaves_node_progress_intact(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """Earned EXP and review history survive a rebuild of the derived stores.

    `node_progress` is keyed on `(user_id, node_id)` with ON DELETE CASCADE, so
    anything that deletes and re-inserts skill nodes silently takes every user's
    progress with it -- including the node ids the rows point at. Both are
    asserted: the progress row, and the node identity it depends on.
    """
    await drill_and_grade(client, dev_headers, seeded)

    ids_before = node_ids()
    with sync_session() as session:
        rows = list(session.scalars(select(NodeProgress).where(NodeProgress.node_id == seeded)))
        assert len(rows) == 1
        exp_before, reps_before = rows[0].exp, rows[0].reps
        assert exp_before > 0, "the fixture grade must actually award EXP for this test to mean anything"

    response = await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)
    assert response.status_code == 202, response.text

    assert node_ids() == ids_before, "reindex must not delete and recreate skill nodes"
    with sync_session() as session:
        rows = list(session.scalars(select(NodeProgress).where(NodeProgress.node_id == seeded)))
    assert len(rows) == 1
    assert (rows[0].exp, rows[0].reps) == (exp_before, reps_before)


# ── what it does rebuild ──────────────────────────────────────────────────


async def test_reindex_rebuilds_both_derived_stores(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    assert neo4j_repo.projected_version(PIANO_COURSE_ID) is None
    assert get_vector_store().count(str(PIANO_COURSE_ID)) == 0

    response = await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)
    assert response.status_code == 202, response.text

    assert neo4j_repo.projected_version(PIANO_COURSE_ID) == graph_version()
    # One vector per seeded chunk, one chunk per fixture concept.
    assert get_vector_store().count(str(PIANO_COURSE_ID)) == len(node_ids())


async def test_reindex_reports_success_through_the_job_endpoint(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """A reindex job polls exactly like an ingest, with a null `document_id`."""
    accepted = (
        await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)
    ).json()

    job = (await client.get(f"/api/jobs/{accepted['job_id']}", headers=dev_headers)).json()
    assert job["state"] == "succeeded"
    assert job["percent"] == 100.0
    # The whole reason `document_id` became nullable: a reindex spans every
    # document in the course, so there is no single one to name.
    assert job["document_id"] is None
    assert job["course_id"] == str(PIANO_COURSE_ID)
    assert job["stage_detail"]["scope"] == "all"
    # The post-condition the task checks and records: after a good projection the
    # course is not stale.
    assert job["stage_detail"]["stale"] is False


@pytest.mark.parametrize(
    ("scope", "expects_vectors", "expects_projection"),
    [("graph", False, True), ("vectors", True, False)],
)
async def test_scope_limits_which_store_is_rebuilt(
    client: AsyncClient,
    dev_headers: dict[str, str],
    seeded: uuid.UUID,
    scope: str,
    expects_vectors: bool,
    expects_projection: bool,
) -> None:
    """A graph-only rebuild is free; a vector rebuild costs real money."""
    response = await client.post(
        f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers, params={"scope": scope}
    )
    assert response.status_code == 202, response.text
    assert response.json()["scope"] == scope

    assert (get_vector_store().count(str(PIANO_COURSE_ID)) > 0) is expects_vectors
    assert (neo4j_repo.projected_version(PIANO_COURSE_ID) is not None) is expects_projection


async def test_a_second_reindex_joins_an_unfinished_one(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """Two clicks must not start two rebuilds racing to write one collection."""
    first = (await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)).json()

    # Eager Celery ran the first job to completion, so park it back in a
    # non-terminal state to model a rebuild still in flight.
    with sync_session() as session:
        session.get(IngestJob, uuid.UUID(first["job_id"])).state = "embedding"

    second = (await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)).json()
    assert second["job_id"] == first["job_id"]
    assert second["deduplicated"] is True


def test_a_projection_failure_fails_the_reindex_job(
    seeded: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deliberate inverse of `tasks.ingest.project_stage`, which swallows this.

    On an ingest the projection is a side effect and swallowing its failure is
    right -- the ingest succeeded, Postgres holds the graph, the read path falls
    back to it. On a reindex the projection IS the deliverable, so reporting
    `succeeded` over a store that is still exactly as broken as it was would
    leave the user with no reason to try again.

    Driven through the task rather than the endpoint because the failure belongs
    on the job row, which is where a real worker would put it.
    """
    from app.tasks import reindex as reindex_task

    def unreachable(*args, **kwargs):
        raise ConnectionError("neo4j is not listening")

    monkeypatch.setattr(reindex_task, "project_course", unreachable)

    with sync_session() as session:
        job = IngestJob(
            course_id=PIANO_COURSE_ID,
            kind="reindex",
            document_id=None,
            idempotency_key="fail-project" + "0" * 40,
            state="queued",
            stage_detail={"scope": "all"},
        )
        session.add(job)
        session.flush()
        job_id = job.id

    with pytest.raises(ConnectionError):
        reindex_task.run_reindex(str(job_id))

    with sync_session() as session:
        failed = session.get(IngestJob, job_id)
        assert failed.state == "failed"
        assert "ConnectionError" in failed.error
        # Chroma ran FIRST and succeeded, so the vectors are there -- but nothing
        # reports the projection as fresh. Had the order been reversed, the
        # staleness gauge would now read "fine" over a half-built index.
        assert failed.stage_detail["embedded"] > 0

    # And the course is untouched: a failed reindex leaves Postgres exactly as it
    # was, so flipping `course.status` to "failed" would put a failure banner
    # over a working tree.
    with sync_session() as session:
        assert session.get(Course, PIANO_COURSE_ID).status != "failed"


# ── projection ────────────────────────────────────────────────────────────


async def test_projection_reports_stale_then_fresh(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """The monitorable scalar the whole consistency story rests on.

    An absent projection reads as stale, not as fine -- a course that has never
    been projected is indistinguishable from one whose store was wiped, and both
    want the same fix.
    """
    before = (
        await client.get(f"/api/admin/courses/{PIANO_COURSE_ID}/projection", headers=dev_headers)
    ).json()
    assert before["stale"] is True
    assert before["projected_version"] is None
    assert before["neo4j_reachable"] is True
    assert before["node_count"] == len(node_ids())

    await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)

    after = (
        await client.get(f"/api/admin/courses/{PIANO_COURSE_ID}/projection", headers=dev_headers)
    ).json()
    assert after["stale"] is False
    assert after["projected_version"] == after["graph_version"] == before["graph_version"]
    assert after["vector_count"] == before["node_count"]


async def test_projection_reports_an_unreachable_store_instead_of_failing(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A status endpoint that 500s when the store is down is useless.

    This is the one situation it was written for, so it must answer.
    """

    def unreachable(*args, **kwargs):
        raise ConnectionError("neo4j is not listening")

    monkeypatch.setattr(neo4j_repo, "projected_version", unreachable)

    response = await client.get(f"/api/admin/courses/{PIANO_COURSE_ID}/projection", headers=dev_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["neo4j_reachable"] is False
    assert body["stale"] is True
    assert "neo4j" in body["detail"]


# ── rejections ────────────────────────────────────────────────────────────


async def test_rejections_expose_the_planted_cycle_with_its_path(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """The trumpet fixture carries the back-edge, so this runs against a real rejection.

    "A melody teaches you long tones" is the shape of claim a model actually
    makes, and long-tones already reaches the melody through major-arpeggios.
    """
    body = (
        await client.get(f"/api/admin/courses/{TRUMPET_COURSE_ID}/rejections", headers=dev_headers)
    ).json()

    assert body["total"] == 1
    assert body["by_reason"] == {"cycle": 1}
    (row,) = body["rows"]
    assert (row["prereq_slug"], row["target_slug"]) == ("simple-trumpet-melody", "long-tones")
    # The cycle path, not just the label, is the debugging material.
    assert row["cycle_path"][0] == "long-tones"
    assert row["cycle_path"][-1] == "simple-trumpet-melody"


async def test_rejections_paginate_without_repeating_or_skipping_rows(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """A bad prompt version produces thousands of these in one ingest.

    Self-contained: it plants every row it counts, on a course the seed leaves
    with none, so paging is asserted against a number this test controls rather
    than against whatever the fixtures happen to refuse.
    """
    with sync_session() as session:
        for index in range(10):
            session.add(
                SkillEdgeRejection(
                    course_id=PIANO_COURSE_ID,
                    prereq_slug=f"p{index}",
                    target_slug=f"t{index}",
                    reason="low_confidence",
                    confidence=0.1,
                )
            )

    seen: list[str] = []
    for offset in (0, 4, 8):
        page = (
            await client.get(
                f"/api/admin/courses/{PIANO_COURSE_ID}/rejections",
                headers=dev_headers,
                params={"limit": 4, "offset": offset},
            )
        ).json()
        assert page["total"] == 10
        # Counted over the whole course, so it does not change as you page.
        assert page["by_reason"] == {"low_confidence": 10}
        seen.extend(row["id"] for row in page["rows"])

    assert len(seen) == 10
    assert len(set(seen)) == 10, "a page boundary repeated a row"


# ── auth ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("post", "reindex"), ("get", "projection"), ("get", "rejections")],
)
async def test_admin_routes_are_owner_scoped_and_404_rather_than_403(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID, method: str, suffix: str
) -> None:
    """`/api/admin` names the surface, not a privilege level.

    404 rather than 403 for someone else's course: a 403 confirms the id exists,
    which is an enumeration oracle.
    """
    other = await client.post(
        "/api/auth/register",
        json={"email": "nosy@example.com", "password": "hunter22-long-enough", "display_name": "N"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = await getattr(client, method)(
        f"/api/admin/courses/{PIANO_COURSE_ID}/{suffix}", headers=headers
    )
    assert response.status_code == 404


# ── cancellation ──────────────────────────────────────────────────────────


async def test_cancelling_a_queued_job_stops_it_before_it_starts(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    """`cancelled` was in the CHECK constraint and `is_cancelled` was checked in
    four places, but nothing ever set it -- so cancellation was unreachable by
    construction. This is the first test that can even reach the guard.
    """
    from app.tasks.reindex import run_reindex

    with sync_session() as session:
        job = IngestJob(
            course_id=PIANO_COURSE_ID,
            kind="reindex",
            document_id=None,
            idempotency_key="cancel-me" + "0" * 40,
            state="queued",
            stage_detail={"scope": "all"},
        )
        session.add(job)
        session.flush()
        job_id = job.id

    response = await client.post(f"/api/jobs/{job_id}/cancel", headers=dev_headers)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "cancelled"

    # The worker picking it up afterwards must do no work at all.
    assert run_reindex(str(job_id)) == "cancelled"
    assert neo4j_repo.projected_version(PIANO_COURSE_ID) is None
    assert get_vector_store().count(str(PIANO_COURSE_ID)) == 0


async def test_cancelling_a_finished_job_is_a_conflict(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    accepted = (
        await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)
    ).json()

    response = await client.post(f"/api/jobs/{accepted['job_id']}/cancel", headers=dev_headers)
    assert response.status_code == 409
    assert "succeeded" in response.json()["detail"]


async def test_cancel_is_owner_scoped(
    client: AsyncClient, dev_headers: dict[str, str], seeded: uuid.UUID
) -> None:
    accepted = (
        await client.post(f"/api/admin/courses/{PIANO_COURSE_ID}/reindex", headers=dev_headers)
    ).json()
    other = await client.post(
        "/api/auth/register",
        json={"email": "nosy2@example.com", "password": "hunter22-long-enough", "display_name": "N"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = await client.post(f"/api/jobs/{accepted['job_id']}/cancel", headers=headers)
    assert response.status_code == 404


# ── the constraint under it ───────────────────────────────────────────────


def test_the_check_constraint_refuses_a_malformed_job(seeded: uuid.UUID) -> None:
    """The invariant is preserved, not dropped -- just made conditional on `kind`.

    `document_id` used to be NOT NULL, which is right for an ingest and
    impossible for a reindex. Simply relaxing it would have permitted a
    document-less *ingest* row, a shape no task can execute.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with sync_session() as session:
            session.add(
                IngestJob(
                    course_id=PIANO_COURSE_ID,
                    kind="ingest",
                    document_id=None,
                    idempotency_key="bad-ingest" + "0" * 40,
                    state="queued",
                )
            )

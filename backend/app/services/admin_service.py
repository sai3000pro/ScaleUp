"""The admin surface: rebuild the derived stores, watch them, and read rejections.

**The rule that governs this whole module: a reindex never writes Postgres.**

Postgres is the only source of truth; Neo4j is a derived read-model and Chroma a
derived index (CLAUDE.md § conventions). That claim is only worth something if
the derived stores are rebuildable, which is what `request_reindex` provides.

The failure mode to guard against is a reindex implemented by re-running
`extract_graph`. It looks like the obvious way to "rebuild everything from the
source", and it would:

* call `persist_graph`, which FULL-REPLACES `skill_nodes` -- and the cascade
  takes each node's edges *and its `node_progress` rows*. That is not a
  hypothetical: the same shape of bug destroyed 1325 EXP and 9 reviews once
  already, and the incident is recorded in `ingest_pipeline._course_toc_graph`;
* bump `course.graph_version`, which is the goalpost `is_stale` compares against
  -- so a reindex that bumped it would move the very number it exists to restore;
* spend real money re-running extraction, when nothing about the *content*
  changed.

So: read Postgres, write Chroma and Neo4j, touch nothing else. The two
regression tests in `tests/integration/test_admin_reindex.py` are what keep that
true -- `graph_version` unchanged, `node_progress` intact.

The one exception, stated so nobody has to discover it: `embed_course` sets
`chunks.vector_id`, which records which id a chunk was stored under in Chroma.
That is bookkeeping about the derived index rather than authoritative content,
the value is deterministic, and writing it is what keeps Postgres honest about
what the index now contains. See its docstring in `ingest_pipeline`.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models import Chunk, Course, IngestJob, SkillEdge, SkillEdgeRejection, SkillNode
from app.repositories import neo4j_repo
from app.schemas.admin import (
    ProjectionStatus,
    ReindexAccepted,
    ReindexScope,
    RejectionRow,
    RejectionsPage,
)
from app.schemas.job import IngestJobOut
from app.services import ingest_service
from app.vector.chroma_store import get_vector_store

# A job in one of these is finished and can no longer be cancelled or joined.
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


# ── reindex ───────────────────────────────────────────────────────────────


def _reindex_key(course_id: uuid.UUID, scope: ReindexScope, nonce: uuid.UUID) -> str:
    """`ingest_jobs.idempotency_key` is UNIQUE and NOT NULL, so a reindex needs one.

    Unlike an ingest key -- derived from the content hash, so re-uploading the
    same bytes collapses to one job -- a reindex is deliberately repeatable: the
    reason to run a second one is that something changed in a store this key
    knows nothing about. The nonce keeps the column's uniqueness honest without
    pretending two rebuilds of the same course are the same request. Concurrent
    duplicates are caught by the in-flight check in `request_reindex` instead,
    which is where that question actually belongs.
    """
    return hashlib.sha256(f"reindex:{course_id}:{scope.value}:{nonce}".encode()).hexdigest()


# @spec CURR-PROJ-001, CURR-PROJ-002
async def request_reindex(
    session: AsyncSession, course: Course, scope: ReindexScope = ReindexScope.ALL
) -> ReindexAccepted:
    """Queue a rebuild of the derived stores. Returns immediately."""
    running = await session.scalar(
        select(IngestJob)
        .where(
            IngestJob.course_id == course.id,
            IngestJob.kind == "reindex",
            IngestJob.state.not_in(TERMINAL_STATES),
        )
        .order_by(IngestJob.created_at.desc())
    )
    if running is not None:
        # Two clicks on the rebuild button must not start two rebuilds racing to
        # write the same collection. Scope is deliberately NOT part of the match:
        # any reindex in flight is already rewriting these stores.
        return ReindexAccepted(
            job_id=running.id,
            course_id=course.id,
            scope=ReindexScope(str((running.stage_detail or {}).get("scope", ReindexScope.ALL.value))),
            deduplicated=True,
        )

    job = IngestJob(
        course_id=course.id,
        kind="reindex",
        # Null by construction, and the CHECK constraint added with `kind`
        # enforces it: a reindex spans every document in the course.
        document_id=None,
        idempotency_key=_reindex_key(course.id, scope, uuid.uuid4()),
        state="queued",
        units_total=2 if scope is ReindexScope.ALL else 1,
        stage_detail={"scope": scope.value},
    )
    session.add(job)
    # Note what is NOT here: `course.status` is untouched. A reindex does not
    # make a ready course un-ready -- the graph in Postgres is fine, and the read
    # path falls back to it while the projection is being rebuilt.
    await session.commit()
    await session.refresh(job)

    # Enqueue only after the commit, or the worker races our own transaction and
    # looks up a job that does not exist yet.
    from app.tasks.reindex import run_reindex

    async_result = run_reindex.delay(str(job.id))
    job.celery_root_id = async_result.id
    await session.commit()

    return ReindexAccepted(job_id=job.id, course_id=course.id, scope=scope, deduplicated=False)


# ── projection health ─────────────────────────────────────────────────────


# @spec CURR-PROJ-003, CURR-PROJ-004
async def projection_status(session: AsyncSession, course: Course) -> ProjectionStatus:
    """Is the projection stale? The one monitorable scalar of the whole design.

    Two constraints shape this function.

    **It must never raise.** A health endpoint that 500s when the store it
    reports on is down is useless in exactly the situation it was written for.
    Every derived-store read is wrapped; an unreachable store reports
    `reachable: false` and `stale: true`, because a projection that cannot be
    read cannot be asserted current.

    **It cannot call `neo4j_repo.is_stale`.** That helper takes a *synchronous*
    Session, so it is unusable from an async handler. The comparison it performs
    is one line, and the async caller already holds the course; so staleness is
    computed here from `projected_version()`, and the Celery task -- which does
    hold a sync Session -- is `is_stale`'s caller.
    """
    node_count = (
        await session.scalar(select(func.count(SkillNode.id)).where(SkillNode.course_id == course.id)) or 0
    )
    edge_count = (
        await session.scalar(select(func.count()).select_from(SkillEdge).where(SkillEdge.course_id == course.id))
        or 0
    )
    chunk_count = (
        await session.scalar(select(func.count(Chunk.id)).where(Chunk.course_id == course.id)) or 0
    )

    problems: list[str] = []

    # Both drivers are synchronous and do network I/O, so neither may run on the
    # event loop.
    try:
        projected = await run_in_threadpool(neo4j_repo.projected_version, course.id)
        neo4j_reachable = True
    except Exception as exc:  # noqa: BLE001 -- reachability is the answer, not an error
        projected, neo4j_reachable = None, False
        problems.append(f"neo4j: {type(exc).__name__}: {exc}")

    try:
        vector_count = await run_in_threadpool(get_vector_store().count, str(course.id))
        chroma_reachable = True
    except Exception as exc:  # noqa: BLE001
        vector_count, chroma_reachable = None, False
        problems.append(f"chroma: {type(exc).__name__}: {exc}")

    return ProjectionStatus(
        course_id=course.id,
        graph_version=course.graph_version,
        node_count=node_count,
        edge_count=edge_count,
        chunk_count=chunk_count,
        neo4j_reachable=neo4j_reachable,
        projected_version=projected,
        # An absent projection (`None`) is stale, not fresh -- a course that has
        # never been projected reads exactly like one whose store was wiped, and
        # both want a reindex.
        stale=(not neo4j_reachable) or projected != course.graph_version,
        chroma_reachable=chroma_reachable,
        vector_count=vector_count,
        detail="; ".join(problems) or None,
    )


# ── rejections ────────────────────────────────────────────────────────────


async def rejections(
    session: AsyncSession, course: Course, *, limit: int = 50, offset: int = 0
) -> RejectionsPage:
    """Edges the extractor proposed and the DAG builder refused.

    `skill_edge_rejections` is written on every `persist_graph` and, until this
    endpoint, was read by nothing outside tests and a `print()` in `seed.py` --
    though `docs/archive/graph_extraction_contract.md` calls it "the primary debugging
    material for prompt iteration".
    """
    total = (
        await session.scalar(
            select(func.count())
            .select_from(SkillEdgeRejection)
            .where(SkillEdgeRejection.course_id == course.id)
        )
        or 0
    )

    grouped = await session.execute(
        select(SkillEdgeRejection.reason, func.count())
        .where(SkillEdgeRejection.course_id == course.id)
        .group_by(SkillEdgeRejection.reason)
        .order_by(func.count().desc())
    )
    by_reason = {reason: int(count) for reason, count in grouped}

    rows = (
        await session.scalars(
            select(SkillEdgeRejection)
            .where(SkillEdgeRejection.course_id == course.id)
            # Newest first: the run you just did is the run you are debugging.
            # `id` breaks ties because a whole persist writes within one
            # `created_at`, which would otherwise make paging non-deterministic
            # and silently skip or repeat rows across pages.
            .order_by(SkillEdgeRejection.created_at.desc(), SkillEdgeRejection.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return RejectionsPage(
        course_id=course.id,
        total=total,
        by_reason=by_reason,
        limit=limit,
        offset=offset,
        rows=[RejectionRow.model_validate(row) for row in rows],
    )


# ── cancellation ──────────────────────────────────────────────────────────


# @spec CURR-JOB-006
async def cancel_job(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> IngestJobOut:
    """Ask a job to stop.

    `cancelled` has been in the state CHECK constraint and `is_cancelled` has
    been checked at four points in `tasks/ingest.py` since stage 1, but nothing
    ever set the state -- so cooperative cancellation was unreachable by
    construction. This is the setter.

    **The mechanism is cooperative, and the distinction matters.** Celery's
    `revoke()` does not reach a task that is already executing, so this flips the
    row and the running task notices at its next stage boundary. Concretely:

    * a QUEUED job never starts -- `run_ingest_pipeline` / `run_reindex` both
      check before doing any work;
    * a RUNNING job finishes its current stage and then stops. Cancelling during
      a 40-minute extraction does not abort the extraction; it stops the pipeline
      before the next one. The stage already in flight is not interrupted.

    That is a deliberate trade: every stage is written to be idempotent so a
    redelivery is safe, and killing a worker mid-write is what makes that
    property expensive to keep.
    """
    # Ownership and the 404-not-403 rule, reusing the one place that implements
    # both. It raises 404 for a job in someone else's course.
    current = await ingest_service.get_job(session, job_id, user_id)

    if current.state in TERMINAL_STATES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Job is already {current.state} and cannot be cancelled.",
        )

    job = await session.get(IngestJob, job_id)
    job.state = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    await session.commit()

    return await ingest_service.get_job(session, job_id, user_id)

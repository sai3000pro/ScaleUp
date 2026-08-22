"""Rebuild a course's derived stores from Postgres.

Thin, like every task here: load a session, call a service, update the job row
(CLAUDE.md § layering). The business rule it enforces is stated once, in
`services/admin_service`, and is worth repeating at the top of the file that
executes it: **a reindex reads Postgres and rewrites only Chroma and Neo4j.** It
must never reach `extract_graph`, and therefore never `persist_graph`, which
full-replaces `skill_nodes` and cascades away `node_progress`. The only Postgres
column it writes is `chunks.vector_id` -- see `ingest_pipeline.embed_course`.

The task is named `ingest.run_reindex` on purpose. `celery_app.task_routes`
routes `ingest.*` to the `ingest` queue, so the worker command documented in
CLAUDE.md picks this up with no change. It must also appear in `celery_app`'s
`include=[...]`, or the worker never imports this module, the task never
registers, and every reindex sits `queued` at 0% with nothing logged anywhere --
this project's flagship failure mode.
"""

from __future__ import annotations

import uuid

from celery.utils.log import get_task_logger

from app.db.session import sync_session
from app.models import IngestJob
from app.repositories.neo4j_repo import is_stale, project_course
from app.services.ingest_pipeline import StageResult, embed_course
from app.tasks.celery_app import celery_app
from app.tasks.ingest import _merge_stage_detail, _set_state, is_cancelled

logger = get_task_logger(__name__)


def _job_target(job_id: str) -> tuple[uuid.UUID, str]:
    """The course this job rebuilds, and the scope it was queued with."""
    with sync_session() as session:
        job = session.get(IngestJob, job_id)
        if job is None:
            raise LookupError(f"ingest job {job_id} not found")
        return job.course_id, str((job.stage_detail or {}).get("scope", "all"))


@celery_app.task(name="ingest.run_reindex", bind=True)
def run_reindex(self, job_id: str) -> str:
    """Chroma, then Neo4j. Both from committed Postgres rows.

    **Chroma before Neo4j, and the order is load-bearing.** `project_course`
    writes `graphVersion` onto the Course node, and that value is the entire
    input to `is_stale`. Projecting first and then failing the re-embed would
    leave the staleness gauge reading "fine" over a half-empty index -- the one
    outcome worse than a store that is obviously broken, because nothing would
    ever prompt a second attempt.

    No `autoretry_for`. An ingest retries transient provider errors because
    re-running a stage is cheap next to losing the parse; a reindex is cheap to
    re-request by hand, and an automatic retry loop against an unreachable Neo4j
    would re-embed the whole course -- at real cost with a real key -- on every
    attempt.
    """
    logger.info("reindex starting for job %s", job_id)

    if is_cancelled(job_id):
        logger.info("reindex job %s was cancelled before it started", job_id)
        return "cancelled"

    course_id, scope = _job_target(job_id)
    do_vectors = scope in {"all", "vectors"}
    do_graph = scope in {"all", "graph"}
    units_total = int(do_vectors) + int(do_graph)
    done = 0

    try:
        _set_state(job_id, state="embedding", units_total=units_total, units_done=0)

        if do_vectors:
            embedded = embed_stage(course_id)
            _merge_stage_detail(job_id, embedded=embedded.embedded)
            done += 1
        else:
            _merge_stage_detail(job_id, embedded=None)

        if is_cancelled(job_id):
            return "cancelled"

        _set_state(job_id, state="finalizing", units_done=done)

        if do_graph:
            edges = project_stage(course_id)
            _merge_stage_detail(job_id, neo4j_edges=edges, stale=stale_stage(course_id))
            done += 1
        else:
            _merge_stage_detail(job_id, neo4j_edges=None)

        _set_state(job_id, state="succeeded", units_done=units_total, units_total=units_total)
    except Exception as exc:  # noqa: BLE001 -- the job row is the error channel
        logger.exception("reindex job %s failed", job_id)
        _set_state(job_id, state="failed", error=f"{type(exc).__name__}: {exc}")
        # Note what is NOT done here: `course.status` is left alone. An ingest
        # that fails leaves a course with no usable graph, so `tasks/ingest` marks
        # it failed. A reindex that fails leaves Postgres exactly as it was --
        # the course is still ready and still readable; only the derived stores
        # are behind. Flipping the course to "failed" would put a failure banner
        # over a working tree.
        raise

    return "succeeded"


def embed_stage(course_id: uuid.UUID) -> StageResult:
    with sync_session() as session:
        return embed_course(session, course_id)


def project_stage(course_id: uuid.UUID) -> int:
    """Mirror the committed graph into Neo4j. Failure FAILS this job.

    This is the deliberate inverse of `tasks.ingest.project_stage`, which
    swallows the same exception, and the divergence is not an oversight -- do not
    "fix" the inconsistency.

    On an *ingest*, the projection is a side effect: the ingest genuinely
    succeeded, Postgres holds the graph, the read path falls back to Postgres
    when the projection is stale, and failing a completed 40-minute ingest
    because a read-model was briefly unavailable would be the wrong call.

    On a *reindex*, the projection IS the deliverable. There is nothing else the
    job did. Swallowing the failure here would report `succeeded` over a store
    that is still exactly as broken as it was when the user asked for the
    rebuild -- and they would have no reason to ask again.
    """
    with sync_session() as session:
        return project_course(session, course_id)


def stale_stage(course_id: uuid.UUID) -> bool:
    """Read the staleness gauge back after writing it.

    `neo4j_repo.is_stale` takes a synchronous Session, which is why the async
    `/projection` endpoint cannot call it and computes the comparison itself.
    Here there is a sync session, so this is the caller it was written for -- and
    it is a genuine post-condition check: after a successful projection the
    course must not be stale, and recording that in `stage_detail` means a
    rebuild that somehow did not take is visible in the job rather than only in
    the next person's confusion.
    """
    with sync_session() as session:
        return is_stale(session, course_id)

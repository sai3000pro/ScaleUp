"""Ingestion pipeline tasks.

Tasks are thin: load a session, call a service, update the job row. All business
logic lives in services and domain (see CLAUDE.md § layering).

Task arguments carry identifiers, never content. A 1000-page book must never
exist as a task payload -- it lives in Postgres and on disk, and tasks address
slices of it by id range.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from celery.utils.log import get_task_logger

from app.db.session import sync_session
from app.llm.base import ProviderError
from app.models import Course, Document, IngestJob
from app.repositories.neo4j_repo import project_course
from app.services.ingest_pipeline import (
    StageResult,
    chunk_document,
    embed_document,
    extract_graph,
    parse_document,
)
from app.tasks.celery_app import celery_app

logger = get_task_logger(__name__)


def _set_state(job_id: str, *, state: str, **fields) -> None:
    """Advance a job's state. Safe to call from any stage."""
    with sync_session() as session:
        job = session.get(IngestJob, job_id)
        if job is None:
            logger.warning("ingest job %s vanished before state=%s", job_id, state)
        else:
            job.state = state
            for key, value in fields.items():
                setattr(job, key, value)
            if state not in {"queued", "succeeded", "failed", "cancelled"} and job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            if state in {"succeeded", "failed", "cancelled"}:
                job.finished_at = datetime.now(timezone.utc)


def _fail_course(job_id: str) -> None:
    """Mark the job's course failed, unless another document already succeeded.

    A course is a bag of documents. If one upload fails while an earlier one
    produced a usable graph, the course is still `ready` and blanking that would
    hide a working tree behind a failure banner.
    """
    with sync_session() as session:
        job = session.get(IngestJob, job_id)
        if job is None:
            logger.warning("ingest job %s vanished before its course could be failed", job_id)
        else:
            course = session.get(Course, job.course_id)
            if course is not None and course.status != "ready":
                course.status = "failed"


def _merge_stage_detail(job_id: str, **detail) -> None:
    with sync_session() as session:
        job = session.get(IngestJob, job_id)
        if job is not None:
            # Reassign rather than mutate: SQLAlchemy does not track in-place
            # edits to a JSONB dict, and the update would silently not persist.
            job.stage_detail = {**(job.stage_detail or {}), **detail}


def is_cancelled(job_id: str) -> bool:
    """Cheap guard every stage checks first.

    Celery's revoke() does not reach a task already executing, so cancellation
    is cooperative: the API flips the row and stages notice.
    """
    with sync_session() as session:
        job = session.get(IngestJob, job_id)
        return job is not None and job.state == "cancelled"


def _document_id(job_id: str) -> uuid.UUID:
    with sync_session() as session:
        job = session.get(IngestJob, job_id)
        if job is None:
            raise LookupError(f"ingest job {job_id} not found")
        return job.document_id


@celery_app.task(
    name="ingest.run_ingest_pipeline",
    bind=True,
    max_retries=5,
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
# @spec CURR-JOB-001, CURR-JOB-002, CURR-JOB-003, CURR-JOB-005
def run_ingest_pipeline(self, job_id: str) -> str:
    """Parse -> chunk -> embed, driving the job state machine.

    Every stage is idempotent (delete-then-write on a natural key), which is what
    makes `task_acks_late` safe: a worker killed mid-ingest redelivers the task
    and the replay is a no-op rather than a duplicate.
    """
    logger.info("ingest pipeline starting for job %s", job_id)

    if is_cancelled(job_id):
        logger.info("job %s was cancelled before it started", job_id)
        return "cancelled"

    document_id = _document_id(job_id)

    try:
        # Three stages; units_done advances one per completed stage so the
        # polling UI moves even before chunk counts are known.
        _set_state(job_id, state="parsing", units_total=5, units_done=0)
        parsed = parse_stage(document_id)
        _merge_stage_detail(job_id, pages=parsed.pages)

        if is_cancelled(job_id):
            return "cancelled"

        _set_state(job_id, state="chunking", units_done=1)
        chunked = chunk_stage(document_id)
        _merge_stage_detail(job_id, chunks=chunked.chunks)

        if is_cancelled(job_id):
            return "cancelled"

        _set_state(job_id, state="embedding", units_done=2)
        embedded = embed_stage(document_id)
        _merge_stage_detail(job_id, embedded=embedded.embedded)

        if is_cancelled(job_id):
            return "cancelled"

        _set_state(job_id, state="extracting", units_done=3)
        extracted = extract_stage(document_id)
        _merge_stage_detail(
            job_id,
            windows=extracted.windows,
            failed_windows=extracted.windows_failed,
            concepts_raw=extracted.concepts_raw,
            concepts_merged=extracted.concepts_merged,
            edges_accepted=extracted.edges_accepted,
            edges_rejected=extracted.edges_rejected,
        )

        # Postgres has committed. Only now project to the derived stores -- and
        # a projection failure must not fail an otherwise-good ingest, because
        # the read path falls back to Postgres when the projection is stale.
        _set_state(job_id, state="finalizing", units_done=4)
        projected = project_stage(document_id)
        _merge_stage_detail(job_id, neo4j_edges=projected)

        _set_state(job_id, state="succeeded", units_done=5, units_total=5)
    except Exception as exc:  # noqa: BLE001 -- the job row is the error channel
        logger.exception("ingest job %s failed", job_id)
        _set_state(job_id, state="failed", error=f"{type(exc).__name__}: {exc}")
        # The course must move too. `course.status` is set to "ingesting" at
        # upload and to "ready" only inside `persist_graph`, so failing the job
        # alone left the course claiming to be ingesting for ever, with the UI
        # showing a spinner over a job that died minutes ago.
        _fail_course(job_id)
        raise

    return "succeeded"


def parse_stage(document_id: uuid.UUID) -> StageResult:
    with sync_session() as session:
        return parse_document(session, document_id)


def chunk_stage(document_id: uuid.UUID) -> StageResult:
    with sync_session() as session:
        return chunk_document(session, document_id)


def embed_stage(document_id: uuid.UUID) -> StageResult:
    with sync_session() as session:
        return embed_document(session, document_id)


def extract_stage(document_id: uuid.UUID) -> StageResult:
    with sync_session() as session:
        return extract_graph(session, document_id)


def project_stage(document_id: uuid.UUID) -> int:
    """Mirror the committed graph into Neo4j.

    Deliberately swallows its own failure: the projection is derived data, the
    read path detects staleness and falls back to Postgres, and failing a
    completed ingest because a read-model was briefly unavailable would be the
    wrong call.
    """
    with sync_session() as session:
        document = session.get(Document, document_id)
        if document is None:
            return 0
        try:
            return project_course(session, document.course_id)
        except Exception as exc:  # noqa: BLE001 -- derived store; never fails the ingest
            logger.warning("neo4j projection failed for course %s: %s", document.course_id, exc)
            return 0

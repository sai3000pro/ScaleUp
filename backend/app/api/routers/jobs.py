from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.course import IngestAccepted
from app.schemas.job import IngestJobOut
from app.services import admin_service, ingest_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=IngestJobOut)
async def get_job(job_id: uuid.UUID, user: CurrentUser, session: DbSession) -> IngestJobOut:
    """Poll target for ingest progress.

    Stateless and idempotent by design: it survives a page refresh, needs no
    sticky routing, and costs ~1.5s of latency on a job measured in minutes.

    Serves both job kinds. `document_id` is null for a `reindex`, which spans
    every document in the course.
    """
    return await ingest_service.get_job(session, job_id, user.id)


@router.post("/{job_id}/retry", response_model=IngestAccepted, status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: uuid.UUID, user: CurrentUser, session: DbSession) -> IngestAccepted:
    """Retry a failed document ingest from the source already stored on the server."""
    return await ingest_service.retry_job(session, job_id, user.id)


@router.post("/{job_id}/cancel", response_model=IngestJobOut)
async def cancel_job(job_id: uuid.UUID, user: CurrentUser, session: DbSession) -> IngestJobOut:
    """Ask a running or queued job to stop. 409 if it has already finished.

    **Cooperative, not pre-emptive.** This flips the job row; the worker notices
    at its next stage boundary. A queued job therefore never starts at all, while
    a running one completes the stage it is in and stops before the next. See
    `services.admin_service.cancel_job`.
    """
    return await admin_service.cancel_job(session, job_id, user.id)

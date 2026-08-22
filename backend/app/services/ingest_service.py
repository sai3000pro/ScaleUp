"""Document upload, deduplication, and job creation.

Three layers of idempotency, per docs/archive/graph_extraction_contract.md:
  request  -- documents unique on (course_id, content_sha256)
  job      -- ingest_jobs unique on a key derived from user+course+content+pipeline
  task     -- every task upserts on a natural key, so redelivery is a no-op
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.ingestion.fetch import UrlFetchError, fetch_url
from app.ingestion.parsers.detect import sniff_source_type
from app.ingestion.parsers.html import document_title
from app.ingestion.parsers.registry import SUPPORTED_SOURCE_TYPES, storage_extension
from app.models import Chunk, Course, Document, IngestJob
from app.schemas.course import DocumentSummary, IngestAccepted
from app.schemas.job import IngestJobOut
from app.services.object_storage import storage_exists, store_payload

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB -- a 1000-page scanned PDF fits
UPLOAD_READ_CHUNK = 1024 * 1024


# @spec CURR-JOB-004
def _idempotency_key(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_sha: str,
    pipeline_version: str,
    attempt: int = 0,
) -> str:
    """Layer 2 of the three-layer idempotency described in the module docstring.

    `attempt` exists so a RETRY of a failed ingest can be enqueued at all. The
    key is deterministic in the same material, so two concurrent uploads of the
    same bytes still collapse to one job -- but a second attempt at content that
    previously failed must not collide with the dead job's key, or the unique
    constraint turns "retry" into a 500.
    """
    material = f"{user_id}:{course_id}:{content_sha}:{pipeline_version}"
    if attempt:
        material = f"{material}:retry{attempt}"
    return hashlib.sha256(material.encode()).hexdigest()


async def _existing_acceptance(session: AsyncSession, course: Course, content_sha: str) -> IngestAccepted:
    """The dedupe response for content another request has already committed."""
    document = await session.scalar(
        select(Document).where(Document.course_id == course.id, Document.content_sha256 == content_sha)
    )
    if document is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That upload conflicted; please retry.")

    job = await session.scalar(
        select(IngestJob).where(IngestJob.document_id == document.id).order_by(IngestJob.created_at.desc())
    )
    if job is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That upload conflicted; please retry.")

    return IngestAccepted(document=await _summarise(session, document), job_id=job.id, deduplicated=True)


async def _read_capped(upload: UploadFile) -> bytes:
    """Read the body, refusing to hold more than the cap in memory.

    The previous version did `await upload.read()` and compared the length
    afterwards -- which is a memory limit enforced only after the memory has
    been spent. A 4 GB upload was rejected with a 413 having already been
    buffered in full.

    Content-Length is checked first as a courtesy so an oversized upload fails
    before transfer, but it is client-supplied and cannot be trusted, so the
    streaming cap below is what actually holds the line.
    """
    declared = upload.size
    if declared is not None and declared > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds the 200 MB limit.")

    chunks: list[bytes] = []
    total = 0
    while True:
        block = await upload.read(UPLOAD_READ_CHUNK)
        if not block:
            break
        total += len(block)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds the 200 MB limit.")
        chunks.append(block)

    payload = b"".join(chunks)
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    return payload


def _detect_or_415(payload: bytes) -> str:
    """Decide the format from the bytes, or refuse.

    Sniffed rather than taken from the filename, the client's content type, or
    a remote server's -- all three are supplied by someone else, and this value
    selects the parser and is written to the database.
    """
    source_type = sniff_source_type(payload)
    if source_type is None or source_type not in SUPPORTED_SOURCE_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only PDF and HTML sources can be ingested.",
        )
    return source_type


async def _accept(
    session: AsyncSession,
    course: Course,
    user_id: uuid.UUID,
    payload: bytes,
    *,
    source_type: str,
    filename: str,
    source_uri: str | None = None,
) -> IngestAccepted:
    """Store the bytes, create or reuse the Document, and queue a job.

    Shared by the upload and URL paths because everything after "we have the
    bytes" is identical -- and because the three layers of idempotency in the
    module docstring are keyed on content, so they must not be re-implemented
    per entry point and drift.
    """
    settings = get_settings()
    content_sha = hashlib.sha256(payload).hexdigest()

    existing = await session.scalar(
        select(Document).where(Document.course_id == course.id, Document.content_sha256 == content_sha)
    )
    if existing is not None:
        job = await session.scalar(
            select(IngestJob).where(IngestJob.document_id == existing.id).order_by(IngestJob.created_at.desc())
        )
        # Dedupe on success, re-enqueue on failure. Returning the old job
        # regardless of state made a failed ingest permanently unrecoverable:
        # the content hash matches for ever, so every re-upload handed back the
        # same failed job id, while `course.status` sat at "ingesting". The only
        # escape was to create a new course. Idempotency is still honoured where
        # it means something -- re-uploading a book that ingested fine does not
        # ingest it twice.
        if job is not None and job.state != "failed":
            return IngestAccepted(
                document=await _summarise(session, existing),
                job_id=job.id,
                deduplicated=True,
            )

    # Content-addressed storage: identical bytes occupy one file regardless of
    # how many courses reference them. The extension follows the sniffed format,
    # not the filename -- it is documentation for whoever opens the upload
    # directory by hand, and a .pdf full of markup is worse than no extension.
    storage_path = await run_in_threadpool(
        store_payload,
        payload,
        content_sha,
        storage_extension(source_type),
    )

    document = existing or Document(
        course_id=course.id,
        source_type=source_type,
        filename=filename,
        source_uri=source_uri,
        content_sha256=content_sha,
        storage_path=str(storage_path),
        byte_size=len(payload),
    )
    session.add(document)
    await session.flush()

    # Every prior job for this document is a prior attempt, so the count is the
    # retry ordinal. Zero on a first upload, which keeps the original key shape.
    attempt = await session.scalar(
        select(func.count()).select_from(IngestJob).where(IngestJob.document_id == document.id)
    )
    job = IngestJob(
        course_id=course.id,
        document_id=document.id,
        idempotency_key=_idempotency_key(
            user_id, course.id, content_sha, settings.pipeline_version, attempt or 0
        ),
        state="queued",
        pipeline_version=settings.pipeline_version,
    )
    session.add(job)

    course.status = "ingesting"
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent upload of the same bytes won the race to
        # (course_id, content_sha256). The constraint held, so the data is
        # correct -- but returning a 500 broke the documented `deduplicated`
        # contract for the exact case it was written for.
        await session.rollback()
        return await _existing_acceptance(session, course, content_sha)
    await session.refresh(document)
    await session.refresh(job)

    # Enqueue only after the commit. Enqueueing first races the worker against
    # our own transaction, and the task can look up a job that does not exist yet.
    from app.tasks.ingest import run_ingest_pipeline

    async_result = run_ingest_pipeline.delay(str(job.id))
    job.celery_root_id = async_result.id
    await session.commit()

    return IngestAccepted(document=await _summarise(session, document), job_id=job.id, deduplicated=False)


# @spec CURR-SOURCE-001, CURR-SOURCE-002, CURR-SOURCE-006
async def upload_document(
    session: AsyncSession,
    course: Course,
    user_id: uuid.UUID,
    upload: UploadFile,
) -> IngestAccepted:
    payload = await _read_capped(upload)
    source_type = _detect_or_415(payload)

    fallback = f"{hashlib.sha256(payload).hexdigest()[:12]}{storage_extension(source_type)}"
    return await _accept(
        session,
        course,
        user_id,
        payload,
        source_type=source_type,
        filename=upload.filename or fallback,
    )


# @spec CURR-SOURCE-003, CURR-SOURCE-006
async def ingest_url(
    session: AsyncSession,
    course: Course,
    user_id: uuid.UUID,
    url: str,
) -> IngestAccepted:
    """Fetch a web page and queue it, exactly as if it had been uploaded.

    **The fetch happens here, before the Document row exists**, and it cannot be
    moved into the Celery task. `content_sha256` and `byte_size` are NOT NULL and
    the `(course_id, content_sha256)` unique constraint is the outermost of the
    three idempotency layers, so a row cannot be written first and filled in
    later. The cost is that this endpoint blocks for as long as the fetch takes
    -- bounded by `url_fetch_timeout_seconds`, and run off the event loop so it
    does not stall the API while it waits.

    **Dedupe is on the bytes, never the URL.** `?utm_source=` and a trailing
    slash are the same page, and normalising a URL well enough to say so is a
    losing game. `source_uri` therefore carries the URL as *provenance*, not
    identity.

    The honest wart in that: HTML is rarely byte-stable. A page with a rotating
    ad slot, a "3 minutes ago" timestamp, or a CSRF token in a meta tag hashes
    differently on every fetch, so re-ingesting the same URL usually creates a
    second document rather than deduplicating. The alternative -- dedupe on a
    normalised URL -- trades that for silently refusing to re-read a page that
    genuinely changed, which is worse for a study tool.
    """
    try:
        fetched = await run_in_threadpool(fetch_url, url)
    except UrlFetchError as exc:
        # 400, not 502: from the caller's side every one of these is "that URL
        # is not something this app will read", and distinguishing "we refused"
        # from "the site was down" would leak which internal addresses exist.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    source_type = _detect_or_415(fetched.payload)

    title = document_title(fetched.payload) if source_type == "html" else None
    return await _accept(
        session,
        course,
        user_id,
        fetched.payload,
        source_type=source_type,
        filename=(title or fetched.url)[:400],
        source_uri=fetched.url,
    )


async def _summarise(session: AsyncSession, document: Document) -> DocumentSummary:
    chunk_count = (
        await session.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == document.id)) or 0
    )
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        source_type=document.source_type,
        source_uri=document.source_uri,
        page_count=document.page_count,
        chunk_count=chunk_count,
        created_at=document.created_at,
    )


# @spec CURR-JOB-003
async def get_job(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> IngestJobOut:
    job = await session.get(IngestJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    course = await session.get(Course, job.course_id)
    if course is None or course.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    percent = 0.0
    if job.units_total > 0:
        percent = round(100.0 * job.units_done / job.units_total, 1)
    elif job.state == "succeeded":
        percent = 100.0

    return IngestJobOut(
        id=job.id,
        document_id=job.document_id,
        course_id=job.course_id,
        state=job.state,
        units_done=job.units_done,
        units_total=job.units_total,
        percent=percent,
        stage_detail=job.stage_detail or {},
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def retry_job(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> IngestAccepted:
    """Retry a failed document ingest from its content-addressed storage.

    Retrying here, instead of asking the browser to upload the source again, is
    important for both entry points: a local file can be up to 200 MB, and a URL
    may return different bytes on its next fetch. The stored document is the
    exact input that failed, so the new job remains tied to the same document and
    content hash.
    """
    failed = await session.get(IngestJob, job_id)
    if failed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    course = await session.get(Course, failed.course_id)
    if course is None or course.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    if failed.kind != "ingest" or failed.document_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only document ingestion jobs can be retried.")
    if failed.state != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is {failed.state}; only failed jobs can be retried.")

    document = await session.get(Document, failed.document_id)
    if document is None or document.course_id != course.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "The source document does not belong to this course.")
    if not await run_in_threadpool(storage_exists, document.storage_path):
        raise HTTPException(status.HTTP_409_CONFLICT, "The stored source is no longer available; upload it again.")

    # A learner may keep an old failed-job tab open after a retry succeeded or
    # failed again. Do not create a third run from that stale job; make the
    # newest attempt the canonical one the UI should watch.
    latest = await session.scalar(
        select(IngestJob)
        .where(IngestJob.document_id == document.id)
        .order_by(IngestJob.created_at.desc(), IngestJob.id.desc())
    )
    if latest is not None and latest.id != failed.id:
        return IngestAccepted(document=await _summarise(session, document), job_id=latest.id, deduplicated=True)

    settings = get_settings()
    attempt = await session.scalar(
        select(func.count()).select_from(IngestJob).where(IngestJob.document_id == document.id)
    )
    retry = IngestJob(
        course_id=course.id,
        document_id=document.id,
        kind="ingest",
        idempotency_key=_idempotency_key(
            user_id, course.id, document.content_sha256, settings.pipeline_version, attempt or 0
        ),
        state="queued",
        pipeline_version=settings.pipeline_version,
    )
    session.add(retry)
    course.status = "ingesting"

    try:
        await session.commit()
    except IntegrityError:
        # A second click or two browser tabs may race. The unique key means only
        # one retry wins; return the newest job rather than turning that race into
        # a 500.
        await session.rollback()
        current = await session.scalar(
            select(IngestJob)
            .where(IngestJob.document_id == document.id)
            .order_by(IngestJob.created_at.desc(), IngestJob.id.desc())
        )
        if current is None or current.id == failed.id:
            raise
        return IngestAccepted(document=await _summarise(session, document), job_id=current.id, deduplicated=True)

    await session.refresh(retry)

    from app.tasks.ingest import run_ingest_pipeline

    try:
        async_result = run_ingest_pipeline.delay(str(retry.id))
    except Exception as exc:  # noqa: BLE001 -- the queue is the retry operation's dependency
        retry.state = "failed"
        retry.error = f"QueueError: {exc}"
        await session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The ingest queue is unavailable; try again.") from exc

    retry.celery_root_id = async_result.id
    await session.commit()

    return IngestAccepted(document=await _summarise(session, document), job_id=retry.id, deduplicated=False)

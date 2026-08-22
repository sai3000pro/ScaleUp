"""Preserved original takes: content-addressed, owned, deletable.

The browser sends the raw recording bytes (base64 in the wire contract); this
service stores them once per (user, content sha256), links them to an attempt
when the submission names them, and enforces owner-only read and delete.
Storing the bytes in Postgres keeps the demo self-contained -- these are short
clips, not a media library -- and the sha256 primary key gives dedupe the same
recovery shape as voice artifacts: a concurrent duplicate insert is re-read as
the winner.
"""

from __future__ import annotations

import base64
import hashlib
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Recording, User
from app.schemas.performance import RecordingCreate, RecordingOut

# Short practice clips: a 30-second WebM/opus take is a few hundred KB. The cap
# protects the demo from a misbehaving client, not from legitimate recordings.
MAX_RECORDING_BYTES = 20 * 1024 * 1024

# Recording container format -> media type for the content endpoint.
MEDIA_TYPES = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
}


# @spec CAP-TAKE-002
def decode_recording_content(content_base64: str) -> bytes:
    """Validate and decode the wire payload into raw bytes.

    Pure enough to unit-test offline: rejects invalid base64, empty content,
    and oversized takes before anything touches the database.
    """
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Recording content is not valid base64.") from exc
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Recording content must not be empty.")
    if len(content) > MAX_RECORDING_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Recording exceeds the size limit.")
    return content


def _out(recording: Recording, deduplicated: bool) -> RecordingOut:
    return RecordingOut(
        id=recording.id,
        course_id=recording.course_id,
        attempt_id=recording.attempt_id,
        format=recording.format,
        byte_size=recording.byte_size,
        content_sha256=recording.content_sha256,
        duration_seconds=recording.duration_seconds,
        created_at=recording.created_at,
        deduplicated=deduplicated,
    )


# @spec ACCESS-OWN-001, ACCESS-OWN-002
async def _owned(session: AsyncSession, recording_id: uuid.UUID, user: User) -> Recording:
    recording = await session.get(Recording, recording_id)
    if recording is None or recording.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found.")
    return recording


# @spec OPS-STORE-004, OPS-STORE-005, CAP-TAKE-001
async def upload_recording(
    session: AsyncSession,
    payload: RecordingCreate,
    user: User,
) -> RecordingOut:
    """Store a take once per (user, content hash); a duplicate returns the original."""
    course = await session.get(Course, payload.course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found.")

    content = decode_recording_content(payload.content_base64)

    content_sha256 = hashlib.sha256(content).hexdigest()
    existing = await session.scalar(
        select(Recording).where(Recording.user_id == user.id, Recording.content_sha256 == content_sha256)
    )
    if existing is not None:
        return _out(existing, deduplicated=True)

    recording = Recording(
        user_id=user.id,
        course_id=course.id,
        content_sha256=content_sha256,
        format=payload.format,
        byte_size=len(content),
        duration_seconds=payload.duration_seconds,
        content=content,
    )
    session.add(recording)
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent upload of the same bytes won the insert; the unique
        # (user, sha256) constraint is the dedupe mechanism, so re-read it.
        await session.rollback()
        settled = await session.scalar(
            select(Recording).where(Recording.user_id == user.id, Recording.content_sha256 == content_sha256)
        )
        if settled is None:
            raise
        return _out(settled, deduplicated=True)

    await session.refresh(recording)
    return _out(recording, deduplicated=False)


# @spec CAP-TAKE-003, CAP-TAKE-006
async def get_recording(session: AsyncSession, recording_id: uuid.UUID, user: User) -> RecordingOut:
    return _out(await _owned(session, recording_id, user), deduplicated=False)


async def get_recording_content(
    session: AsyncSession, recording_id: uuid.UUID, user: User
) -> tuple[bytes, str]:
    """Return (bytes, media type) for the owner, so the router can stream them."""
    recording = await _owned(session, recording_id, user)
    media_type = MEDIA_TYPES.get(recording.format, "application/octet-stream")
    return recording.content, media_type


# @spec ACCESS-OWN-003, CAP-TAKE-004
async def delete_recording(session: AsyncSession, recording_id: uuid.UUID, user: User) -> None:
    recording = await _owned(session, recording_id, user)
    await session.delete(recording)
    await session.commit()

"""Owner-scoped original takes: upload, metadata, content, delete.

The raw audio a practice take was scored from is preserved here so the demo can
replay it and the attempt can cite its evidence. Uploads are content-addressed
per user (an identical take is stored once), metadata and content are separate
endpoints so replay can stream bytes without hauling them through a JSON
payload, and the owner can delete a take at any time.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.performance import RecordingCreate, RecordingOut
from app.services import recording_service

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


@router.post("", response_model=RecordingOut, status_code=status.HTTP_201_CREATED)
async def upload_recording(
    payload: RecordingCreate,
    user: CurrentUser,
    session: DbSession,
) -> RecordingOut:
    return await recording_service.upload_recording(session, payload, user)


@router.get("/{recording_id}", response_model=RecordingOut)
async def get_recording(
    recording_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> RecordingOut:
    return await recording_service.get_recording(session, recording_id, user)


@router.get("/{recording_id}/content")
async def get_recording_content(
    recording_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    content, media_type = await recording_service.get_recording_content(session, recording_id, user)
    return Response(content=content, media_type=media_type)


@router.delete("/{recording_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recording(
    recording_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    await recording_service.delete_recording(session, recording_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

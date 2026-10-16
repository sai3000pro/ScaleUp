"""The retention policy, and the one operation that applies it.

Raw audio -- original takes and synthesised feedback -- is kept for
RAW_AUDIO_RETENTION_DAYS and then removed, rows and stored objects together.
Derived metrics (scores, per-note alignment, posture readings) are kept for the
life of the attempt they describe: they are the learner's progress, they hold no
media, and they leave only when their owner deletes the attempt, course or
account, which cascades. Callers choose the scheduler; the signed n8n workflow
is the supported deployment path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Recording, StoredVoiceArtifact
from app.services.recording_service import release_audio_objects

RAW_AUDIO_RETENTION_DAYS = 30

# @spec OPS-STORE-005
RETENTION_POLICY: dict[str, str] = {
    "recordings": f"deleted {RAW_AUDIO_RETENTION_DAYS} days after upload, object and row together",
    "voice_artifacts": f"deleted {RAW_AUDIO_RETENTION_DAYS} days after synthesis, object and row together",
    "derived_metrics": "kept for the life of the attempt; removed only by owner deletion, which cascades",
}


# @spec OPS-STORE-004, OPS-STORE-005
async def expire_audio(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, int | str]:
    """Delete audio older than the policy window, returning counts for the audit ledger."""
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=RAW_AUDIO_RETENTION_DAYS)
    expired_paths: set[str | None] = set(
        (await session.execute(select(Recording.storage_path).where(Recording.created_at < cutoff))).scalars()
    ) | set(
        (await session.execute(select(StoredVoiceArtifact.storage_path).where(StoredVoiceArtifact.created_at < cutoff))).scalars()
    )
    recording_ids = select(Recording.id).where(Recording.created_at < cutoff)
    recordings = await session.execute(delete(Recording).where(Recording.id.in_(recording_ids)))
    expired_artifact_keys = select(StoredVoiceArtifact.cache_key).where(StoredVoiceArtifact.created_at < cutoff)
    # The raw voice cache is audio data; its immutable feedback text is already
    # retained on the attempt, so delete only the blob artifact row.
    voice_artifacts = await session.execute(
        delete(StoredVoiceArtifact).where(StoredVoiceArtifact.cache_key.in_(expired_artifact_keys))
    )
    recordings_deleted = recordings.rowcount or 0
    voice_artifacts_deleted = voice_artifacts.rowcount or 0
    await session.flush()
    objects_released = await release_audio_objects(session, expired_paths)
    return {
        "recordings_deleted": recordings_deleted,
        "voice_artifacts_deleted": voice_artifacts_deleted,
        "objects_released": objects_released,
        "retention_days": RAW_AUDIO_RETENTION_DAYS,
        "cutoff_at": cutoff.isoformat(),
    }

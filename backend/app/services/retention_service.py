"""Retention operations for raw audio only.

Scores, feedback, attempts, metrics, and learner progress remain durable. This
service removes only original recordings and generated voice audio after the
configured policy window; callers choose the scheduler (the signed n8n workflow
is the supported deployment path).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Recording, StoredVoiceArtifact

RAW_AUDIO_RETENTION_DAYS = 30


async def expire_audio(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, int | str]:
    """Delete audio older than 30 days, returning counts for the audit ledger."""
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=RAW_AUDIO_RETENTION_DAYS)
    recording_ids = select(Recording.id).where(Recording.created_at < cutoff)
    recordings = await session.execute(delete(Recording).where(Recording.id.in_(recording_ids)))
    expired_artifact_keys = select(StoredVoiceArtifact.cache_key).where(
        StoredVoiceArtifact.created_at < cutoff
    )
    # The raw voice cache is audio data; its immutable feedback text is already
    # retained on the attempt, so delete only the blob artifact row.
    voice_artifacts = await session.execute(
        delete(StoredVoiceArtifact).where(StoredVoiceArtifact.cache_key.in_(expired_artifact_keys))
    )
    recordings_deleted = recordings.rowcount or 0
    voice_artifacts_deleted = voice_artifacts.rowcount or 0
    await session.flush()
    return {
        "recordings_deleted": recordings_deleted,
        "voice_artifacts_deleted": voice_artifacts_deleted,
        "retention_days": RAW_AUDIO_RETENTION_DAYS,
        "cutoff_at": cutoff.isoformat(),
    }

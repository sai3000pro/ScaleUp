"""Thirty-day audio retention has an explicit cutoff and touches audio rows only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Recording, StoredVoiceArtifact
from app.services import retention_service


class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Session:
    def __init__(self) -> None:
        self.statements = []
        self._results = iter((2, 3))
        self.flushed = False

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(next(self._results))

    async def flush(self) -> None:
        self.flushed = True


async def test_expire_audio_uses_thirty_day_cutoff_and_deletes_only_audio_rows() -> None:
    now = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    session = _Session()

    result = await retention_service.expire_audio(session, now=now)

    assert result["recordings_deleted"] == 2
    assert result["voice_artifacts_deleted"] == 3
    assert result["retention_days"] == 30
    assert result["cutoff_at"] == (now - timedelta(days=30)).isoformat()
    assert len(session.statements) == 2
    assert "recordings" in str(session.statements[0])
    assert "voice_artifacts" in str(session.statements[1])
    assert all("created_at" in str(statement) for statement in session.statements)
    assert session.flushed is True
    assert Recording.__tablename__ == "recordings"
    assert StoredVoiceArtifact.__tablename__ == "voice_artifacts"

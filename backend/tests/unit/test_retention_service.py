"""Thirty-day audio retention has an explicit cutoff, touches audio rows only, and
releases the stored objects those rows pointed at."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Recording, StoredVoiceArtifact
from app.services import object_storage, retention_service


class _Result:
    def __init__(self, rowcount: int = 0, rows: tuple[str | None, ...] = ()) -> None:
        self.rowcount = rowcount
        self._rows = rows

    def scalars(self):
        return iter(self._rows)


class _Session:
    """Scripted session: two path selects, two deletes, two still-held selects."""

    def __init__(self) -> None:
        self.statements = []
        self._results = iter(
            (
                _Result(rows=("/store/take-a.webm", "/store/shared.mp3")),
                _Result(rows=("/store/shared.mp3", None)),
                _Result(rowcount=2),
                _Result(rowcount=3),
                _Result(rows=()),
                _Result(rows=("/store/shared.mp3",)),
            )
        )
        self.flushed = False

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self._results)

    async def flush(self) -> None:
        self.flushed = True


# @spec OPS-STORE-005
async def test_expire_audio_uses_thirty_day_cutoff_and_deletes_only_audio_rows(monkeypatch) -> None:
    now = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    session = _Session()
    released: list[str] = []
    monkeypatch.setattr(object_storage, "delete_payload", lambda path: released.append(path) or True)

    result = await retention_service.expire_audio(session, now=now)

    assert result["recordings_deleted"] == 2
    assert result["voice_artifacts_deleted"] == 3
    assert result["retention_days"] == 30
    assert result["cutoff_at"] == (now - timedelta(days=30)).isoformat()
    deletes = [statement for statement in session.statements if str(statement).startswith("DELETE")]
    assert len(deletes) == 2
    assert "recordings" in str(deletes[0])
    assert "voice_artifacts" in str(deletes[1])
    assert all("created_at" in str(statement) for statement in session.statements[:4])
    assert session.flushed is True
    assert Recording.__tablename__ == "recordings"
    assert StoredVoiceArtifact.__tablename__ == "voice_artifacts"


# @spec OPS-STORE-004, OPS-STORE-005
async def test_expire_audio_releases_only_objects_no_row_still_holds(monkeypatch) -> None:
    session = _Session()
    released: list[str] = []
    monkeypatch.setattr(object_storage, "delete_payload", lambda path: released.append(path) or True)

    result = await retention_service.expire_audio(session)

    # shared.mp3 is still referenced by a live artifact row; take-a.webm is not.
    assert released == ["/store/take-a.webm"]
    assert result["objects_released"] == 1


# @spec OPS-STORE-005
def test_retention_policy_names_every_retained_class() -> None:
    policy = retention_service.RETENTION_POLICY
    assert set(policy) == {"recordings", "voice_artifacts", "derived_metrics"}
    assert str(retention_service.RAW_AUDIO_RETENTION_DAYS) in policy["recordings"]
    assert "owner deletion" in policy["derived_metrics"]

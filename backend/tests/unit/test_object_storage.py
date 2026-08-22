from pathlib import Path

import pytest

from app.config import Settings
from app.services import object_storage


class FakeBlob:
    def __init__(self, objects: dict[str, bytes], key: str) -> None:
        self.objects = objects
        self.key = key

    def exists(self) -> bool:
        return self.key in self.objects

    def upload_from_string(self, payload: bytes, *, content_type: str) -> None:
        assert content_type in {"application/pdf", "text/html; charset=utf-8"}
        self.objects[self.key] = payload

    def download_to_filename(self, filename: str) -> None:
        Path(filename).write_bytes(self.objects[self.key])


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def blob(self, key: str) -> FakeBlob:
        return FakeBlob(self.objects, key)


def test_deployed_settings_reject_ephemeral_uploads() -> None:
    with pytest.raises(ValueError, match="STORAGE_BACKEND must be gcs"):
        Settings(
            deployed=True,
            jwt_secret="a-real-secret",
            email_provider="resend",
            google_oauth_client_id="client-id",
            google_oauth_client_secret="client-secret",
            storage_backend="local",
        )


def test_local_storage_writes_content_addressed_file(tmp_path, monkeypatch) -> None:
    settings = Settings(upload_dir=tmp_path)
    monkeypatch.setattr(object_storage, "get_settings", lambda: settings)

    storage_path = object_storage.store_payload(b"pdf-bytes", "a" * 64, ".pdf")

    assert Path(storage_path).read_bytes() == b"pdf-bytes"
    assert object_storage.storage_exists(storage_path)
    assert object_storage.materialize_storage_path(storage_path) == storage_path


def test_gcs_storage_uploads_and_materializes_for_parsers(monkeypatch, tmp_path) -> None:
    settings = Settings(storage_backend="gcs", gcs_bucket="study-bucket", gcs_prefix="sources")
    bucket = FakeBucket()
    monkeypatch.setattr(object_storage, "get_settings", lambda: settings)
    monkeypatch.setattr(object_storage, "_gcs_bucket", lambda: bucket)
    monkeypatch.setattr(object_storage.tempfile, "gettempdir", lambda: str(tmp_path))

    storage_path = object_storage.store_payload(b"html-bytes", "b" * 64, ".html")

    assert storage_path == "gs://study-bucket/sources/" + "b" * 64 + ".html"
    assert object_storage.storage_exists(storage_path)
    local_path = object_storage.materialize_storage_path(storage_path)
    assert Path(local_path).read_bytes() == b"html-bytes"
    assert object_storage.materialize_storage_path(storage_path) == local_path

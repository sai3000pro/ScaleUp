"""Source-byte storage with a local development fallback.

The ingestion pipeline needs a filesystem path because PyMuPDF and the HTML
parser consume paths. In production, the authoritative bytes live in GCS and
are materialized into the worker's ephemeral filesystem only while a stage uses
them. Local storage remains the default so tests and Docker development need no
cloud credentials.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings


class StorageConfigurationError(RuntimeError):
    """The selected storage backend is not configured correctly."""


def _gcs_bucket():
    settings = get_settings()
    if not settings.gcs_bucket:
        raise StorageConfigurationError("GCS_BUCKET is required when STORAGE_BACKEND=gcs")
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - exercised only in a misbuilt cloud image
        raise StorageConfigurationError("google-cloud-storage is required when STORAGE_BACKEND=gcs") from exc
    return storage.Client().bucket(settings.gcs_bucket)


def _object_key(content_sha: str, extension: str) -> str:
    settings = get_settings()
    prefix = settings.gcs_prefix.strip("/")
    filename = f"{content_sha}{extension}"
    return f"{prefix}/{filename}" if prefix else filename


def _gcs_uri(key: str) -> str:
    settings = get_settings()
    return f"gs://{settings.gcs_bucket}/{key}"


# @spec OPS-STORE-001, OPS-STORE-002, OPS-STORE-004
def store_payload(payload: bytes, content_sha: str, extension: str) -> str:
    """Persist content and return its stable storage identifier."""
    settings = get_settings()
    if settings.storage_backend == "local":
        path = settings.resolved_upload_dir() / f"{content_sha}{extension}"
        if not path.exists():
            path.write_bytes(payload)
        return str(path)
    if settings.storage_backend == "gcs":
        key = _object_key(content_sha, extension)
        blob = _gcs_bucket().blob(key)
        if not blob.exists():
            blob.upload_from_string(payload, content_type=_content_type(extension))
        return _gcs_uri(key)
    raise StorageConfigurationError(f"Unsupported STORAGE_BACKEND={settings.storage_backend!r}")


def storage_exists(storage_path: str) -> bool:
    """Return whether a persisted source is available to a worker."""
    if storage_path.startswith("gs://"):
        parsed = urlparse(storage_path)
        if parsed.netloc != get_settings().gcs_bucket or not parsed.path.lstrip("/"):
            return False
        return _gcs_bucket().blob(parsed.path.lstrip("/")).exists()
    return Path(storage_path).is_file()


# @spec OPS-STORE-002
def materialize_storage_path(storage_path: str) -> str:
    """Return a parser-readable local path, downloading GCS objects when needed."""
    if not storage_path.startswith("gs://"):
        return storage_path

    parsed = urlparse(storage_path)
    key = parsed.path.lstrip("/")
    if parsed.netloc != get_settings().gcs_bucket or not key:
        raise StorageConfigurationError(f"Invalid GCS storage path: {storage_path!r}")

    suffix = Path(key).suffix or ".bin"
    cache_name = hashlib.sha256(storage_path.encode("utf-8")).hexdigest() + suffix
    cache_dir = Path(tempfile.gettempdir()) / "learn-anything-storage-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / cache_name
    if not target.exists():
        partial = target.with_suffix(target.suffix + ".part")
        _gcs_bucket().blob(key).download_to_filename(str(partial))
        os.replace(partial, target)
    return str(target)


def _content_type(extension: str) -> str:
    if extension == ".pdf":
        return "application/pdf"
    if extension == ".html":
        return "text/html; charset=utf-8"
    return "application/octet-stream"

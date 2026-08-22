"""Offline-testable pieces of the preserved-take boundary.

The full upload/dedupe/ownership lifecycle needs a database, so it lives in the
Postgres integration suite; the decode gate is pure and covered here.
"""

from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from app.services.recording_service import MEDIA_TYPES, decode_recording_content


def test_decode_accepts_valid_base64() -> None:
    payload = base64.b64encode(b"RIFF....WAVE").decode()
    assert decode_recording_content(payload) == b"RIFF....WAVE"


def test_decode_rejects_invalid_base64() -> None:
    with pytest.raises(HTTPException) as exc:
        decode_recording_content("not base64!!!")
    assert exc.value.status_code == 400
    assert "not valid base64" in exc.value.detail


def test_decode_rejects_empty_content() -> None:
    with pytest.raises(HTTPException) as exc:
        decode_recording_content(base64.b64encode(b"").decode())
    assert exc.value.status_code == 400
    assert "must not be empty" in exc.value.detail


def test_decode_rejects_oversized_content() -> None:
    oversized = b"x" * (20 * 1024 * 1024 + 1)
    with pytest.raises(HTTPException) as exc:
        decode_recording_content(base64.b64encode(oversized).decode())
    assert exc.value.status_code == 413
    assert "size limit" in exc.value.detail


def test_media_types_cover_supported_formats() -> None:
    assert MEDIA_TYPES["webm"] == "audio/webm"
    assert MEDIA_TYPES["wav"] == "audio/wav"
    # The browser's MediaRecorder captures webm; the mapping must include it.
    assert "webm" in MEDIA_TYPES

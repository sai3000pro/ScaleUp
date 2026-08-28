"""Unit tests for Gemini Live real-time coaching integration."""

from __future__ import annotations

import uuid

import pytest

from app.schemas.coach import CoachLiveTipRequest
from app.services.coach_service import generate_live_tip
from app.services.gemini_live_service import GeminiLiveCoachSession, generate_gemini_tip


@pytest.mark.asyncio
async def test_gemini_session_inactive_without_key(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    try:
        session = GeminiLiveCoachSession(
            instrument="piano",
            exercise_title="C Major Scale",
            tempo_bpm=60,
        )
        assert not session.is_active

        connected = await session.connect()
        assert not connected
        assert not session.is_active
    finally:
        get_settings.cache_clear()

    # Methods should be safe no-ops when inactive
    await session.send_audio_chunk(b"\x00" * 320)
    await session.send_text_context("C4 note played")
    await session.close()
    assert not session.is_active


@pytest.mark.asyncio
async def test_generate_gemini_tip_graceful_offline():
    tip = await generate_gemini_tip(
        instrument="guitar",
        exercise_title="Low E Fretting",
        tempo_bpm=60,
        current_note="E2",
        signed_timing_bias_seconds=-0.04,
        mean_pitch_error_semitones=0.1,
    )
    # With no API key in default test environment, it safely returns None
    assert tip is None or isinstance(tip, dict)


@pytest.mark.asyncio
async def test_generate_live_tip_returns_actionable_response():
    req = CoachLiveTipRequest(
        exercise_title="Stepwise C Major",
        instrument="piano",
        tempo_bpm=60,
        current_note="C4",
        signed_timing_bias_seconds=-0.08,
        mean_pitch_error_semitones=0.02,
    )
    res = await generate_live_tip(uuid.uuid4(), req)
    assert res.focus_area != ""
    assert res.tip != ""
    assert res.suggested_action != ""
    assert "rushing" in res.focus_area.lower() or "rhythm" in res.focus_area.lower()

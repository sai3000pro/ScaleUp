"""The voice boundary is testable with zero keys and never blocks a result."""

from __future__ import annotations

import struct

import pytest

from app.services.voice import (
    WAV_SAMPLE_RATE,
    ElevenLabsVoiceProvider,
    FakeVoiceProvider,
    VoiceArtifact,
    cache_key_for,
    synthesize_feedback,
)

TEXT = "Stepwise C Major was a clean run. Next: raise the tempo."


async def test_fake_voice_provider_emits_a_valid_silence_wav() -> None:
    content = await FakeVoiceProvider().synthesize(TEXT, voice_key="professor-cadenza")

    assert content.startswith(b"RIFF")
    assert content[8:12] == b"WAVE"
    assert content[12:16] == b"fmt "
    channels, sample_rate = struct.unpack_from("<HI", content, 22)
    assert channels == 1
    assert sample_rate == WAV_SAMPLE_RATE
    assert content.endswith(b"\x00\x00")


async def test_synthesize_feedback_with_fake_provider_returns_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "voice_provider", "fake")
    artifact = await synthesize_feedback(TEXT, voice_key="professor-cadenza")

    assert isinstance(artifact, VoiceArtifact)
    assert artifact.provider == "fake"
    assert artifact.format == "wav"
    assert artifact.content
    assert artifact.spoken_text == TEXT


def test_cache_key_is_deterministic_and_content_addressed() -> None:
    assert cache_key_for(TEXT, "professor-cadenza") == cache_key_for(TEXT, "professor-cadenza")
    assert cache_key_for(TEXT, "professor-cadenza") != cache_key_for(TEXT, "other-voice")
    assert cache_key_for(TEXT, "professor-cadenza") != cache_key_for("different text", "professor-cadenza")


async def test_elevenlabs_provider_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services import voice as voice_module

    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        await ElevenLabsVoiceProvider("").synthesize(TEXT, voice_key="professor-cadenza")

    class BrokenProvider:
        provider = "broken"

        async def synthesize(self, text: str, *, voice_key: str) -> bytes:
            raise RuntimeError("provider down")

    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.setattr(get_settings(), "voice_provider", "elevenlabs")
    monkeypatch.setattr(voice_module, "_provider_for", lambda _name: BrokenProvider())
    artifact = await synthesize_feedback(TEXT, voice_key="professor-cadenza")

    assert artifact.provider == "unavailable"
    assert artifact.format == "text"
    assert artifact.content == b""
    assert artifact.spoken_text == TEXT

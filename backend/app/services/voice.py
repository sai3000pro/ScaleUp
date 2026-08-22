"""Voice provider boundary for examiner feedback.

Text feedback always works; audio is an optional upgrade. The fake provider
emits a deterministic, valid silence WAV so the whole pipeline is exercisable
with no keys, and the response always carries the spoken text so the frontend
can fall back to browser TTS when no provider is configured. A synthesis
failure never invalidates a score or an EXP award -- it only degrades the
delivery, which is why the service layer swallows provider errors here rather
than letting them surface as a 500 next to a perfectly good attempt.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

WAV_SAMPLE_RATE = 22050
WAV_CHANNELS = 1
WAV_BITS_PER_SAMPLE = 16
# Short silence: enough to prove the plumbing end to end, nothing to listen to.
WAV_SILENCE_SECONDS = 0.05

# ElevenLabs voices are referenced by id, not name. This is the shared
# "Rachel" voice used in most examples; it can be overridden per call with a
# different voice_key.
DEFAULT_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"


def _silence_wav() -> bytes:
    """A minimal, valid PCM WAV containing only silence.

    Deterministic, so the fake's artifact is stable across calls and tests can
    assert on the exact bytes and header fields.
    """
    sample_count = int(WAV_SAMPLE_RATE * WAV_SILENCE_SECONDS)
    data_size = sample_count * WAV_CHANNELS * (WAV_BITS_PER_SAMPLE // 8)
    byte_rate = WAV_SAMPLE_RATE * WAV_CHANNELS * (WAV_BITS_PER_SAMPLE // 8)
    block_align = WAV_CHANNELS * (WAV_BITS_PER_SAMPLE // 8)

    header = b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, WAV_CHANNELS, WAV_SAMPLE_RATE, byte_rate, block_align, WAV_BITS_PER_SAMPLE)
    header += b"data" + struct.pack("<I", data_size)
    return header + b"\x00\x00" * sample_count


@dataclass(frozen=True, slots=True)
class VoiceArtifact:
    provider: str
    voice_key: str
    format: str
    content: bytes
    cache_key: str
    spoken_text: str


class VoiceProvider(Protocol):
    provider: str

    async def synthesize(self, text: str, *, voice_key: str) -> bytes:
        """Return audio bytes for `text`. Raises on any provider failure."""
        ...


class FakeVoiceProvider:
    """Deterministic, key-free. Emits a valid silence WAV."""

    provider = "fake"

    async def synthesize(self, text: str, *, voice_key: str) -> bytes:
        return _silence_wav()


class ElevenLabsVoiceProvider:
    """The real provider, behind the same boundary. Requires an API key."""

    provider = "elevenlabs"

    def __init__(self, api_key: str, base_url: str = "https://api.elevenlabs.io/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def synthesize(self, text: str, *, voice_key: str) -> bytes:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured.")
        voice_id = voice_key or get_settings().elevenlabs_voice_id or DEFAULT_ELEVENLABS_VOICE_ID
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base_url}/text-to-speech/{voice_id}",
                headers={"xi-api-key": self._api_key, "Accept": "audio/mpeg"},
                json={
                    "text": text,
                    "model_id": get_settings().elevenlabs_model_id,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
            response.raise_for_status()
            return response.content


def _provider_for(name: str) -> VoiceProvider:
    if name == "elevenlabs":
        settings = get_settings()
        return ElevenLabsVoiceProvider(settings.elevenlabs_api_key)
    return FakeVoiceProvider()


# @spec COACH-VOICE-004
def cache_key_for(text: str, voice_key: str) -> str:
    """Content-addressed key: identical text + voice always map to one key.

    The eventual voice artifact store keys rows on this so repeat requests are
    served without a second paid synthesis call.
    """
    return hashlib.sha256(f"{voice_key}|{text}".encode("utf-8")).hexdigest()


# @spec COACH-VOICE-001, COACH-VOICE-002, COACH-VOICE-003, COACH-VOICE-005
async def synthesize_feedback(text: str, *, voice_key: str = "") -> VoiceArtifact:
    """Synthesize `text` with the configured provider, falling back to text-only.

    Never raises: a provider outage must degrade delivery, not the attempt.
    """
    settings = get_settings()
    provider = _provider_for(settings.voice_provider)
    cache_key = cache_key_for(text, voice_key)
    try:
        content = await provider.synthesize(text, voice_key=voice_key)
        return VoiceArtifact(
            provider=provider.provider,
            voice_key=voice_key,
            format="wav" if provider.provider == "fake" else "mp3",
            content=content,
            cache_key=cache_key,
            spoken_text=text,
        )
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning("voice synthesis failed (%s); returning text-only feedback", exc)
        return VoiceArtifact(
            provider="unavailable",
            voice_key=voice_key,
            format="text",
            content=b"",
            cache_key=cache_key,
            spoken_text=text,
        )


# ── streaming ────────────────────────────────────────────────────────────────
#
# Added alongside the clip path rather than replacing it. `synthesize_feedback`
# and `cache_key_for` are untouched: the post-take spoken feedback must keep
# working exactly as it does, and a streaming bug must not be able to reach it.


class StreamingVoiceProvider(Protocol):
    provider: str

    def stream(self, sentences: AsyncIterator[str], *, voice_key: str) -> AsyncIterator[bytes]:
        """Yield audio chunks for each completed sentence, in order."""
        ...


class FakeStreamingVoiceProvider:
    """Deterministic streamed silence.

    Emits a WAV header first and then one PCM chunk per sentence, sized from the
    text so a longer sentence really does take longer to "speak". Concatenated,
    the chunks are a valid WAV -- which is what lets the client exercise its
    incremental append path with no keys.
    """

    provider = "fake"

    async def stream(self, sentences: AsyncIterator[str], *, voice_key: str) -> AsyncIterator[bytes]:
        del voice_key
        first = True
        async for sentence in sentences:
            samples = max(1, int(WAV_SAMPLE_RATE * min(2.0, len(sentence) / 24.0)))
            if first:
                yield _silence_wav()
                first = False
            yield b"\x00\x00" * samples


# @spec COACH-VOICE-007
class ElevenLabsStreamingVoiceProvider:
    """Real streaming, one HTTP request per completed sentence.

    Sentence-at-a-time rather than the WebSocket input API deliberately: it fits
    the same Protocol, needs no second persistent connection inside a feature
    that already has one, and the latency difference is a couple of hundred
    milliseconds against a policy that only speaks at phrase boundaries anyway.
    Swapping in the socket API later changes this class and nothing else.
    """

    provider = "elevenlabs"

    def __init__(self, api_key: str, base_url: str = "https://api.elevenlabs.io/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def stream(self, sentences: AsyncIterator[str], *, voice_key: str) -> AsyncIterator[bytes]:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured.")
        settings = get_settings()
        voice_id = voice_key or settings.elevenlabs_voice_id or DEFAULT_ELEVENLABS_VOICE_ID
        async with httpx.AsyncClient(timeout=20) as client:
            async for sentence in sentences:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/text-to-speech/{voice_id}/stream",
                    headers={"xi-api-key": self._api_key, "Accept": "audio/mpeg"},
                    json={
                        "text": sentence,
                        "model_id": settings.elevenlabs_streaming_model_id,
                        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                    },
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk


def streaming_provider_for(name: str) -> StreamingVoiceProvider:
    if name == "elevenlabs":
        return ElevenLabsStreamingVoiceProvider(get_settings().elevenlabs_api_key)
    return FakeStreamingVoiceProvider()


def streaming_audio_format(name: str) -> str:
    return "mp3" if name == "elevenlabs" else "wav"


# @spec COACH-VOICE-006, COACH-VOICE-008
async def stream_feedback(sentences: AsyncIterator[str], *, voice_key: str = "") -> AsyncIterator[bytes]:
    """Stream audio for a live cue. Never raises.

    A synthesis failure has to degrade delivery and nothing else. The text
    deltas have already reached the learner by this point, and the score is not
    computed anywhere near this code path.
    """
    provider = streaming_provider_for(get_settings().voice_provider)
    try:
        async for chunk in provider.stream(sentences, voice_key=voice_key):
            yield chunk
    except Exception as exc:  # noqa: BLE001 - delivery degrades, the take does not
        logger.warning("streamed voice synthesis failed; the learner still has the text: %s", exc)

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
        model_id = get_settings().elevenlabs_model_id or "eleven_flash_v2_5"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self._base_url}/text-to-speech/{voice_id}?optimize_streaming_latency=4&output_format=mp3_44100_64",
                headers={"xi-api-key": self._api_key, "Accept": "audio/mpeg"},
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
                },
            )
            response.raise_for_status()
            return response.content


def _pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(pcm_data)
    total_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        total_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_data


class GeminiVoiceProvider:
    """The Gemini TTS provider matching live session voice selection."""

    provider = "gemini"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def synthesize(self, text: str, *, voice_key: str) -> bytes:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        import base64
        import json
        import websockets

        voice_name = voice_key if voice_key in {"Puck", "Charon", "Kore", "Fenrir", "Aoede"} else (get_settings().gemini_live_voice or "Puck")
        url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={self._api_key}"
        async with websockets.connect(url, ping_interval=10, ping_timeout=10) as ws:
            setup_payload = {
                "setup": {
                    "model": "models/gemini-3.1-flash-live-preview",
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": voice_name
                                }
                            }
                        }
                    },
                    "systemInstruction": {
                        "parts": [{
                            "text": (
                                f"You are {voice_name}, an expert, supportive music coach and examiner. "
                                "Deliver a concise, natural, and personalized spoken debrief (2 to 3 sentences) "
                                "based on the student's performance results. Highlight their score and key strengths, "
                                "provide an actionable musical tip, and encourage them on their next step. "
                                "Sound warm, expressive, and conversational without robotic repetition."
                            )
                        }]
                    }
                }
            }
            await ws.send(json.dumps(setup_payload))
            await ws.recv()

            turn_payload = {
                "clientContent": {
                    "turns": [{
                        "role": "user",
                        "parts": [{
                            "text": (
                                f"Here are the student's performance results: {text}. "
                                "Deliver your spoken personalized debrief now."
                            )
                        }]
                    }],
                    "turnComplete": True
                }
            }
            await ws.send(json.dumps(turn_payload))

            pcm_chunks: list[bytes] = []
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                server_content = msg.get("serverContent", {})
                model_turn = server_content.get("modelTurn", {})
                for part in model_turn.get("parts", []):
                    inline = part.get("inlineData", {})
                    if inline.get("data"):
                        pcm_chunks.append(base64.b64decode(inline["data"]))
                if server_content.get("turnComplete"):
                    break

            full_pcm = b"".join(pcm_chunks)
            if not full_pcm:
                raise RuntimeError("No audio returned from Gemini Live session.")
            return _pcm16_to_wav(full_pcm, sample_rate=24000)


def _provider_for(name: str) -> VoiceProvider:
    settings = get_settings()
    if name == "gemini":
        return GeminiVoiceProvider(settings.gemini_api_key)
    if name == "elevenlabs" and settings.elevenlabs_api_key:
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
    if settings.voice_provider == "fake":
        provider: VoiceProvider = FakeVoiceProvider()
    elif voice_key in {"Puck", "Charon", "Kore", "Fenrir", "Aoede"} and settings.gemini_api_key:
        provider = GeminiVoiceProvider(settings.gemini_api_key)
    else:
        provider = _provider_for(settings.voice_provider)
    cache_key = cache_key_for(text, voice_key)
    try:
        content = await provider.synthesize(text, voice_key=voice_key)
        return VoiceArtifact(
            provider=provider.provider,
            voice_key=voice_key,
            format="wav" if provider.provider in ("fake", "gemini") else "mp3",
            content=content,
            cache_key=cache_key,
            spoken_text=text,
        )
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning("primary voice synthesis failed (%s); trying fallback", exc)
        if provider.provider != "gemini" and settings.gemini_api_key:
            try:
                gemini_fallback = GeminiVoiceProvider(settings.gemini_api_key)
                content = await gemini_fallback.synthesize(text, voice_key="Puck")
                return VoiceArtifact(
                    provider="gemini",
                    voice_key="Puck",
                    format="wav",
                    content=content,
                    cache_key=cache_key,
                    spoken_text=text,
                )
            except Exception as fallback_exc:
                logger.warning("fallback voice synthesis failed (%s)", fallback_exc)
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
        gemini_voices = {"Puck", "Charon", "Kore", "Fenrir", "Aoede"}
        if not voice_key or voice_key in gemini_voices:
            voice_id = settings.elevenlabs_voice_id or DEFAULT_ELEVENLABS_VOICE_ID
        else:
            voice_id = voice_key
        model_id = settings.elevenlabs_streaming_model_id or "eleven_flash_v2_5"
        async with httpx.AsyncClient(timeout=15) as client:
            async for sentence in sentences:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/text-to-speech/{voice_id}/stream?optimize_streaming_latency=4&output_format=mp3_44100_64",
                    headers={"xi-api-key": self._api_key, "Accept": "audio/mpeg"},
                    json={
                        "text": sentence,
                        "model_id": model_id,
                        "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
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

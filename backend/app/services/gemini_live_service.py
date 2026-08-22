"""Gemini Multimodal Live API real-time coach integration.

Enables bidirectional streaming of audio and text via Google's
`GenerativeService.BidiGenerateContent` WebSocket endpoint. When configured with
a GEMINI_API_KEY, the live coach streams the learner's raw audio directly to
Gemini 2.0 Flash Live and streams back real-time pedagogical cues and speech.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from typing import Any, AsyncIterator

import websockets

from app.config import get_settings

logger = logging.getLogger("gemini.live")

GEMINI_LIVE_WS_BASE = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"

AVAILABLE_GEMINI_VOICES = {
    "Puck": "Crisp, energetic, and engaging voice",
    "Charon": "Warm, deep, and grounding voice",
    "Kore": "Calm, natural, and supportive voice",
    "Fenrir": "Authoritative, resonant, and clear voice",
    "Aoede": "Melodic, bright, and friendly voice",
}


class GeminiLiveCoachSession:
    """Manages an active bidirectional WebSocket session with Gemini Live API."""

    def __init__(
        self,
        instrument: str,
        exercise_title: str,
        tempo_bpm: int,
        instructions: str = "",
        voice_name: str | None = None,
    ) -> None:
        settings = get_settings()
        self.instrument = instrument
        self.exercise_title = exercise_title
        self.tempo_bpm = tempo_bpm
        self.instructions = instructions
        valid_gemini_voices = {"Puck", "Charon", "Kore", "Fenrir", "Aoede"}
        if voice_name in valid_gemini_voices:
            self.voice_name = voice_name
        elif settings.gemini_live_voice in valid_gemini_voices:
            self.voice_name = settings.gemini_live_voice
        else:
            self.voice_name = "Puck"
        self._ws: websockets.ClientConnection | None = None
        self._is_ready = False

    @property
    def is_active(self) -> bool:
        return self._ws is not None and self._is_ready

    async def connect(self) -> bool:
        """Establish the WebSocket connection and perform the setup handshake."""
        settings = get_settings()
        api_key = settings.gemini_api_key.strip()
        if not api_key:
            logger.info("ℹ️ [GEMINI LIVE] API key is not configured; using deterministic live coach")
            return False

        model_name = settings.gemini_live_model.strip() or "models/gemini-3.1-flash-live-preview"
        if "gemini-2.0" in model_name:
            model_name = "models/gemini-3.1-flash-live-preview"
        elif not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        ws_url = f"{GEMINI_LIVE_WS_BASE}?key={api_key}"
        logger.info(
            "🚀 [GEMINI LIVE CONNECT] Opening bidi WebSocket stream to Gemini Live (model=%s, voice=%s, instrument=%s, tempo=%d BPM)",
            model_name,
            self.voice_name,
            self.instrument,
            self.tempo_bpm,
        )

        try:
            self._ws = await websockets.connect(
                ws_url,
                subprotocols=[],
                ping_interval=20,
                ping_timeout=20,
            )

            # Construct setup configuration optimized for real-time latency
            system_prompt = (
                f"You are an ultra-responsive, expressive real-time music coach for the {self.instrument} "
                f"practicing '{self.exercise_title}' at {self.tempo_bpm} BPM. "
                "Speed and low latency are critical. When you receive a cue or note event, immediately speak a 3 to 6 word "
                "actionable, dynamic vocal cue (e.g. 'Steady the tempo', 'Right on the beat', 'Crisp articulation', 'Breathe and reset', 'Super clean groove'). "
                "Never speak long paragraphs or give conversational intros. Maximum 6 words per utterance. "
                "Vary your phrasing each time so feedback feels dynamic, lively, and never repetitive."
            )

            gemini_voice = self.voice_name if self.voice_name in {"Puck", "Charon", "Kore", "Fenrir", "Aoede"} else "Puck"
            setup_payload = {
                "setup": {
                    "model": model_name,
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": gemini_voice
                                }
                            }
                        },
                    },
                    "systemInstruction": {
                        "parts": [{"text": system_prompt}]
                    },
                }
            }

            logger.info("📤 [GEMINI LIVE OUT] Sending setup frame with voice='%s' and model='%s'", gemini_voice, model_name)
            await self._ws.send(json.dumps(setup_payload))

            # Wait for setup acknowledgment
            ack_raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            ack_data = json.loads(ack_raw) if isinstance(ack_raw, str) else json.loads(ack_raw.decode("utf-8"))
            logger.info("📥 [GEMINI LIVE IN] Setup ACK received from Gemini: %s", ack_data)
            self._is_ready = True
            return True
        except Exception as exc:
            logger.warning("⚠️ [GEMINI LIVE ERROR] Could not establish Gemini Live session (%s); falling back to local coach", exc)
            if self._ws is not None:
                with contextlib.suppress(Exception):
                    await self._ws.close()
                self._ws = None
            self._is_ready = False
            return False

    async def send_audio_chunk(self, pcm_bytes: bytes, mime_type: str = "audio/pcm;rate=16000") -> None:
        """Stream an incoming audio chunk (PCM) to Gemini Live."""
        if not self._ws or not self._is_ready:
            return

        payload = {
            "realtimeInput": {
                "mediaChunks": [
                    {
                        "mimeType": mime_type,
                        "data": base64.b64encode(pcm_bytes).decode("ascii"),
                    }
                ]
            }
        }
        logger.info("📤 [GEMINI LIVE OUT] Sent realtime audio chunk (%d bytes PCM, mime=%s)", len(pcm_bytes), mime_type)
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:
            logger.warning("⚠️ [GEMINI LIVE ERROR] Failed to send audio chunk: %s", exc)

    async def send_text_context(self, text: str) -> None:
        """Send an updated text note / cue event to Gemini Live."""
        if not self._ws or not self._is_ready:
            return

        payload = {
            "clientContent": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": text}],
                    }
                ],
                "turnComplete": True,
            }
        }
        logger.info("📤 [GEMINI LIVE OUT] Sent text context turn: %r", text)
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:
            logger.warning("⚠️ [GEMINI LIVE ERROR] Failed to send text context: %s", exc)

    async def receive_stream(
        self,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[tuple[str, bytes | None, bool]]:
        """Yield (text_delta, audio_bytes, is_turn_complete) as Gemini responds."""
        if not self._ws or not self._is_ready:
            return

        try:
            while not (cancel_event and cancel_event.is_set()):
                raw_msg = await self._ws.recv()
                msg = json.loads(raw_msg) if isinstance(raw_msg, str) else json.loads(raw_msg.decode("utf-8"))
                server_content = msg.get("serverContent", {})
                model_turn = server_content.get("modelTurn", {})
                parts = model_turn.get("parts", [])
                turn_complete = bool(server_content.get("turnComplete", False))

                text_chunk = ""
                audio_bytes = None

                for part in parts:
                    if "text" in part:
                        text_chunk += part["text"]
                    if "inlineData" in part:
                        raw_b64 = part["inlineData"].get("data", "")
                        if raw_b64:
                            audio_bytes = base64.b64decode(raw_b64)

                if text_chunk:
                    logger.info("📥 [GEMINI LIVE IN] Text Delta: %r", text_chunk)
                if audio_bytes:
                    logger.info("📥 [GEMINI LIVE IN] Synthesized Audio Chunk (%d bytes PCM)", len(audio_bytes))
                if turn_complete:
                    logger.info("📥 [GEMINI LIVE IN] Turn Complete from Gemini Live model")

                if text_chunk or audio_bytes or turn_complete:
                    yield (text_chunk, audio_bytes, turn_complete)

                if turn_complete:
                    break
        except websockets.ConnectionClosed:
            logger.info("🛑 [GEMINI LIVE] Connection closed by server")
        except Exception as exc:
            logger.warning("⚠️ [GEMINI LIVE ERROR] Receive stream error: %s", exc)

    async def close(self) -> None:
        """Cleanly close the Gemini Live WebSocket session."""
        self._is_ready = False
        if self._ws is not None:
            logger.info("🛑 [GEMINI LIVE CLOSE] Closing Gemini Live WebSocket connection")
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None


async def generate_gemini_tip(
    instrument: str,
    exercise_title: str,
    tempo_bpm: int,
    current_note: str | None = None,
    signed_timing_bias_seconds: float | None = None,
    mean_pitch_error_semitones: float | None = None,
) -> dict[str, str] | None:
    """Query Gemini 2.0 Flash via REST for a fast, structured pedagogical tip."""
    settings = get_settings()
    api_key = settings.gemini_api_key.strip()
    if not api_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    prompt = (
        f"You are an expert {instrument} coach. The student is practicing '{exercise_title}' at {tempo_bpm} BPM.\n"
        f"Context:\n"
        f"- Current target note: {current_note or 'steady phrase'}\n"
        f"- Timing bias: {f'{signed_timing_bias_seconds:+.3f}s' if signed_timing_bias_seconds is not None else 'balanced'}\n"
        f"- Pitch deviation: {f'{mean_pitch_error_semitones:+.2f} semitones' if mean_pitch_error_semitones is not None else 'on pitch'}\n\n"
        "Return ONLY a JSON object with keys: 'tip' (1-2 sentences of encouraging, actionable guidance), "
        "'focus_area' (e.g. 'Rhythm & Pacing' or 'Finger Posture'), and 'suggested_action' (brief 4-8 word direct instruction)."
    )

    logger.info("📤 [GEMINI TIP REQUEST] Prompting Gemini 2.0 Flash for instant tip (%s at %d BPM)", instrument, tempo_bpm)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.3,
                    },
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    if text:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict) and "tip" in parsed:
                            logger.info("📥 [GEMINI TIP RESPONSE] Generated tip: %s", parsed)
                            return {
                                "tip": str(parsed.get("tip", "")),
                                "focus_area": str(parsed.get("focus_area", "Technique & Rhythm")),
                                "suggested_action": str(parsed.get("suggested_action", "Keep steady pulse.")),
                            }
    except Exception as exc:
        logger.warning("⚠️ [GEMINI TIP ERROR] Gemini tip generation failed (%s); using deterministic guidance", exc)
    return None

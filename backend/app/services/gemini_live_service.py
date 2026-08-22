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

logger = logging.getLogger(__name__)

GEMINI_LIVE_WS_BASE = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"


class GeminiLiveCoachSession:
    """Manages an active bidirectional WebSocket session with Gemini Live API."""

    def __init__(
        self,
        instrument: str,
        exercise_title: str,
        tempo_bpm: int,
        instructions: str = "",
    ) -> None:
        self.instrument = instrument
        self.exercise_title = exercise_title
        self.tempo_bpm = tempo_bpm
        self.instructions = instructions
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
            logger.info("Gemini API key is not configured; using deterministic live coach")
            return False

        ws_url = f"{GEMINI_LIVE_WS_BASE}?key={api_key}"
        try:
            self._ws = await websockets.connect(
                ws_url,
                subprotocols=[],
                ping_interval=20,
                ping_timeout=20,
            )

            # Construct setup configuration
            system_prompt = (
                f"You are a world-class real-time musical coach assisting a student practicing the {self.instrument}. "
                f"The student is playing the exercise '{self.exercise_title}' at a target tempo of {self.tempo_bpm} BPM. "
                f"Exercise Instructions: {self.instructions or 'Play smoothly with steady rhythm'}. "
                "Your job is to listen closely to their audio stream. When they make an error (such as rushing ahead of the beat, "
                "dragging behind, missing notes, or tone buzzing), speak an ultra-concise, supportive 1-sentence tip in real time. "
                "When they are playing well, give brief encouragement. Keep spoken responses under 10 words so you do not talk over them."
            )

            setup_payload = {
                "setup": {
                    "model": settings.gemini_live_model or "models/gemini-2.0-flash-exp",
                    "generationConfig": {
                        "responseModalities": ["AUDIO", "TEXT"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": "Aoede"
                                }
                            }
                        },
                    },
                    "systemInstruction": {
                        "parts": [{"text": system_prompt}]
                    },
                }
            }

            await self._ws.send(json.dumps(setup_payload))
            # Wait for setup acknowledgment
            ack_raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            ack_data = json.loads(ack_raw) if isinstance(ack_raw, str) else json.loads(ack_raw.decode("utf-8"))
            logger.info("Gemini Live session initialized: %s", ack_data)
            self._is_ready = True
            return True
        except Exception as exc:
            logger.warning("Could not establish Gemini Live session (%s); falling back to local coach", exc)
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
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:
            logger.warning("Failed to send audio chunk to Gemini Live: %s", exc)

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
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:
            logger.warning("Failed to send text context to Gemini Live: %s", exc)

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

                if text_chunk or audio_bytes or turn_complete:
                    yield (text_chunk, audio_bytes, turn_complete)

                if turn_complete:
                    break
        except websockets.ConnectionClosed:
            logger.info("Gemini Live session ended")
        except Exception as exc:
            logger.warning("Gemini Live receive stream error: %s", exc)

    async def close(self) -> None:
        """Cleanly close the Gemini Live WebSocket session."""
        self._is_ready = False
        if self._ws is not None:
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
                            return {
                                "tip": str(parsed.get("tip", "")),
                                "focus_area": str(parsed.get("focus_area", "Technique & Rhythm")),
                                "suggested_action": str(parsed.get("suggested_action", "Keep steady pulse.")),
                            }
    except Exception as exc:
        logger.warning("Gemini tip generation failed (%s); using deterministic guidance", exc)
    return None

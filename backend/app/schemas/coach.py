"""The live coaching wire protocol, `coach.v1`.

Every frame carries `v`, `type`, and a client-monotonic `seq`. The version is
negotiated in the handshake and the socket closes on a mismatch, because a
protocol that silently half-works is worse than one that refuses.

Audio rides as base64 inside JSON frames for v1. One channel, one test path, and
`VoiceArtifactOut` already ships base64 today; binary frames are an optimisation
that needs no protocol change beyond a new message type.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.schemas.performance import PerformanceAttemptOut, PerformedNoteIn

PROTOCOL_VERSION = "coach.v1"

# Close codes. Named because a bare number in a browser console is a support
# ticket.
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_DUPLICATE_TAKE = 4409
CLOSE_PROTOCOL_MISMATCH = 4426
CLOSE_RATE_LIMITED = 4429


class CoachFrame(BaseModel):
    v: int = 1
    type: str
    seq: int = 0


# ── client -> server ─────────────────────────────────────────────────────────


class CoachHello(CoachFrame):
    """Browsers cannot set headers on a WebSocket handshake, so the token
    arrives in the first frame rather than the URL -- which also keeps it out of
    access logs."""

    token: str
    protocol_version: str = PROTOCOL_VERSION


class CoachTakeStart(CoachFrame):
    take_id: uuid.UUID
    practice_session_id: uuid.UUID
    resume: bool = False
    voice: str | None = None


class CoachNotes(CoachFrame):
    take_id: uuid.UUID
    take_clock_seconds: float = Field(default=0.0, ge=0)
    notes: list[PerformedNoteIn] = Field(default_factory=list, max_length=32)


class CoachLevelFrame(CoachFrame):
    take_id: uuid.UUID
    take_clock_seconds: float = Field(default=0.0, ge=0)
    rms_db: float = Field(default=-100.0, ge=-120, le=20)
    silence_seconds: float = Field(default=0.0, ge=0)


class CoachTechniqueFrame(CoachFrame):
    take_id: uuid.UUID
    take_clock_seconds: float = Field(default=0.0, ge=0)
    detected: bool = False
    # The reduced output of the browser's posture/technique reducers. Never
    # landmarks, and never video.
    metrics: list[dict] = Field(default_factory=list, max_length=12)


class CoachBargeIn(CoachFrame):
    take_id: uuid.UUID
    utterance_id: uuid.UUID


class CoachFinalize(CoachFrame):
    take_id: uuid.UUID
    # The client's own complete note list, used verbatim. It is the only place
    # guaranteed to hold every note, and using it avoids a real trap: JS
    # `Number(x.toFixed(3))` and Python `round(x, 3)` disagree on ties, so a
    # server-buffered list could score a hair differently from the same take
    # submitted over HTTP.
    notes: list[PerformedNoteIn] = Field(default_factory=list, max_length=2000)
    recording_id: uuid.UUID | None = None
    posture: dict | None = None
    analyzer: str | None = Field(default=None, max_length=24)
    duration_seconds: float = Field(default=0.0, ge=0)


# ── server -> client ─────────────────────────────────────────────────────────


class CoachExerciseOut(BaseModel):
    id: uuid.UUID
    title: str
    instrument: str
    tempo_bpm: float
    expected_note_count: int


class CoachSessionReady(CoachFrame):
    type: str = "session.ready"
    protocol_version: str = PROTOCOL_VERSION
    resumed: bool = False
    buffered_note_count: int = 0
    exercise: CoachExerciseOut | None = None
    coach_enabled: bool = True
    audio_enabled: bool = True
    audio_format: str = "wav"


class CoachCue(CoachFrame):
    """Cheap, always-on, no LLM. This is what makes the panel feel live."""

    type: str = "cue"
    take_id: uuid.UUID
    take_clock_seconds: float = 0.0
    cue: str | None = None
    severity: str = "info"
    cursor: int = 0
    expected_note_count: int = 0
    matched_count: int = 0
    missed_count: int = 0
    extra_count: int = 0
    signed_timing_bias_seconds: float | None = None
    mean_pitch_error_semitones: float | None = None
    signed_pitch_bias_semitones: float | None = None
    progress_ratio: float = 0.0
    suppressed_by: str | None = None


class CoachUtteranceBegin(CoachFrame):
    type: str = "coach.begin"
    utterance_id: uuid.UUID
    cue: str
    severity: str
    provider: str
    audio_format: str | None = None


class CoachUtteranceDelta(CoachFrame):
    type: str = "coach.delta"
    utterance_id: uuid.UUID
    text: str


class CoachAudioChunk(CoachFrame):
    type: str = "coach.audio"
    utterance_id: uuid.UUID
    sequence: int
    format: str
    audio_base64: str


class CoachUtteranceEnd(CoachFrame):
    type: str = "coach.end"
    utterance_id: uuid.UUID
    spoken_text: str
    cancelled: bool = False
    provider: str = "deterministic"
    voice_provider: str | None = None


class CoachUtteranceCancel(CoachFrame):
    type: str = "coach.cancel"
    utterance_id: uuid.UUID
    reason: str


class CoachTakeResult(CoachFrame):
    type: str = "take.result"
    take_id: uuid.UUID
    # The existing, unmodified attempt contract. The streaming path is delivery;
    # the grade is the same one the clip path produces.
    attempt: PerformanceAttemptOut


class CoachError(CoachFrame):
    type: str = "error"
    code: str
    detail: str
    fatal: bool = False


class CoachLiveTipRequest(BaseModel):
    exercise_title: str
    instrument: str
    tempo_bpm: int
    current_note: str | None = None
    signed_timing_bias_seconds: float | None = None
    mean_pitch_error_semitones: float | None = None
    streak_count: int = 0


class CoachLiveTipResponse(BaseModel):
    tip: str
    focus_area: str
    suggested_action: str

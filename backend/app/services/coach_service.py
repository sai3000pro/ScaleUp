"""The live coaching session.

The load-bearing decision in this whole feature is what this module does *not*
do: it never produces a score. At end of take it hands the client's note list to
the existing `performance_service.submit_attempt` with an idempotency key
derived from the take id, and that call grades, awards EXP, and advances the
SRS exactly as it does for a clip. So "the streaming path agrees with the batch
path" is true by construction rather than by two implementations being kept in
step, and every existing test of the clip path still proves what it proved.

What this module owns is delivery: following the performance closely enough to
say something useful at the right moment, and getting that something to the
learner's ears while they are still sitting at the instrument.

Two concurrent tasks per socket, never one. The receive loop only ingests and
matches; a separate task streams an utterance. An utterance that blocked note
ingestion would make the coach's own speech look like a dropout in the take.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Mapping, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import _async_session_factory
from app.domain.coach_policy import (
    CoachTurn,
    CueKind,
    TurnBudget,
    TurnHistory,
    decide_turn,
)
from app.evaluation.feedback import live_cue_text
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.online import (
    ExpectedEvent,
    MatcherState,
    ObservedEvent,
    advance,
    expected_events,
    flush_stale,
    new_matcher,
    rolling_window,
)
from app.llm.base import LLMRole
from app.models import CoachSession, CoachUtterance, Exercise, PracticeSession, ScoreAsset
from app.models.llm_call import LlmCall
from app.schemas.coach import (
    CLOSE_DUPLICATE_TAKE,
    CLOSE_PROTOCOL_MISMATCH,
    PROTOCOL_VERSION,
    CoachExerciseOut,
    CoachLiveTipRequest,
    CoachLiveTipResponse,
)
from app.schemas.performance import PerformanceAttemptCreate, PerformedNoteIn, PostureObservationIn
from app.services import performance_service
from app.services.gemini_live_service import GeminiLiveCoachSession, generate_gemini_tip
from app.services.llm_gateway import recording_llm_client
from app.services.voice import stream_feedback, streaming_audio_format

logger = logging.getLogger(__name__)

# Process-local fallback map and unique instance id for cross-instance safety
_LIVE_TAKES: dict[uuid.UUID, str] = {}
_INSTANCE_ID = str(uuid.uuid4())


# @spec COACH-SESSION-012
def _claim_take(take_id: uuid.UUID, instance_id: str, ttl_seconds: int = 60) -> bool:
    """Acquire or refresh a cross-instance claim on a live take.

    Uses Redis when available so multiple application instances coordinate take claims (COACH-SESSION-012);
    falls back to process-local dictionary when Redis is unreachable or unconfigured.
    """
    owner = _LIVE_TAKES.get(take_id)
    if owner is not None and owner != instance_id:
        return False
    try:
        import redis

        client = redis.Redis.from_url(get_settings().celery_broker_url, socket_connect_timeout=1)
        key = f"coach:take:{take_id}:owner"
        acquired = client.set(key, instance_id, nx=True, ex=ttl_seconds)
        if acquired:
            _LIVE_TAKES[take_id] = instance_id
            return True
        current = client.get(key)
        if current and current.decode("utf-8") == instance_id:
            client.expire(key, ttl_seconds)
            _LIVE_TAKES[take_id] = instance_id
            return True
        return False
    except Exception:
        _LIVE_TAKES[take_id] = instance_id
        return True


# @spec COACH-SESSION-012
def _release_take(take_id: uuid.UUID, instance_id: str) -> None:
    """Release ownership of a live take across instances."""
    _LIVE_TAKES.pop(take_id, None)
    try:
        import redis

        client = redis.Redis.from_url(get_settings().celery_broker_url, socket_connect_timeout=1)
        key = f"coach:take:{take_id}:owner"
        current = client.get(key)
        if current and current.decode("utf-8") == instance_id:
            client.delete(key)
    except Exception:
        pass

CUE_INTERVAL_SECONDS = 0.4

# What one streamed cue costs, near enough to gate on. A live take cannot afford
# a database round trip per decision, so the remaining budget is read once when
# the take opens and drawn down locally -- an estimate that errs toward stopping
# early, which is the right direction for a ceiling.
UTTERANCE_COST_ESTIMATE_USD = Decimal("0.002")


class CoachTransport(Protocol):
    """Narrow enough that the state machine is testable without Starlette.

    `starlette.websockets.WebSocket` satisfies this structurally.
    """

    async def send_json(self, payload: Mapping[str, Any]) -> None: ...

    async def receive_json(self) -> dict[str, Any]: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


@dataclass
class TakeState:
    take_id: uuid.UUID
    practice_session_id: uuid.UUID
    exercise: Exercise
    instrument: str
    expected: tuple[ExpectedEvent, ...]
    timing_tolerance: float
    matcher: MatcherState = field(default_factory=new_matcher)
    history: TurnHistory = field(default_factory=TurnHistory)
    cue_times: dict[str, float] = field(default_factory=dict)
    silence_seconds: float = 0.0
    clock_seconds: float = 0.0
    suppressed: int = 0
    notes_seen: int = 0
    remaining_budget_usd: Decimal = Decimal("0")
    last_cue_sent: float = -1.0
    utterance_task: asyncio.Task | None = None
    cancel_event: asyncio.Event | None = None
    current_utterance: uuid.UUID | None = None


async def _load_take(session: AsyncSession, practice_session_id: uuid.UUID, user_id: uuid.UUID):
    practice = await session.get(PracticeSession, practice_session_id)
    if practice is None or practice.user_id != user_id:
        return None, None, None
    exercise = await session.get(Exercise, practice.exercise_id)
    if exercise is None:
        return None, None, None
    asset = await session.get(ScoreAsset, exercise.score_asset_id)
    return practice, exercise, asset


def _instrument_of(asset: ScoreAsset | None) -> str:
    if asset is not None and asset.asset_metadata and isinstance(asset.asset_metadata.get("instrument"), str):
        return str(asset.asset_metadata["instrument"])
    return "piano"


async def run_coach_session(
    session: AsyncSession,
    transport: CoachTransport,
    user,
) -> None:
    """Drive one socket until it closes."""
    state: TakeState | None = None

    try:
        while True:
            frame = await transport.receive_json()
            kind = str(frame.get("type", ""))

            if kind == "take.start":
                state = await _start_take(session, transport, user, frame)
                if state is None:
                    return
            elif kind == "hello":
                pass
            elif state is None:
                if kind not in {"frame", "heartbeat", "notes"}:
                    await _send_error(transport, "no_take", "Start a take before sending data.")
            elif kind == "notes":
                await _handle_notes(transport, state, frame)
            elif kind == "frame":
                state.clock_seconds = float(frame.get("take_clock_seconds", state.clock_seconds))
                state.silence_seconds = float(frame.get("silence_seconds", 0.0))
                await _flush_and_cue(transport, state)
            elif kind == "technique":
                # Accepted and acknowledged; posture rides on the finalize frame,
                # where it can be scored against the whole take rather than one
                # instant.
                pass
            elif kind == "barge_in":
                await _cancel_utterance(state, "barge_in", transport)
            elif kind == "heartbeat":
                await transport.send_json({"v": 1, "type": "pong", "seq": 0})
            elif kind == "take.finalize":
                await _finalize(session, transport, user, state, frame)
                state = None
            elif kind == "take.abandon":
                await _abandon(session, state)
                state = None
            else:
                await _send_error(transport, "unknown_frame", f"Unrecognised frame type {kind!r}.")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - a dropped socket is normal, not an incident
        logger.info("coach session ended: %s", exc)
    finally:
        if state is not None:
            await _cancel_utterance(state, "socket_closed", None)
            _release_take(state.take_id, _INSTANCE_ID)


# @spec COACH-SESSION-001, COACH-SESSION-002, COACH-SESSION-003, COACH-SESSION-012
async def _start_take(session, transport, user, frame) -> TakeState | None:
    if str(frame.get("protocol_version", PROTOCOL_VERSION)) != PROTOCOL_VERSION:
        await transport.close(CLOSE_PROTOCOL_MISMATCH, "Unsupported coach protocol version.")
        return None

    take_id = uuid.UUID(str(frame["take_id"]))
    practice_session_id = uuid.UUID(str(frame["practice_session_id"]))

    if not _claim_take(take_id, _INSTANCE_ID):
        await transport.close(CLOSE_DUPLICATE_TAKE, "This take is already open elsewhere.")
        return None

    practice, exercise, asset = await _load_take(session, practice_session_id, user.id)
    if practice is None or exercise is None or asset is None:
        _release_take(take_id, _INSTANCE_ID)
        await _send_error(transport, "not_found", "Practice session not found.", fatal=True)
        return None

    instrument = _instrument_of(asset)
    score = parse_musicxml(asset.content)
    expected = expected_events(score, instrument)
    seconds_per_beat = 60.0 / score.tempo_bpm
    tolerance = max(0.18, seconds_per_beat * 0.5)

    existing = await session.get(CoachSession, take_id)
    if existing is None:
        session.add(
            CoachSession(
                take_id=take_id,
                practice_session_id=practice.id,
                user_id=user.id,
                course_id=practice.course_id,
                exercise_id=exercise.id,
                status="active",
            )
        )
        await session.commit()
    elif existing.user_id != user.id or existing.status != "active":
        _release_take(take_id, _INSTANCE_ID)
        await _send_error(transport, "not_resumable", "This take is not active or belongs to another user.", fatal=True)
        return None

    settings = get_settings()
    spent = await session.scalar(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(LlmCall.course_id == practice.course_id)
    )
    remaining = max(Decimal("0"), settings.course_llm_budget_usd - Decimal(str(spent or 0)))

    await transport.send_json(
        {
            "v": 1,
            "type": "session.ready",
            "seq": 0,
            "protocol_version": PROTOCOL_VERSION,
            "resumed": existing is not None,
            "buffered_note_count": 0,
            "exercise": CoachExerciseOut(
                id=exercise.id,
                title=exercise.title,
                instrument=instrument,
                tempo_bpm=score.tempo_bpm,
                expected_note_count=len(expected),
            ).model_dump(mode="json"),
            "coach_enabled": True,
            "audio_enabled": True,
            "audio_format": streaming_audio_format(settings.voice_provider),
        }
    )
    return TakeState(
        take_id=take_id,
        practice_session_id=practice.id,
        exercise=exercise,
        instrument=instrument,
        expected=expected,
        timing_tolerance=tolerance,
        remaining_budget_usd=remaining,
    )


async def _handle_notes(transport, state: TakeState, frame) -> None:
    state.clock_seconds = float(frame.get("take_clock_seconds", state.clock_seconds))
    for raw in frame.get("notes", []):
        note = PerformedNoteIn.model_validate(raw)
        observation = ObservedEvent(
            pitch_midi=note.pitch_midi,
            onset_seconds=note.onset_seconds,
            duration_seconds=note.duration_seconds,
            confidence=note.confidence,
            drum=note.drum,
            level_db=note.level_db,
        )
        state.matcher, _ = advance(
            state.matcher,
            state.expected,
            observation,
            state.notes_seen,
            timing_tolerance=state.timing_tolerance,
        )
        state.notes_seen += 1

    # Notes arriving while the coach is talking is the definition of a barge-in.
    if frame.get("notes") and state.current_utterance is not None:
        await _cancel_utterance(state, "barge_in", transport)
    state.silence_seconds = 0.0
    await _flush_and_cue(transport, state)


async def _flush_and_cue(transport, state: TakeState) -> None:
    state.matcher, _ = flush_stale(
        state.matcher,
        state.expected,
        now_seconds=state.clock_seconds,
        timing_tolerance=state.timing_tolerance,
    )
    window = rolling_window(
        state.matcher,
        now_seconds=state.clock_seconds,
        window_seconds=6.0,
        expected_count=len(state.expected),
    )
    turn = decide_turn(
        window=window,
        history=replace(state.history, last_cue_at_seconds=state.cue_times),
        budget=TurnBudget(
            remaining_course_budget_usd=state.remaining_budget_usd,
            estimated_utterance_cost_usd=UTTERANCE_COST_ESTIMATE_USD,
        ),
        now_seconds=state.clock_seconds,
        silence_seconds=state.silence_seconds,
        expected_count=len(state.expected),
    )

    # The cheap channel: always on, no model, no spend. This is what makes the
    # panel feel live even when the coach has nothing worth saying.
    if state.clock_seconds - state.last_cue_sent >= CUE_INTERVAL_SECONDS:
        state.last_cue_sent = state.clock_seconds
        await transport.send_json(
            {
                "v": 1,
                "type": "cue",
                "seq": 0,
                "take_id": str(state.take_id),
                "take_clock_seconds": state.clock_seconds,
                "cue": None if turn.cue is None else str(turn.cue),
                "severity": turn.severity,
                "cursor": state.matcher.cursor,
                "expected_note_count": len(state.expected),
                "matched_count": window.matched_count,
                "missed_count": window.missed_count,
                "extra_count": window.extra_count,
                "signed_timing_bias_seconds": window.signed_timing_bias_seconds,
                "mean_pitch_error_semitones": window.mean_pitch_error_semitones,
                "signed_pitch_bias_semitones": window.signed_pitch_bias_semitones,
                "progress_ratio": window.progress_ratio,
                "suppressed_by": turn.suppressed_by,
            }
        )

    if turn.suppressed_by is not None:
        state.suppressed += 1
    elif turn.should_speak and state.utterance_task is None:
        state.utterance_task = asyncio.create_task(_speak(transport, state, turn))


async def _speak(transport, state: TakeState, turn: CoachTurn) -> None:
    """Stream one utterance. Never raises into the receive loop."""
    settings = get_settings()
    utterance_id = uuid.uuid4()
    cue = turn.cue or CueKind.GOOD_STREAK
    floor = live_cue_text(str(cue), exercise_title=state.exercise.title, instrument=state.instrument)
    cancel = asyncio.Event()
    state.cancel_event = cancel
    state.current_utterance = utterance_id

    provider = "deterministic"
    spoken = floor
    cancelled = False
    try:
        await transport.send_json(
            {
                "v": 1,
                "type": "coach.begin",
                "seq": 0,
                "utterance_id": str(utterance_id),
                "cue": str(cue),
                "severity": turn.severity,
                "provider": provider,
                "audio_format": streaming_audio_format(settings.voice_provider),
            }
        )
        spoken, provider, cancelled = await _stream_text(transport, state, turn, utterance_id, floor, cancel)
        if not cancelled:
            await _stream_audio(transport, utterance_id, spoken, cancel)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:  # noqa: BLE001 - delivery degrades, the take does not
        logger.warning("coach utterance failed; the deterministic sentence stands: %s", exc)
    finally:
        # Recorded BEFORE the end frame is sent, so a client that has seen
        # `coach.end` can rely on the utterance existing. The other order is a
        # race: the socket can close between the frame and the write.
        await _persist_utterance(state, utterance_id, turn, spoken, provider, cancelled)
        with contextlib.suppress(Exception):
            await transport.send_json(
                {
                    "v": 1,
                    "type": "coach.end",
                    "seq": 0,
                    "utterance_id": str(utterance_id),
                    "spoken_text": spoken,
                    "cancelled": cancelled,
                    "provider": provider,
                    "voice_provider": settings.voice_provider,
                }
            )
        state.history = TurnHistory(
            utterance_count=state.history.utterance_count + 1,
            last_utterance_at_seconds=state.clock_seconds,
            last_cue=cue,
            last_cue_at_seconds=state.cue_times,
            interventions=state.history.interventions + (1 if turn.severity == "intervene" else 0),
        )
        state.cue_times[str(cue)] = state.clock_seconds
        if provider != "deterministic":
            state.remaining_budget_usd = max(
                Decimal("0"), state.remaining_budget_usd - UTTERANCE_COST_ESTIMATE_USD
            )
        state.current_utterance = None
        state.cancel_event = None
        state.utterance_task = None


# @spec COACH-SESSION-004, COACH-SESSION-006
async def _stream_text(transport, state: TakeState, turn: CoachTurn, utterance_id, floor: str, cancel: asyncio.Event):
    """Stream the reworded cue, falling back to the deterministic sentence."""
    settings = get_settings()
    client = recording_llm_client(state.exercise.course_id)
    variables = {
        "exercise_title": state.exercise.title,
        "instrument": state.instrument,
        "cue": str(turn.cue),
        "severity": turn.severity,
        "metric_words": ", ".join(turn.phrase_words) or "nothing unusual",
        "deterministic_cue": floor,
        "recent_utterances": ", ".join(state.cue_times) or "(none)",
    }

    stream = getattr(client, "stream_text", None)
    if stream is None:
        await transport.send_json(
            {"v": 1, "type": "coach.delta", "seq": 0, "utterance_id": str(utterance_id), "text": floor}
        )
        return floor, "deterministic", False

    chunks: list[str] = []
    cancelled = False
    try:
        async with contextlib.aclosing(stream(LLMRole.LIVE_COACH_CUE, variables)) as deltas:
            async with asyncio.timeout(settings.coach_utterance_timeout_seconds):
                async for delta in deltas:
                    if cancel.is_set():
                        cancelled = True
                        break
                    chunks.append(delta.text)
                    await transport.send_json(
                        {
                            "v": 1,
                            "type": "coach.delta",
                            "seq": 0,
                            "utterance_id": str(utterance_id),
                            "text": delta.text,
                        }
                    )
    except (TimeoutError, asyncio.TimeoutError):
        # A slow model means the learner has already started playing again.
        logger.info("coach cue timed out; the deterministic sentence stands")
    except Exception as exc:  # noqa: BLE001 - the floor is always available
        logger.info("coach cue stream failed (%s); using the deterministic sentence", exc)

    text = "".join(chunks).strip()
    if not text:
        await transport.send_json(
            {"v": 1, "type": "coach.delta", "seq": 0, "utterance_id": str(utterance_id), "text": floor}
        )
        return floor, "deterministic", cancelled
    return text, client.provider, cancelled


async def _stream_audio(transport, utterance_id, text: str, cancel: asyncio.Event) -> None:
    settings = get_settings()

    async def sentences() -> AsyncIterator[str]:
        for sentence in _split_sentences(text):
            if not cancel.is_set():
                yield sentence

    sequence = 0
    async for chunk in stream_feedback(sentences()):
        if cancel.is_set():
            break
        await transport.send_json(
            {
                "v": 1,
                "type": "coach.audio",
                "seq": 0,
                "utterance_id": str(utterance_id),
                "sequence": sequence,
                "format": streaming_audio_format(settings.voice_provider),
                "audio_base64": base64.b64encode(chunk).decode("ascii"),
            }
        )
        sequence += 1


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for character in text:
        current.append(character)
        if character in ".!?":
            parts.append("".join(current).strip())
            current = []
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts or [text]


# @spec COACH-SESSION-005
async def _cancel_utterance(state: TakeState, reason: str, transport) -> None:
    if state.cancel_event is not None:
        state.cancel_event.set()
    utterance_id = state.current_utterance
    if utterance_id is not None and transport is not None:
        with contextlib.suppress(Exception):
            await transport.send_json(
                {
                    "v": 1,
                    "type": "coach.cancel",
                    "seq": 0,
                    "utterance_id": str(utterance_id),
                    "reason": reason,
                }
            )
    task = state.utterance_task
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    state.utterance_task = None


# @spec COACH-SESSION-007
async def _persist_utterance(state: TakeState, utterance_id, turn, spoken, provider, cancelled) -> None:
    """Record the utterance on its OWN session.

    The utterance runs as a separate task from the receive loop, and an
    `AsyncSession` is not safe to use from two tasks at once -- sharing one here
    silently lost every utterance row and would eventually have corrupted the
    receive loop's own transaction.
    """
    settings = get_settings()
    try:
        async with _async_session_factory()() as session:
            session.add(
                CoachUtterance(
                    id=utterance_id,
                    take_id=state.take_id,
                    sequence=state.history.utterance_count,
                    cue=str(turn.cue or ""),
                    severity=turn.severity,
                    reason=turn.reason,
                    provider=provider,
                    voice_provider=settings.voice_provider,
                    spoken_text=spoken,
                    cancelled=cancelled,
                    take_clock_seconds=state.clock_seconds,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - bookkeeping must not sink a live session
        logger.warning("could not record a coach utterance", exc_info=True)


# @spec COACH-SESSION-008, COACH-SESSION-009, COACH-SESSION-010, COACH-SESSION-011
async def _finalize(session, transport, user, state: TakeState, frame) -> None:
    """Hand the take to the one grading path there is."""
    await _cancel_utterance(state, "take_finalized", transport)

    payload = PerformanceAttemptCreate(
        observed_notes=[PerformedNoteIn.model_validate(note) for note in frame.get("notes", [])],
        recording_id=uuid.UUID(str(frame["recording_id"])) if frame.get("recording_id") else None,
        posture=PostureObservationIn.model_validate(frame["posture"]) if frame.get("posture") else None,
        analyzer=frame.get("analyzer"),
    )
    try:
        attempt = await performance_service.submit_attempt(
            session,
            state.practice_session_id,
            payload,
            user,
            # The same key the HTTP fallback uses, so a socket that dropped and
            # a client that retried cannot produce two attempts or two awards.
            f"coach:{state.take_id}",
        )
    except Exception as exc:  # noqa: BLE001 - report it and let the client retry over HTTP
        logger.warning("streamed take could not be scored: %s", exc)
        await _send_error(transport, "score_failed", str(exc))
        return

    coach_session = await session.get(CoachSession, state.take_id)
    if coach_session is not None:
        committed = state.matcher.committed
        coach_session.status = "finalized"
        coach_session.attempt_id = attempt.id
        coach_session.finalized_at = datetime.now(timezone.utc)
        coach_session.observed_note_count = state.notes_seen
        coach_session.utterance_count = state.history.utterance_count
        coach_session.suppressed_turn_count = state.suppressed
        coach_session.live_matched_note_count = len([o for o in committed if o.kind == "matched"])
        coach_session.live_missed_note_count = len([o for o in committed if o.kind == "missed"])
        coach_session.live_extra_note_count = len([o for o in committed if o.kind == "extra"])
        await session.commit()

    await transport.send_json(
        {
            "v": 1,
            "type": "take.result",
            "seq": 0,
            "take_id": str(state.take_id),
            "attempt": attempt.model_dump(mode="json"),
        }
    )
    _release_take(state.take_id, _INSTANCE_ID)


async def _abandon(session, state: TakeState | None) -> None:
    if state is None:
        return
    coach_session = await session.get(CoachSession, state.take_id)
    if coach_session is not None and coach_session.status == "active":
        coach_session.status = "abandoned"
        await session.commit()
    _release_take(state.take_id, _INSTANCE_ID)


async def _send_error(transport, code: str, detail: str, *, fatal: bool = False) -> None:
    with contextlib.suppress(Exception):
        await transport.send_json(
            {"v": 1, "type": "error", "seq": 0, "code": code, "detail": detail, "fatal": fatal}
        )


async def coach_sessions_for(session: AsyncSession, user_id: uuid.UUID) -> list[CoachSession]:
    return list(
        await session.scalars(
            select(CoachSession).where(CoachSession.user_id == user_id).order_by(CoachSession.created_at.desc())
        )
    )


async def generate_live_tip(course_id: uuid.UUID, req: CoachLiveTipRequest) -> CoachLiveTipResponse:
    instrument = req.instrument.lower()
    bpm = req.tempo_bpm
    current_note = req.current_note or "target notes"
    timing = req.signed_timing_bias_seconds
    pitch_err = req.mean_pitch_error_semitones

    # Try Gemini 2.0 Live API tip generation first if configured
    gemini_tip = await generate_gemini_tip(
        instrument=instrument,
        exercise_title=req.exercise_title,
        tempo_bpm=bpm,
        current_note=req.current_note,
        signed_timing_bias_seconds=timing,
        mean_pitch_error_semitones=pitch_err,
    )
    if gemini_tip is not None:
        return CoachLiveTipResponse(
            tip=gemini_tip["tip"],
            focus_area=gemini_tip["focus_area"],
            suggested_action=gemini_tip["suggested_action"],
        )

    if timing is not None and timing < -0.05:
        focus = "Rhythm: Rushing"
        tip = f"You are striking slightly ahead of the beat by {abs(round(timing * 1000))}ms. Relax into the pulse and let {current_note} land directly on the metronome click."
        action = "Breathe and lock in with Beat 1 downbeat."
    elif timing is not None and timing > 0.05:
        focus = "Rhythm: Dragging"
        tip = f"You are landing {abs(round(timing * 1000))}ms behind the beat. Pre-position your finger for {current_note} ahead of time so the attack is crisp."
        action = "Prepare your finger above the key/fret before the beat strikes."
    elif pitch_err is not None and abs(pitch_err) > 0.4:
        focus = "Pitch Accuracy"
        tip = f"Pitch deviated near {current_note}. Check your finger placement on the instrument visualizer."
        action = "Check key/fret position and ensure clean contact."
    else:
        instrument_tips: dict[str, tuple[str, str, str]] = {
            "piano": (
                "Hand Posture & Touch",
                f"Keep your wrists relaxed and fingers naturally curved over the keys. For {current_note} at {bpm} BPM, aim for even weight across all fingers.",
                "Maintain curved hand shape and press through the keybed smoothly.",
            ),
            "guitar": (
                "Fret Placement & Clarity",
                f"Fret right up against the fret wire for {current_note} to prevent fret buzz, keeping your thumb anchored comfortably behind the neck.",
                "Ensure fingertips strike perpendicular to the fretboard.",
            ),
            "violin": (
                "Bow Contact & Tone",
                f"Keep your bow parallel to the bridge with steady pressure for {current_note}. Listen for a rich, resonant acoustic tone.",
                "Maintain consistent bow speed from frog to tip.",
            ),
            "trumpet": (
                "Airflow & Embouchure",
                f"Support your tone from the diaphragm. Keep corners of the mouth firm for {current_note} at {bpm} BPM.",
                "Keep breath support steady through each interval transition.",
            ),
            "drums": (
                "Stick Control & Groove",
                f"Keep wrist grip loose for relaxed rebound on each stroke at {bpm} BPM.",
                "Lock into the kick drum on beat 1 and snare on beats 2 and 4.",
            ),
        }
        focus, tip, action = instrument_tips.get(
            instrument,
            ("Practice Technique", f"Play {current_note} smoothly at {bpm} BPM with steady pulse.", "Focus on rhythm and clarity.")
        )

    return CoachLiveTipResponse(tip=tip, focus_area=focus, suggested_action=action)

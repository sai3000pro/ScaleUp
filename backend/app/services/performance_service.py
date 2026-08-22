"""Clip-based instrument practice over the canonical evaluator boundary."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exp import award_for_attempt
from app.domain.realm import LessonProgress, is_lesson_open, is_test_open, open_lesson_step
from app.domain.srs import schedule
from app.domain.states import overdue_days
from app.evaluation.feedback import PERSONA, ExaminerFeedback, generate_feedback, merge_feedback
from app.evaluation.musicxml import MusicXMLParseError, midi_to_note_name, parse_musicxml
from app.evaluation.piano import PianoPerformanceScore
from app.evaluation.posture import PostureMetric, PostureScore, score_posture
from app.evaluation.registry import EvaluationResult, ObservationIn, evaluate
from app.llm.base import LLMRole
from app.models import (
    Course,
    Exercise,
    PerformanceAttempt,
    PerformanceMetricBundle,
    PracticeSession,
    Recording,
    ScoreAsset,
    SkillNode,
    StoredVoiceArtifact,
    User,
)
from app.models.progress import NodeProgress
from app.schemas.performance import (
    ExaminerFeedbackOut,
    ExerciseNoteOut,
    ExerciseOut,
    LessonOut,
    PerformanceAttemptCreate,
    PerformanceAttemptOut,
    PerformanceMetricsOut,
    PracticeSessionCreate,
    PracticeSessionOut,
    SkillRealmOut,
    VoiceArtifactOut,
)
from app.services import n8n_service
from app.services.graph_read import ensure_progress_rows, review_state_of
from app.services.llm_gateway import recording_llm_client
from app.services.voice import cache_key_for, synthesize_feedback

logger = logging.getLogger(__name__)


def _session_out(practice: PracticeSession) -> PracticeSessionOut:
    return PracticeSessionOut(
        id=practice.id,
        course_id=practice.course_id,
        exercise_id=practice.exercise_id,
        status=practice.status,
        created_at=practice.created_at,
        completed_at=practice.completed_at,
    )


def _metrics_out(metrics: PerformanceMetricBundle) -> PerformanceMetricsOut:
    return PerformanceMetricsOut(
        evaluator_version=metrics.evaluator_version,
        expected_note_count=metrics.expected_note_count,
        observed_note_count=metrics.observed_note_count,
        matched_note_count=metrics.matched_note_count,
        missed_note_count=metrics.missed_note_count,
        extra_note_count=metrics.extra_note_count,
        pitch_accuracy=metrics.pitch_accuracy,
        rhythm_accuracy=metrics.rhythm_accuracy,
        technique_accuracy=metrics.technique_accuracy,
        position_error_count=metrics.position_error_count,
        intonation_accuracy=metrics.intonation_accuracy,
        intonation_deviation_cents=metrics.intonation_deviation_cents,
        dynamics_accuracy=metrics.dynamics_accuracy,
        dynamic_range_db=metrics.dynamic_range_db,
        dynamics_contrast=metrics.dynamics_contrast,
        posture_accuracy=metrics.posture_accuracy,
        posture_version=metrics.posture_version,
        analyzer=metrics.analyzer,
        tempo_bpm=metrics.tempo_bpm,
        tempo_deviation_percent=metrics.tempo_deviation_percent,
        alignment_confidence=metrics.alignment_confidence,
        overall_score=metrics.overall_score,
        low_confidence=metrics.low_confidence,
    )


def _feedback_out(feedback: ExaminerFeedback) -> ExaminerFeedbackOut:
    return ExaminerFeedbackOut(
        persona=feedback.persona,
        tone=feedback.tone,
        summary=feedback.summary,
        strengths=list(feedback.strengths),
        corrections=list(feedback.corrections),
        next_step=feedback.next_step,
    )


def _score_from_bundle(metrics: PerformanceMetricBundle) -> PianoPerformanceScore:
    return PianoPerformanceScore(
        evaluator_version=metrics.evaluator_version,
        expected_note_count=metrics.expected_note_count,
        observed_note_count=metrics.observed_note_count,
        matched_note_count=metrics.matched_note_count,
        missed_note_count=metrics.missed_note_count,
        extra_note_count=metrics.extra_note_count,
        pitch_accuracy=metrics.pitch_accuracy,
        rhythm_accuracy=metrics.rhythm_accuracy,
        tempo_bpm=metrics.tempo_bpm,
        tempo_deviation_percent=metrics.tempo_deviation_percent,
        alignment_confidence=metrics.alignment_confidence,
        overall_score=metrics.overall_score,
        intonation_accuracy=metrics.intonation_accuracy,
        intonation_deviation_cents=metrics.intonation_deviation_cents,
    )


async def _exercise_context(session: AsyncSession, exercise_id: uuid.UUID) -> tuple[str, str, int]:
    exercise = await session.get(Exercise, exercise_id)
    if exercise is None:
        return "Exercise", "instrument", 3
    asset = await session.get(ScoreAsset, exercise.score_asset_id)
    instrument = "instrument"
    if asset is not None and asset.asset_metadata:
        instrument = str(asset.asset_metadata.get("instrument", "instrument"))
    return exercise.title, instrument, exercise.difficulty


def _feedback_block(feedback: ExaminerFeedback) -> str:
    strengths = "\n".join(f"- {item}" for item in feedback.strengths)
    corrections = "\n".join(f"- {item}" for item in feedback.corrections)
    return (
        f"Persona: {feedback.persona}\n"
        f"Tone: {feedback.tone}\n"
        f"Summary: {feedback.summary}\n"
        f"Strengths:\n{strengths}\n"
        f"Corrections:\n{corrections}\n"
        f"Next step: {feedback.next_step}"
    )


def _metrics_block(score: EvaluationResult) -> str:
    """The metric bundle as prose the examiner prompt can read.

    Words as well as numbers: a model handed `0.94` has to guess whether that is
    good, and a model handed `34` cents has to guess which direction is better.
    Naming the polarity inline is what stops an examiner congratulating a learner
    on a large intonation deviation.
    """
    lines = [f"Overall score: {score.overall_score:.2f}"]
    if score.pitch_accuracy is not None:
        lines.append(f"Pitch accuracy: {score.pitch_accuracy:.2f} (higher is better)")
    else:
        lines.append("Pitch accuracy: inapplicable (rhythm-only instrument)")
    lines.append(f"Rhythm accuracy: {score.rhythm_accuracy:.2f} (higher is better)")
    lines.append(f"Missed notes: {score.missed_note_count} (lower is better)")
    lines.append(f"Extra notes: {score.extra_note_count} (lower is better)")
    lines.append(f"Alignment confidence: {score.alignment_confidence:.2f} (higher is better)")
    if score.technique_accuracy is not None:
        lines.append(f"Fretboard position accuracy: {score.technique_accuracy:.2f} (higher is better)")
        lines.append(f"Position errors: {score.position_error_count} (lower is better)")
    if score.intonation_deviation_cents is not None:
        lines.append(f"Intonation deviation: {score.intonation_deviation_cents:.1f} cents (lower is better)")
    if score.dynamics_accuracy is not None:
        lines.append(f"Dynamics accuracy: {score.dynamics_accuracy:.2f} (higher is better)")
    if score.dynamics_contrast is not None:
        lines.append(f"Dynamic shaping followed: {score.dynamics_contrast:.2f} (higher is better)")
    else:
        lines.append("Dynamics: not assessed in this take")
    if score.posture_accuracy is not None:
        lines.append(f"Posture: {score.posture_accuracy:.2f} (higher is better)")
    else:
        lines.append("Posture: not assessed in this take")
    if score.tempo_deviation_percent is not None:
        lines.append(f"Tempo deviation: {score.tempo_deviation_percent:.1f}% (closer to zero is better)")
    return "\n".join(lines)


async def _attempt_out(
    session: AsyncSession,
    attempt: PerformanceAttempt,
    metrics: PerformanceMetricBundle,
) -> PerformanceAttemptOut:
    exercise_title, instrument, difficulty = await _exercise_context(session, attempt.exercise_id)
    if attempt.feedback_provider is not None and attempt.feedback_summary is not None:
        feedback = ExaminerFeedback(
            persona=attempt.feedback_persona or PERSONA,
            tone=attempt.feedback_tone or "supportive",
            summary=attempt.feedback_summary,
            strengths=tuple(attempt.feedback_strengths or ()),
            corrections=tuple(attempt.feedback_corrections or ()),
            next_step=attempt.feedback_next_step or "",
        )
    else:
        feedback = generate_feedback(
            _score_from_bundle(metrics),
            exercise_title=exercise_title,
            instrument=instrument,
            difficulty=difficulty,
        )
    return PerformanceAttemptOut(
        id=attempt.id,
        session_id=attempt.session_id,
        exercise_id=attempt.exercise_id,
        status=attempt.status,
        overall_score=attempt.overall_score,
        alignment_confidence=attempt.alignment_confidence,
        exp_awarded=attempt.exp_awarded,
        feedback_provider=attempt.feedback_provider or "deterministic",
        created_at=attempt.created_at,
        metrics=_metrics_out(metrics),
        feedback=_feedback_out(feedback),
    )


async def _owned_exercise(session: AsyncSession, exercise_id: uuid.UUID, user_id: uuid.UUID) -> Exercise:
    exercise = await session.get(Exercise, exercise_id)
    if exercise is None or not exercise.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise not found.")
    course = await session.get(Course, exercise.course_id)
    if course is None or course.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise not found.")
    return exercise


def _notes_from_score(content: str) -> list[ExerciseNoteOut]:
    try:
        score = parse_musicxml(content)
        result = []
        for n in score.notes:
            if n.pitch_midi is not None:
                name = midi_to_note_name(n.pitch_midi)
            elif n.unpitched_step:
                name = f"{n.unpitched_step}{n.unpitched_octave or ''}"
            else:
                name = "Rest"
            result.append(
                ExerciseNoteOut(
                    pitch_midi=n.pitch_midi,
                    note_name=name,
                    onset_beats=n.onset_beats,
                    duration_beats=n.duration_beats,
                    fret=n.fret,
                    string=n.string,
                )
            )
        return result
    except Exception:
        return []


# @spec PROG-REALM-001, PROG-REALM-002, PROG-REALM-003
async def list_skill_realms(session: AsyncSession, course_id: uuid.UUID, user: User) -> list[SkillRealmOut]:
    """Every skill's lesson run in one call, with this learner's progress on it.

    One call rather than one per skill: a realm is opened by double-clicking,
    which is not a moment to start a round trip, and the whole course's runs are
    a few dozen rows.

    Best score, not latest. A learner who cleared a lesson and then had a bad
    take has still cleared it -- the SRS is what decides whether the skill has
    since decayed, and re-closing a lesson behind them would be a second opinion
    on that.
    """
    course = await session.get(Course, course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found.")

    exercises = list(
        await session.scalars(
            select(Exercise)
            .where(Exercise.course_id == course_id, Exercise.active.is_(True))
            .order_by(Exercise.node_id, Exercise.difficulty, Exercise.slug)
        )
    )
    titles = {
        node_id: title
        for node_id, title in await session.execute(
            select(SkillNode.id, SkillNode.title).where(SkillNode.course_id == course_id)
        )
    }

    # One aggregate over the learner's attempts, rather than a query per lesson.
    takes = {
        exercise_id: (count, best)
        for exercise_id, count, best in await session.execute(
            select(
                PerformanceAttempt.exercise_id,
                func.count(PerformanceAttempt.id),
                func.max(PerformanceAttempt.overall_score),
            )
            .where(PerformanceAttempt.course_id == course_id, PerformanceAttempt.user_id == user.id)
            .group_by(PerformanceAttempt.exercise_id)
        )
    }

    by_node: dict[uuid.UUID, list[LessonProgress]] = {}
    for exercise in exercises:
        run = by_node.setdefault(exercise.node_id, [])
        attempts, best = takes.get(exercise.id, (0, None))
        run.append(
            LessonProgress(
                exercise_id=str(exercise.id),
                title=exercise.title,
                instructions=exercise.instructions,
                difficulty=exercise.difficulty,
                step=len(run) + 1,
                attempts=attempts,
                best_score=best,
            )
        )

    realms: list[SkillRealmOut] = []
    for node_id, run in by_node.items():
        lessons = tuple(run)
        frontier = open_lesson_step(lessons)
        realms.append(
            SkillRealmOut(
                node_id=node_id,
                node_title=titles.get(node_id, ""),
                lessons=[
                    LessonOut(
                        exercise_id=uuid.UUID(lesson.exercise_id),
                        title=lesson.title,
                        instructions=lesson.instructions,
                        difficulty=lesson.difficulty,
                        step=lesson.step,
                        attempts=lesson.attempts,
                        best_score=lesson.best_score,
                        cleared=lesson.cleared,
                        open=is_lesson_open(lessons, lesson.step),
                    )
                    for lesson in lessons
                ],
                open_step=frontier,
                test_open=is_test_open(lessons),
            )
        )
    return realms


async def list_exercises(session: AsyncSession, course_id: uuid.UUID, user: User) -> list[ExerciseOut]:
    course = await session.get(Course, course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found.")
    rows = list(
        await session.execute(
            select(Exercise, ScoreAsset)
            .join(ScoreAsset, ScoreAsset.id == Exercise.score_asset_id)
            .where(Exercise.course_id == course_id, Exercise.active.is_(True))
            .order_by(Exercise.created_at, Exercise.id)
        )
    )
    return [
        ExerciseOut(
            id=exercise.id,
            course_id=exercise.course_id,
            node_id=exercise.node_id,
            slug=exercise.slug,
            title=exercise.title,
            instructions=exercise.instructions,
            score_title=asset.title,
            score_format=asset.format,
            tempo_bpm=asset.tempo_bpm,
            duration_beats=asset.duration_beats,
            evaluator_version=exercise.evaluator_version,
            difficulty=exercise.difficulty,
            notes=_notes_from_score(asset.content),
        )
        for exercise, asset in rows
    ]


async def create_session(
    session: AsyncSession,
    payload: PracticeSessionCreate,
    user: User,
) -> PracticeSessionOut:
    exercise = await _owned_exercise(session, payload.exercise_id, user.id)
    practice = PracticeSession(
        user_id=user.id,
        course_id=exercise.course_id,
        exercise_id=exercise.id,
        status="active",
    )
    session.add(practice)
    await session.commit()
    await session.refresh(practice)
    return _session_out(practice)


async def _owned_practice_session(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> PracticeSession:
    practice = await session.get(PracticeSession, session_id)
    if practice is None or practice.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Practice session not found.")
    return practice


async def _existing_attempt(
    session: AsyncSession, user_id: uuid.UUID, idempotency_key: str
) -> PerformanceAttemptOut | None:
    attempt = await session.scalar(
        select(PerformanceAttempt).where(
            PerformanceAttempt.user_id == user_id,
            PerformanceAttempt.idempotency_key == idempotency_key,
        )
    )
    if attempt is None:
        return None
    metrics = await session.scalar(
        select(PerformanceMetricBundle).where(PerformanceMetricBundle.attempt_id == attempt.id)
    )
    if metrics is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Performance metrics are missing.")
    return await _attempt_out(session, attempt, metrics)



# @spec EVAL-INST-001, EVAL-INST-008, EVAL-VER-003, EVAL-VER-004, EVAL-LIVE-006
# @spec CAP-TAKE-005
async def submit_attempt(
    session: AsyncSession,
    practice_session_id: uuid.UUID,
    payload: PerformanceAttemptCreate,
    user: User,
    idempotency_key: str,
) -> PerformanceAttemptOut:
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key is required for performance submissions.")
    if len(idempotency_key) > 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key must be at most 128 characters.")
    existing = await _existing_attempt(session, user.id, idempotency_key)
    if existing is not None:
        return existing

    practice = await _owned_practice_session(session, practice_session_id, user.id)
    if practice.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This practice session is no longer active.")
    exercise = await _owned_exercise(session, practice.exercise_id, user.id)
    if payload.recording_id is not None:
        recording = await session.get(Recording, payload.recording_id)
        if recording is None or recording.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found.")
        if recording.course_id != practice.course_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Recording belongs to a different course than this practice session.",
            )
    asset = await session.get(ScoreAsset, exercise.score_asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Exercise score asset is missing.")

    instrument = "piano"
    if asset.asset_metadata and isinstance(asset.asset_metadata.get("instrument"), str):
        instrument = asset.asset_metadata["instrument"]

    posture_score: PostureScore | None = None
    posture_metrics: list[dict] | None = None
    if payload.posture is not None and payload.posture.metrics:
        posture_metrics = [metric.model_dump() for metric in payload.posture.metrics]
        posture_score = score_posture(
            [
                PostureMetric(
                    key=metric.key,
                    value=metric.value,
                    confidence=metric.confidence,
                    status=metric.status,
                    raw=metric.raw,
                    unit=metric.unit,
                )
                for metric in payload.posture.metrics
            ],
            version=payload.posture.version,
        )

    try:
        score_asset = parse_musicxml(asset.content)
        observations = [
            ObservationIn(
                pitch_midi=note.pitch_midi,
                onset_seconds=note.onset_seconds,
                duration_seconds=note.duration_seconds,
                confidence=note.confidence,
                string=note.string,
                fret=note.fret,
                cents_deviation=note.cents_deviation,
                drum=note.drum,
                level_db=note.level_db,
            )
            for note in payload.observed_notes
        ]
        result = evaluate(
            instrument,
            exercise.evaluator_version,
            score_asset,
            observations,
            posture=posture_score,
        )
    except (MusicXMLParseError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    deterministic = generate_feedback(
        result,
        exercise_title=exercise.title,
        instrument=instrument,
        difficulty=exercise.difficulty,
    )
    feedback = deterministic
    feedback_provider = "deterministic"
    try:
        client = recording_llm_client(practice.course_id)
        llm_result = await client.structured(
            LLMRole.PERFORMANCE_FEEDBACK,
            {
                "exercise_title": exercise.title,
                "instrument": instrument,
                "difficulty": str(exercise.difficulty),
                "metrics": _metrics_block(result),
                "deterministic_feedback": _feedback_block(deterministic),
            },
            course_id=str(practice.course_id),
        )
        feedback = merge_feedback(deterministic, llm_result.data)
        feedback_provider = llm_result.provider
    except Exception as exc:  # noqa: BLE001 - the deterministic floor keeps the result usable
        logger.warning("performance feedback fell back to the deterministic examiner: %s", exc)

    await ensure_progress_rows(session, user.id, [exercise.node_id])
    progress = await session.get(NodeProgress, (user.id, exercise.node_id))
    if progress is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Exercise progress row is missing.")

    now = datetime.now(timezone.utc)
    before = review_state_of(progress)
    award = 0
    if not result.low_confidence:
        first_pass = before.last_reviewed_at is None and before.lapses == 0 and before.reps == 0
        award = award_for_attempt(
            score=result.overall_score,
            difficulty=exercise.difficulty,
            overdue_days=overdue_days(before, now),
            interval_days=before.interval_days,
            is_first_pass=first_pass,
        )
        after = schedule(before, result.overall_score, now)
        progress.exp += award
        progress.mastery = after.mastery
        progress.ease = after.ease
        progress.interval_days = after.interval_days
        progress.reps = after.reps
        progress.lapses = after.lapses
        progress.last_reviewed_at = after.last_reviewed_at
        progress.due_at = after.due_at
        user.total_exp += award

    attempt = PerformanceAttempt(
        session_id=practice.id,
        user_id=user.id,
        course_id=practice.course_id,
        exercise_id=exercise.id,
        idempotency_key=idempotency_key,
        status="needs_review" if result.low_confidence else "completed",
        observed_notes=[note.model_dump() for note in payload.observed_notes],
        overall_score=result.overall_score,
        alignment_confidence=result.alignment_confidence,
        exp_awarded=award,
        feedback_provider=feedback_provider,
        feedback_persona=feedback.persona,
        feedback_tone=feedback.tone,
        feedback_summary=feedback.summary,
        feedback_strengths=list(feedback.strengths),
        feedback_corrections=list(feedback.corrections),
        feedback_next_step=feedback.next_step,
    )
    session.add(attempt)
    await session.flush()
    session.add(
        PerformanceMetricBundle(
            attempt_id=attempt.id,
            evaluator_version=result.evaluator_version,
            expected_note_count=result.expected_note_count,
            observed_note_count=result.observed_note_count,
            matched_note_count=result.matched_note_count,
            missed_note_count=result.missed_note_count,
            extra_note_count=result.extra_note_count,
            pitch_accuracy=result.pitch_accuracy,
            rhythm_accuracy=result.rhythm_accuracy,
            technique_accuracy=result.technique_accuracy,
            position_error_count=result.position_error_count,
            intonation_accuracy=result.intonation_accuracy,
            intonation_deviation_cents=result.intonation_deviation_cents,
            dynamics_accuracy=result.dynamics_accuracy,
            dynamic_range_db=result.dynamic_range_db,
            dynamics_contrast=result.dynamics_contrast,
            posture_accuracy=result.posture_accuracy,
            posture_version=result.posture_version,
            posture_metrics=posture_metrics,
            analyzer=payload.analyzer,
            tempo_bpm=result.tempo_bpm,
            tempo_deviation_percent=result.tempo_deviation_percent,
            alignment_confidence=result.alignment_confidence,
            overall_score=result.overall_score,
            low_confidence=result.low_confidence,
        )
    )
    practice.status = "completed"
    practice.completed_at = now
    if payload.recording_id is not None:
        recording.attempt_id = attempt.id
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        settled = await _existing_attempt(session, user.id, idempotency_key)
        if settled is None:
            raise
        return settled

    await session.refresh(attempt)
    metrics = await session.scalar(
        select(PerformanceMetricBundle).where(PerformanceMetricBundle.attempt_id == attempt.id)
    )
    if metrics is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Performance metrics are missing.")

    # Announced only after the attempt is committed, and never awaited for its
    # result. n8n being unreachable is not a reason a practice take fails.
    await n8n_service.emit(
        "attempt.completed",
        {
            "attempt_id": str(attempt.id),
            "user_id": str(user.id),
            "course_id": str(attempt.course_id),
            "exercise_id": str(attempt.exercise_id),
            "overall_score": attempt.overall_score,
            "exp_awarded": attempt.exp_awarded,
            "status": attempt.status,
        },
    )
    return await _attempt_out(session, attempt, metrics)



async def get_attempt(
    session: AsyncSession, attempt_id: uuid.UUID, user: User
) -> PerformanceAttemptOut:
    attempt = await session.get(PerformanceAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Performance attempt not found.")
    metrics = await session.scalar(
        select(PerformanceMetricBundle).where(PerformanceMetricBundle.attempt_id == attempt.id)
    )
    if metrics is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Performance metrics are missing.")
    return await _attempt_out(session, attempt, metrics)


async def speech_for_attempt(
    session: AsyncSession, attempt: PerformanceAttempt, voice_key: str = ""
) -> VoiceArtifactOut:
    """Speak an attempt's examiner feedback, caching the audio by content.

    Shared by the learner endpoint (after its ownership check) and the
    feedback.requested webhook (after its existence check), so n8n can request
    voice delivery for an attempt without impersonating its owner.

    The response always carries the spoken text and only carries audio when a
    provider is configured, so the frontend can read the feedback aloud with
    browser TTS either way.
    """
    score_pct = round((attempt.overall_score or 0) * 100)
    intros = [
        f"Brilliant take! You finished with {score_pct} percent accuracy.",
        f"Solid execution on this drill, landing at {score_pct} percent.",
        f"Great session! Your overall performance scored {score_pct} percent.",
        f"Take finalized! You achieved a score of {score_pct} percent.",
    ]
    tier_intro = intros[score_pct % len(intros)] if score_pct >= 80 else (
        f"Good effort on this drill! You landed at {score_pct} percent." if score_pct >= 50 else
        f"Good practice pass at {score_pct} percent. Let's build up momentum and try it again."
    )
    summary = attempt.feedback_summary or tier_intro
    next_step = attempt.feedback_next_step or "Run through the drill once more to lock in the groove."
    text = f"{summary} Next step: {next_step}"
    actual_voice = voice_key or "21m00Tcm4TlvDq8ikWAM"
    cache_key = cache_key_for(text, actual_voice)
    stored = await session.get(StoredVoiceArtifact, cache_key)
    if stored is not None:
        return VoiceArtifactOut(
            attempt_id=attempt.id,
            provider=stored.provider,
            voice_key=stored.voice_key,
            format=stored.format,
            audio_base64=base64.b64encode(stored.content).decode("ascii"),
            spoken_text=stored.spoken_text,
            cache_key=cache_key,
            cached=True,
        )

    artifact = await synthesize_feedback(text, voice_key=actual_voice)
    if artifact.content:
        session.add(
            StoredVoiceArtifact(
                cache_key=cache_key,
                attempt_id=attempt.id,
                provider=artifact.provider,
                voice_key=actual_voice,
                format=artifact.format,
                content=artifact.content,
                spoken_text=artifact.spoken_text,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent request synthesized the same text first; the primary
            # key is the content hash, so re-reading is the recovery.
            await session.rollback()
            await session.refresh(attempt)
    return VoiceArtifactOut(
        attempt_id=attempt.id,
        provider=artifact.provider,
        voice_key=artifact.voice_key,
        format=artifact.format,
        audio_base64=base64.b64encode(artifact.content).decode("ascii") if artifact.content else None,
        spoken_text=artifact.spoken_text,
        cache_key=cache_key,
        cached=False,
    )


async def synthesize_attempt_speech(
    session: AsyncSession, attempt_id: uuid.UUID, user: User, voice_key: str = ""
) -> VoiceArtifactOut:
    """Learner-facing speech endpoint: ownership check, then shared synthesis."""
    attempt = await session.get(PerformanceAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Performance attempt not found.")
    return await speech_for_attempt(session, attempt, voice_key=voice_key)

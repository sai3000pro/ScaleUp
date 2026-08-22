from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.coach import CoachLiveTipRequest, CoachLiveTipResponse
from app.schemas.performance import (
    ExerciseGenerateIn,
    ExerciseOut,
    PerformanceAttemptCreate,
    PerformanceAttemptOut,
    PracticeSessionCreate,
    PracticeSessionOut,
    SkillRealmOut,
    VoiceArtifactOut,
)
from app.schemas.progress import PracticeReport
from app.services import coach_service, course_service, performance_service, practice_progress_service, score_service

router = APIRouter(prefix="/api", tags=["practice"])


@router.get("/courses/{course_id}/practice/exercises", response_model=list[ExerciseOut])
async def list_practice_exercises(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[ExerciseOut]:
    return await performance_service.list_exercises(session, course_id, user)


@router.get("/courses/{course_id}/practice/realms", response_model=list[SkillRealmOut])
async def list_skill_realms(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[SkillRealmOut]:
    """Every skill's lesson run, with this learner's progress and its test gate."""
    return await performance_service.list_skill_realms(session, course_id, user)


@router.post(
    "/courses/{course_id}/practice/exercises",
    response_model=ExerciseOut,
    status_code=status.HTTP_201_CREATED,
)
async def generate_practice_exercise(
    course_id: uuid.UUID,
    payload: ExerciseGenerateIn,
    user: CurrentUser,
    session: DbSession,
    response: Response,
) -> ExerciseOut:
    """Generate a score-backed exercise for one skill node.

    Idempotent: a node that already has an exercise of this pattern returns the
    existing one with `200` rather than creating a second. Regenerating is
    deliberately not offered -- attempt history is grouped by exercise, so
    swapping the score under a stable id would silently compare a learner
    against a different piece of music.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    exercise, created = await score_service.create_exercise_for_node(session, course=course, payload=payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return exercise


@router.get("/courses/{course_id}/practice/report", response_model=PracticeReport)
async def get_practice_report(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    exercise_id: uuid.UUID | None = None,
    days: int = 30,
) -> PracticeReport:
    """How this learner's practice has moved over a window of days.

    Computed on read from the attempts already recorded. Nothing about a trend
    is stored: it would be wrong the moment the next attempt landed, and would
    need a job to keep it honest.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await practice_progress_service.build_practice_report(
        session,
        user=user,
        course_id=course.id,
        exercise_id=exercise_id,
        days=days,
    )


@router.post(
    "/practice/sessions",
    response_model=PracticeSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_practice_session(
    payload: PracticeSessionCreate,
    user: CurrentUser,
    session: DbSession,
) -> PracticeSessionOut:
    return await performance_service.create_session(session, payload, user)


@router.post(
    "/practice/sessions/{session_id}/attempts",
    response_model=PerformanceAttemptOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_performance_attempt(
    session_id: uuid.UUID,
    payload: PerformanceAttemptCreate,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PerformanceAttemptOut:
    return await performance_service.submit_attempt(
        session,
        session_id,
        payload,
        user,
        idempotency_key or "",
    )


@router.get("/practice/attempts/{attempt_id}", response_model=PerformanceAttemptOut)
async def get_performance_attempt(
    attempt_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> PerformanceAttemptOut:
    return await performance_service.get_attempt(session, attempt_id, user)


@router.post("/practice/attempts/{attempt_id}/speech", response_model=VoiceArtifactOut)
async def synthesize_attempt_speech(
    attempt_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    voice: str = "",
) -> VoiceArtifactOut:
    return await performance_service.synthesize_attempt_speech(session, attempt_id, user, voice_key=voice)


@router.post("/courses/{course_id}/practice/coach/tip", response_model=CoachLiveTipResponse)
async def get_live_coach_tip(
    course_id: uuid.UUID,
    payload: CoachLiveTipRequest,
    user: CurrentUser,
    session: DbSession,
) -> CoachLiveTipResponse:
    """Generate real-time pedagogical AI guidance tailored to current performance metrics."""
    return await coach_service.generate_live_tip(course_id, payload)

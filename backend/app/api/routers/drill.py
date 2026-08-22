from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.drill import DrillOut, GradeRequest, GradeResult, QuestionType
from app.services import drill_service

router = APIRouter(tags=["drill"])


@router.post("/api/nodes/{node_id}/drill", response_model=DrillOut, status_code=status.HTTP_201_CREATED)
async def start_drill(
    node_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    question_type: Annotated[QuestionType, Query()] = "short_answer",
) -> DrillOut:
    """Generate a question for a skill.

    Send an `Idempotency-Key` to make retries free: the same key returns the
    same attempt rather than paying for another generation call.
    """
    return await drill_service.start_drill(session, node_id, user, idempotency_key, question_type)


@router.post("/api/attempts/{attempt_id}/grade", response_model=GradeResult)
async def grade(
    attempt_id: uuid.UUID,
    payload: GradeRequest,
    user: CurrentUser,
    session: DbSession,
) -> GradeResult:
    """Grade an answer, award EXP, and advance the review schedule.

    Grading an already-graded attempt returns the stored result unchanged, so a
    retry after a dropped connection never awards EXP twice.
    """
    return await drill_service.grade_attempt(session, attempt_id, payload.answer, user)

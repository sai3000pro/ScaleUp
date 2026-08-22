"""n8n webhook boundary: signed, idempotent, replay-safe orchestration.

n8n owns scheduling and delivery; this service owns verification, dedupe, and
the side effects. Each endpoint is keyed by a caller-supplied ``event_id``: the
first delivery processes the event and stores the result in the ledger; any
replay of the same id answers from the ledger with ``status: duplicate`` and
never touches the underlying services again. That, plus the idempotency of the
services themselves (attempt submissions, voice synthesis, board building), is
what makes the webhook surface replay-safe.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PerformanceAttempt, User, WebhookEvent
from app.schemas.webhook import (
    DailyQuestsRefreshPayload,
    FeedbackRequestedPayload,
    SessionCompletedPayload,
    WebhookEnvelope,
    WebhookResult,
)
from app.services import performance_service, quest_service

logger = logging.getLogger(__name__)

SIGNATURE_PREFIX = "sha256="


def sign_payload(secret: str, body: bytes) -> str:
    """The exact `X-Webhook-Signature` value for `body` under `secret`."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


# @spec OPS-HOOK-001, OPS-HOOK-002
def verify_signature(secret: str, body: bytes, provided: str | None) -> bool:
    """Constant-time comparison of the provided signature against the expected one."""
    if not provided or not provided.startswith(SIGNATURE_PREFIX):
        return False
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, provided)


def payload_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def _process_session_completed(session: AsyncSession, payload: SessionCompletedPayload) -> dict:
    attempt = await session.get(PerformanceAttempt, payload.attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Performance attempt not found.")
    return {
        "attempt_id": str(attempt.id),
        "status": attempt.status,
        "overall_score": attempt.overall_score,
        "exp_awarded": attempt.exp_awarded,
        "has_feedback": attempt.feedback_summary is not None,
    }


async def _process_feedback_requested(session: AsyncSession, payload: FeedbackRequestedPayload) -> dict:
    attempt = await session.get(PerformanceAttempt, payload.attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Performance attempt not found.")
    result = {
        "attempt_id": str(attempt.id),
        "feedback_provider": attempt.feedback_provider or "deterministic",
        "feedback_persona": attempt.feedback_persona,
        "feedback_tone": attempt.feedback_tone,
        "feedback_summary": attempt.feedback_summary,
        "feedback_strengths": attempt.feedback_strengths or [],
        "feedback_corrections": attempt.feedback_corrections or [],
        "feedback_next_step": attempt.feedback_next_step,
    }
    if payload.voice:
        artifact = await performance_service.speech_for_attempt(session, attempt)
        result["voice"] = artifact.model_dump(mode="json")
    return result


async def _process_daily_quests_refresh(session: AsyncSession, payload: DailyQuestsRefreshPayload) -> dict:
    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    # The nightly "decay math" lives here, in the existing quest service. n8n
    # schedules the call; it does not reimplement the math, and nothing
    # time-derived is stored -- the board is computed on read and returned for
    # n8n to act on (notify, badge, etc.).
    board = await quest_service.build_board(session, user)
    return {
        "user_id": str(user.id),
        "date": str(board.date),
        "quest_count": len(board.quests),
        "total_reward_exp": board.total_reward_exp,
        "quests": [quest.model_dump(mode="json") for quest in board.quests],
    }


# @spec OPS-HOOK-003, OPS-HOOK-004, OPS-MIGRATE-005
async def dispatch(
    session: AsyncSession,
    event_type: str,
    payload: WebhookEnvelope,
    body_sha256: str,
) -> WebhookResult:
    """Verify, dedupe, process, and record one webhook event.

    The signature check happens in the router (it needs the raw bytes); this
    function assumes the event is authentic. The ledger row and the side
    effect share the session, so a duplicate id is caught by the primary key
    even under concurrency.
    """
    existing = await session.get(WebhookEvent, payload.event_id)
    if existing is not None:
        return WebhookResult(
            event_id=existing.event_id,
            event_type=existing.event_type,
            status="duplicate",
            correlation_id=existing.correlation_id,
            result=existing.result_json,
        )

    if event_type == "session.completed":
        result = await _process_session_completed(session, payload)
    elif event_type == "feedback.requested":
        result = await _process_feedback_requested(session, payload)
    elif event_type == "daily-quests.refresh":
        result = await _process_daily_quests_refresh(session, payload)
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown webhook event type: {event_type}")

    now = datetime.now(timezone.utc)
    session.add(
        WebhookEvent(
            event_id=payload.event_id,
            event_type=event_type,
            correlation_id=payload.correlation_id,
            payload_sha256=body_sha256,
            status="processed",
            result_json=result,
            processed_at=now,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent delivery won the insert for the same event id; the
        # primary key is the dedupe mechanism, so re-reading is the recovery.
        await session.rollback()
        settled = await session.get(WebhookEvent, payload.event_id)
        if settled is None:
            raise
        return WebhookResult(
            event_id=settled.event_id,
            event_type=settled.event_type,
            status="duplicate",
            correlation_id=settled.correlation_id,
            result=settled.result_json,
        )

    return WebhookResult(
        event_id=payload.event_id,
        event_type=event_type,
        status="processed",
        correlation_id=payload.correlation_id,
        result=result,
    )

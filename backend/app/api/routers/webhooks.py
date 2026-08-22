"""Signed, idempotent webhook endpoints for n8n orchestration.

These are the n8n seam (section 6 of docs/roadmap.md): n8n schedules delivery
of `session.completed`, `feedback.requested`, and `daily-quests.refresh`, while
all verification, dedupe, and side effects stay in the backend. The demo works
with n8n stopped -- the synchronous practice path does not depend on any of
these endpoints.

Authentication is an HMAC-SHA256 signature over the exact request bytes, sent
as `X-Webhook-Signature: sha256=<hex>`, keyed by WEBHOOK_SECRET. With no secret
configured the endpoints only answer when DEV_WEBHOOKS_ENABLED=true (the fake
runner and local tests), and the deployed config validator refuses to start
with DEPLOYED=true and an empty secret.

Replay-safety: every payload carries a caller-generated `event_id`; the first
delivery processes and records the result, any replay answers `duplicate` from
the ledger without re-executing.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.deps import DbSession
from app.config import get_settings
from app.schemas.webhook import (
    DailyQuestsRefreshPayload,
    FeedbackRequestedPayload,
    SessionCompletedPayload,
    WebhookResult,
)
from app.services import webhook_service

logger = logging.getLogger(__name__)

# One literal route per event type, so OpenAPI documents each contract with
# its own path and payload instead of a single `{event_type}` template. A new
# event type is a reviewed addition here; breaking changes bump the `/v1/`.
router = APIRouter(prefix="/api/webhooks/v1", tags=["webhooks"])


# @spec OPS-HOOK-005
async def _dispatch(
    event_type: str,
    payload_model: type[SessionCompletedPayload | FeedbackRequestedPayload | DailyQuestsRefreshPayload],
    request: Request,
    session: DbSession,
    signature: str | None,
    correlation_id: str | None,
) -> WebhookResult:
    settings = get_settings()

    body = await request.body()

    if settings.webhook_secret:
        if not webhook_service.verify_signature(settings.webhook_secret, body, signature):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature.")
    elif settings.dev_webhooks_enabled:
        logger.warning("accepting unsigned webhook (DEV_WEBHOOKS_ENABLED) -- never do this when deployed")
    else:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Webhooks are not configured: set WEBHOOK_SECRET or DEV_WEBHOOKS_ENABLED=true.",
        )

    try:
        payload = payload_model.model_validate_json(body)
    except Exception as exc:  # noqa: BLE001 - surface the pydantic detail as a 422
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid webhook payload: {exc}") from exc

    if payload.correlation_id is None and correlation_id:
        payload.correlation_id = correlation_id

    return await webhook_service.dispatch(
        session,
        event_type,
        payload,
        webhook_service.payload_sha256(body),
    )


@router.post("/session.completed", response_model=WebhookResult)
async def session_completed(
    request: Request,
    session: DbSession,
    signature: Annotated[str | None, Header(alias="X-Webhook-Signature")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> WebhookResult:
    return await _dispatch("session.completed", SessionCompletedPayload, request, session, signature, correlation_id)


@router.post("/feedback.requested", response_model=WebhookResult)
async def feedback_requested(
    request: Request,
    session: DbSession,
    signature: Annotated[str | None, Header(alias="X-Webhook-Signature")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> WebhookResult:
    return await _dispatch("feedback.requested", FeedbackRequestedPayload, request, session, signature, correlation_id)


@router.post("/daily-quests.refresh", response_model=WebhookResult)
async def daily_quests_refresh(
    request: Request,
    session: DbSession,
    signature: Annotated[str | None, Header(alias="X-Webhook-Signature")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> WebhookResult:
    return await _dispatch("daily-quests.refresh", DailyQuestsRefreshPayload, request, session, signature, correlation_id)

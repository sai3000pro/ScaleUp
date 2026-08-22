"""Signed, versioned webhook contracts consumed by n8n.

The URL carries the contract version (`/api/webhooks/v1/...`); a breaking
change is a new path, never a silent field change. Every payload carries a
caller-supplied ``event_id`` that makes the delivery idempotent: n8n retries
reuse the same id and the backend answers from its ledger instead of
re-executing the side effect.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WebhookEnvelope(BaseModel):
    # Dedupe key. Generate once per logical event; reuse it on retries.
    event_id: uuid.UUID
    # When the event actually happened, for auditability. Delivery time is
    # recorded by the ledger itself.
    occurred_at: datetime
    # Free-form trace id n8n passes through; echoed back in the response.
    correlation_id: str | None = Field(default=None, max_length=80)


class SessionCompletedPayload(WebhookEnvelope):
    attempt_id: uuid.UUID


class FeedbackRequestedPayload(WebhookEnvelope):
    attempt_id: uuid.UUID
    # When true, the response also synthesizes (and content-addressed caches)
    # the spoken feedback for this attempt.
    voice: bool = False


class DailyQuestsRefreshPayload(WebhookEnvelope):
    user_id: uuid.UUID


class WebhookResult(BaseModel):
    event_id: uuid.UUID
    event_type: str
    # `processed` is a first delivery; `duplicate` is a replay that was served
    # from the ledger without re-executing the side effect.
    status: Literal["processed", "duplicate"]
    correlation_id: str | None
    # Type-specific result payload; shapes are documented in
    # docs/api_contract.md (Webhooks section).
    result: dict[str, Any]

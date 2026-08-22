"""Deduplication ledger for n8n webhook events.

Every successfully processed webhook event is stored here, keyed by the
caller-supplied ``event_id``. Replaying the same event id returns the stored
result instead of re-executing the side effect, which is what makes the
endpoints replay-safe: n8n retries reuse the same id, and a duplicate id is a
lookup, not a second EXP award, second synthesis, or second quest pass.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (CheckConstraint("status IN ('processed', 'duplicate')", name="status_valid"),)

    # The caller's id, not ours: n8n retries reuse it, so the primary key is
    # the dedupe mechanism and concurrent duplicates resolve by re-reading the
    # row that won the insert.
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    # sha256 of the exact request body, so the ledger is a replayable audit log
    # of what was signed and sent.
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    # The stored response for this event id, so a replay answers identically
    # without touching the underlying services.
    result_json: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

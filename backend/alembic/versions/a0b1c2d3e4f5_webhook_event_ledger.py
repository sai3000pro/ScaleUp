"""add webhook event ledger

Revision ID: a0b1c2d3e4f5
Revises: 9d0e1f2a3b45
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "9d0e1f2a3b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_json", JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('processed', 'duplicate')", name=op.f("ck_webhook_events_status_valid")),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_webhook_events")),
    )
    op.create_index(op.f("ix_webhook_events_correlation_id"), "webhook_events", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_webhook_events_event_type"), "webhook_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_events_event_type"), table_name="webhook_events")
    op.drop_index(op.f("ix_webhook_events_correlation_id"), table_name="webhook_events")
    op.drop_table("webhook_events")

"""add voice artifact cache

Revision ID: 9d0e1f2a3b45
Revises: 8c9d0e1f2a34
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d0e1f2a3b45"
down_revision: str | None = "8c9d0e1f2a34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_artifacts",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("voice_key", sa.String(length=80), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("spoken_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["performance_attempts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_voice_artifacts")),
    )
    op.create_index(op.f("ix_voice_artifacts_attempt_id"), "voice_artifacts", ["attempt_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_voice_artifacts_attempt_id"), table_name="voice_artifacts")
    op.drop_table("voice_artifacts")

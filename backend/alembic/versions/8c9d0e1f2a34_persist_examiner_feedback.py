"""persist examiner feedback on attempts

Revision ID: 8c9d0e1f2a34
Revises: 7b8c9d0e1f23
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c9d0e1f2a34"
down_revision: str | None = "7b8c9d0e1f23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "performance_attempts",
        sa.Column("feedback_provider", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "performance_attempts",
        sa.Column("feedback_persona", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "performance_attempts",
        sa.Column("feedback_tone", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "performance_attempts",
        sa.Column("feedback_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "performance_attempts",
        sa.Column("feedback_strengths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "performance_attempts",
        sa.Column("feedback_corrections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "performance_attempts",
        sa.Column("feedback_next_step", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("performance_attempts", "feedback_next_step")
    op.drop_column("performance_attempts", "feedback_corrections")
    op.drop_column("performance_attempts", "feedback_strengths")
    op.drop_column("performance_attempts", "feedback_summary")
    op.drop_column("performance_attempts", "feedback_tone")
    op.drop_column("performance_attempts", "feedback_persona")
    op.drop_column("performance_attempts", "feedback_provider")

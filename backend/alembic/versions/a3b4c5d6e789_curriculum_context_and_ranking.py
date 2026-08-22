"""add learner context and source quality ranking

Revision ID: a3b4c5d6e789
Revises: f2c3d4e5a678
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3b4c5d6e789"
down_revision: str | None = "f2c3d4e5a678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "curriculum_proposals",
        sa.Column("learner_level", sa.String(length=16), server_default="beginner", nullable=False),
    )
    op.add_column(
        "curriculum_proposals",
        sa.Column("weekly_minutes", sa.Integer(), server_default="120", nullable=False),
    )
    op.add_column(
        "curriculum_proposals",
        sa.Column("format_preference", sa.String(length=16), server_default="mixed", nullable=False),
    )
    op.add_column(
        "curriculum_sources",
        sa.Column("quality_score", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "curriculum_sources",
        sa.Column(
            "quality_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("curriculum_sources", "quality_reasons")
    op.drop_column("curriculum_sources", "quality_score")
    op.drop_column("curriculum_proposals", "format_preference")
    op.drop_column("curriculum_proposals", "weekly_minutes")
    op.drop_column("curriculum_proposals", "learner_level")

"""questions store multiple-choice options

Revision ID: e1b2c3d4f567
Revises: d7a4b8c9e012
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1b2c3d4f567"
down_revision: str | None = "d7a4b8c9e012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("questions", sa.Column("correct_option_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "correct_option_id")
    op.drop_column("questions", "options")

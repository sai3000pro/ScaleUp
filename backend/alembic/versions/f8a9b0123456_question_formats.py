"""add cloze and static code question metadata

Revision ID: f8a9b0123456
Revises: e7f8a9b0123
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8a9b0123456"
down_revision: str | None = "e7f8a9b0123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("accepted_answers", postgresql.JSONB(), server_default="[]", nullable=False),
    )
    op.add_column("questions", sa.Column("code_language", sa.String(length=32), nullable=True))
    op.add_column(
        "questions",
        sa.Column("code_requirements", postgresql.JSONB(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("questions", "code_requirements")
    op.drop_column("questions", "code_language")
    op.drop_column("questions", "accepted_answers")

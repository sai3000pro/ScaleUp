"""add learner character profiles

Revision ID: d8e9f0a1b234
Revises: c5d6e7f89012
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8e9f0a1b234"
down_revision: str | None = "c5d6e7f89012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "character_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("character_name", sa.String(length=80), nullable=False),
        sa.Column("avatar_key", sa.String(length=32), server_default="owl", nullable=False),
        sa.Column("archetype", sa.String(length=32), server_default="scholar", nullable=False),
        sa.Column(
            "unlocked_perks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="pk_character_profiles"),
    )


def downgrade() -> None:
    op.drop_table("character_profiles")

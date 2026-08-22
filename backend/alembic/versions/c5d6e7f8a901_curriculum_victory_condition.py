"""add campaign victory conditions

Revision ID: c5d6e7f8a901
Revises: b4c5d6e7f890
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a901"
down_revision: str | None = "b4c5d6e7f890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "curriculum_proposals",
        sa.Column("target_outcome", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("curriculum_proposals", "target_outcome")

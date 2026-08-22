"""persist curriculum source discovery angle

Revision ID: a9b012345678
Revises: a1b2c3d4e5f6
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9b012345678"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "curriculum_sources",
        sa.Column("discovery_angle", sa.String(length=24), server_default="general", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("curriculum_sources", "discovery_angle")

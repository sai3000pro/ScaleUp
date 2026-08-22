"""add character appearance customization

Revision ID: e9f0a1b2c345
Revises: d8e9f0a1b234
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c345"
down_revision: str | None = "d8e9f0a1b234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("character_profiles", sa.Column("skin_tone", sa.String(length=32), server_default="sand", nullable=False))
    op.add_column("character_profiles", sa.Column("hair_style", sa.String(length=32), server_default="sweep", nullable=False))
    op.add_column("character_profiles", sa.Column("hair_color", sa.String(length=32), server_default="chestnut", nullable=False))
    op.add_column("character_profiles", sa.Column("outfit_color", sa.String(length=32), server_default="azure", nullable=False))
    op.add_column("character_profiles", sa.Column("accessory", sa.String(length=32), server_default="none", nullable=False))


def downgrade() -> None:
    op.drop_column("character_profiles", "accessory")
    op.drop_column("character_profiles", "outfit_color")
    op.drop_column("character_profiles", "hair_color")
    op.drop_column("character_profiles", "hair_style")
    op.drop_column("character_profiles", "skin_tone")

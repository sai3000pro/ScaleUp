"""record explicit source-policy check times

Revision ID: c5d6e7f89012
Revises: c0123456789b, e7f8a9b0123
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f89012"
down_revision: tuple[str, str] = ("c0123456789b", "e7f8a9b0123")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("curriculum_sources", sa.Column("policy_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("curriculum_sources", "policy_checked_at")

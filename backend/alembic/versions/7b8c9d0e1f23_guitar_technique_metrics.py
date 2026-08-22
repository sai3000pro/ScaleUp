"""add guitar technique metrics

Revision ID: 7b8c9d0e1f23
Revises: 6a7b8c9d0e12
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7b8c9d0e1f23"
down_revision: str | None = "6a7b8c9d0e12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "performance_metric_bundles",
        sa.Column("technique_accuracy", sa.Float(), nullable=True),
    )
    op.add_column(
        "performance_metric_bundles",
        sa.Column("position_error_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("performance_metric_bundles", "position_error_count")
    op.drop_column("performance_metric_bundles", "technique_accuracy")

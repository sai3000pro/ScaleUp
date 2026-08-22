"""instrument intonation and rhythm metrics

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drums are rhythm-only: pitch is inapplicable, so existing rows keep their
    # values and new rhythm-only rows may store NULL.
    op.alter_column("performance_metric_bundles", "pitch_accuracy", existing_type=sa.Float(), nullable=True)
    op.add_column(
        "performance_metric_bundles",
        sa.Column("intonation_accuracy", sa.Float(), nullable=True),
    )
    op.add_column(
        "performance_metric_bundles",
        sa.Column("intonation_deviation_cents", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("performance_metric_bundles", "intonation_deviation_cents")
    op.drop_column("performance_metric_bundles", "intonation_accuracy")
    op.alter_column("performance_metric_bundles", "pitch_accuracy", existing_type=sa.Float(), nullable=False)

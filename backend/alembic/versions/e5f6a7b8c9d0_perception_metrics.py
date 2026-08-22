"""Dynamics, posture, and analyzer provenance on the metric bundle.

Every column is nullable with no backfill, deliberately. For an attempt recorded
before these existed the values are genuinely unknown, and NULL is the only
honest way to say so -- a default of 0.0 would retroactively assert that every
historical take had no dynamic contrast and bad posture.

`posture_metrics` stores the per-metric readings including the raw geometric
value each came from. Without that, the posture thresholds could never be
retuned against real data, which would make every posture number permanently
unauditable.

Revision ID: e5f6a7b8c9d0
Revises: c2d3e4f5a6b7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# @spec OPS-MIGRATE-004
revision = "e5f6a7b8c9d0"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("dynamics_accuracy", sa.Float()),
    ("dynamic_range_db", sa.Float()),
    ("dynamics_contrast", sa.Float()),
    ("posture_accuracy", sa.Float()),
    ("posture_version", sa.String(32)),
    ("posture_metrics", postgresql.JSONB()),
    ("analyzer", sa.String(24)),
)


def upgrade() -> None:
    for name, column_type in _COLUMNS:
        op.add_column("performance_metric_bundles", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("performance_metric_bundles", name)

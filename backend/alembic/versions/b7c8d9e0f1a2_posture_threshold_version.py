"""Persist the threshold version submitted with a posture observation.

Revision ID: b7c8d9e0f1a2
Revises: f6a7b8c9d0e1
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# @spec OBS-RED-008
def upgrade() -> None:
    op.add_column(
        "performance_metric_bundles",
        sa.Column("posture_threshold_version", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("performance_metric_bundles", "posture_threshold_version")

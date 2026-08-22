"""ingest jobs record the worker start time

Revision ID: d7a4b8c9e012
Revises: c3f1a7d40b52
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a4b8c9e012"
down_revision: str | None = "c3f1a7d40b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingest_jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ingest_jobs", "started_at")

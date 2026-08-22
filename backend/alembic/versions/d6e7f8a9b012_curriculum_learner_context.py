"""persist richer learner context for curriculum proposals

Revision ID: d6e7f8a9b012
Revises: c5d6e7f8a901
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b012"
down_revision: str | None = "c5d6e7f8a901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "curriculum_proposals",
        sa.Column("prior_knowledge", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "curriculum_proposals",
        sa.Column("application_context", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("curriculum_proposals", "application_context")
    op.drop_column("curriculum_proposals", "prior_knowledge")

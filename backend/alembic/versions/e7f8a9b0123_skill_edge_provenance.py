"""store source chunk provenance for prerequisite edges

Revision ID: e7f8a9b0123
Revises: d6e7f8a9b012
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7f8a9b0123"
down_revision: str | None = "d6e7f8a9b012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_edges",
        sa.Column(
            "source_chunk_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default="{}",
            nullable=False,
        ),
    )
    # Existing edges were already grounded by their target node's passages;
    # preserve that evidence instead of making provenance appear only after the
    # next full graph rebuild.
    op.execute(
        """
        UPDATE skill_edges AS edge
        SET source_chunk_ids = node.source_chunk_ids
        FROM skill_nodes AS node
        WHERE edge.target_id = node.id
        """
    )


def downgrade() -> None:
    op.drop_column("skill_edges", "source_chunk_ids")

"""skill nodes carry their outline section as a label

The outline stops contributing edges and structural nodes; it contributes this
column instead. See `app.ingestion.toc.section_labels`.

Autogenerate also proposed dropping `uq_courses_owner_copy`, the
`course_shares.token_hash` index, and rewriting four unique constraints into
unique indexes. None of that is this change -- it is naming-convention drift
between the model metadata and what is actually in the database, and applying it
would drop live constraints. Only the column is kept here; the drift is a
separate question with its own migration.

Revision ID: 49db625e8d49
Revises: e9f0a1b2c345
Create Date: 2026-08-18 19:23:29.431044
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# @spec OPS-MIGRATE-003, OPS-MIGRATE-006
revision: str = "49db625e8d49"
down_revision: str | None = "e9f0a1b2c345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("skill_nodes", sa.Column("section", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("skill_nodes", "section")

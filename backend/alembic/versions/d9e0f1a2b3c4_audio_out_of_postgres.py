"""Audio bytes move from Postgres columns to object storage.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3

Recordings and synthesised voice artifacts gain a `storage_path` pointing at the
object store (content-addressed, so identical bytes are stored once). `content`
becomes nullable: rows written before this revision keep their bytes there and
are still readable; every row written after it leaves the column NULL. Nothing
is copied in this migration -- the thirty-day audio retention window removes
the pre-move rows on its own schedule.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# @spec OPS-STORE-004
def upgrade() -> None:
    for table in ("recordings", "voice_artifacts"):
        op.add_column(table, sa.Column("storage_path", sa.Text(), nullable=True))
        op.alter_column(table, "content", existing_type=sa.LargeBinary(), nullable=True)


def downgrade() -> None:
    for table in ("recordings", "voice_artifacts"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE content IS NULL"))
        op.alter_column(table, "content", existing_type=sa.LargeBinary(), nullable=False)
        op.drop_column(table, "storage_path")

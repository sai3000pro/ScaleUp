"""preserved practice recordings

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recordings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["performance_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recordings")),
        sa.UniqueConstraint("user_id", "content_sha256", name=op.f("uq_recordings_user_hash")),
    )
    op.create_index(op.f("ix_recordings_attempt_id"), "recordings", ["attempt_id"], unique=False)
    op.create_index(op.f("ix_recordings_course_id"), "recordings", ["course_id"], unique=False)
    op.create_index(op.f("ix_recordings_user_id"), "recordings", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_recordings_user_id"), table_name="recordings")
    op.drop_index(op.f("ix_recordings_course_id"), table_name="recordings")
    op.drop_index(op.f("ix_recordings_attempt_id"), table_name="recordings")
    op.drop_table("recordings")

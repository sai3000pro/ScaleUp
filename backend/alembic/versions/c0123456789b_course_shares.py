"""add course shares and copy provenance

Revision ID: c0123456789b
Revises: b0123456789a
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0123456789b"
down_revision: str | None = "b0123456789a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "course_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_course_shares"),
        sa.UniqueConstraint("course_id", name="uq_course_shares_course_id"),
        sa.UniqueConstraint("token_hash", name="uq_course_shares_token_hash"),
    )
    op.create_index("ix_course_shares_course_id", "course_shares", ["course_id"], unique=False)
    op.create_index("ix_course_shares_token_hash", "course_shares", ["token_hash"], unique=False)

    op.add_column("courses", sa.Column("copied_from_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_courses_copied_from_id_courses",
        "courses",
        "courses",
        ["copied_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_courses_copied_from_id", "courses", ["copied_from_id"], unique=False)
    # One learner copies a given course at most once; a second copy returns the
    # first instead of duplicating the tree.
    op.create_index(
        "uq_courses_owner_copy",
        "courses",
        ["owner_id", "copied_from_id"],
        unique=True,
        postgresql_where=sa.text("copied_from_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_courses_owner_copy", table_name="courses")
    op.drop_index("ix_courses_copied_from_id", table_name="courses")
    op.drop_constraint("fk_courses_copied_from_id_courses", "courses", type_="foreignkey")
    op.drop_column("courses", "copied_from_id")
    op.drop_index("ix_course_shares_token_hash", table_name="course_shares")
    op.drop_index("ix_course_shares_course_id", table_name="course_shares")
    op.drop_table("course_shares")

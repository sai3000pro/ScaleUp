"""add bounded curriculum proposals

Revision ID: f2c3d4e5a678
Revises: e1b2c3d4f567
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c3d4e5a678"
down_revision: str | None = "e1b2c3d4f567"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "curriculum_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','approved','ingesting','completed')",
            name=op.f("ck_curriculum_proposals_status_valid"),
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculum_proposals")),
    )
    op.create_index(op.f("ix_curriculum_proposals_course_id"), "curriculum_proposals", ["course_id"], unique=False)
    op.create_index(op.f("ix_curriculum_proposals_owner_id"), "curriculum_proposals", ["owner_id"], unique=False)

    op.create_table(
        "curriculum_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("snippet", sa.Text(), server_default="", nullable=False),
        sa.Column("published_at", sa.String(length=80), nullable=True),
        sa.Column("selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="proposed", nullable=False),
        sa.Column("ingest_job_id", sa.Uuid(), nullable=True),
        sa.Column("ingest_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed','approved','ingesting','ingested','failed')",
            name=op.f("ck_curriculum_sources_status_valid"),
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["curriculum_proposals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculum_sources")),
    )
    op.create_index(op.f("ix_curriculum_sources_proposal_id"), "curriculum_sources", ["proposal_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_curriculum_sources_proposal_id"), table_name="curriculum_sources")
    op.drop_table("curriculum_sources")
    op.drop_index(op.f("ix_curriculum_proposals_owner_id"), table_name="curriculum_proposals")
    op.drop_index(op.f("ix_curriculum_proposals_course_id"), table_name="curriculum_proposals")
    op.drop_table("curriculum_proposals")

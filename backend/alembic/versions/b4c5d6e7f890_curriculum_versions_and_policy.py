"""version curriculum proposals and record source-policy review state

Revision ID: b4c5d6e7f890
Revises: a3b4c5d6e789
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4c5d6e7f890"
down_revision: str | None = "a3b4c5d6e789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "curriculum_proposals",
        sa.Column("proposal_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("curriculum_proposals", sa.Column("supersedes_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_curriculum_proposals_supersedes_id"),
        "curriculum_proposals",
        ["supersedes_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_curriculum_proposals_supersedes_id_curriculum_proposals"),
        "curriculum_proposals",
        "curriculum_proposals",
        ["supersedes_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "curriculum_sources",
        sa.Column("policy_status", sa.String(length=24), server_default="review_required", nullable=False),
    )
    op.add_column(
        "curriculum_sources",
        sa.Column("robots_url", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "curriculum_sources",
        sa.Column("robots_status", sa.String(length=16), server_default="not_checked", nullable=False),
    )
    op.add_column(
        "curriculum_sources",
        sa.Column("license_status", sa.String(length=24), server_default="not_identified", nullable=False),
    )
    op.add_column(
        "curriculum_sources",
        sa.Column(
            "policy_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "curriculum_sources",
        sa.Column("policy_acknowledged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("curriculum_sources", "policy_acknowledged")
    op.drop_column("curriculum_sources", "policy_reasons")
    op.drop_column("curriculum_sources", "license_status")
    op.drop_column("curriculum_sources", "robots_status")
    op.drop_column("curriculum_sources", "robots_url")
    op.drop_column("curriculum_sources", "policy_status")
    op.drop_constraint(
        op.f("fk_curriculum_proposals_supersedes_id_curriculum_proposals"),
        "curriculum_proposals",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_curriculum_proposals_supersedes_id"), table_name="curriculum_proposals")
    op.drop_column("curriculum_proposals", "supersedes_id")
    op.drop_column("curriculum_proposals", "proposal_version")

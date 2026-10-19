"""Skill transitions between curriculum versions.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


# @spec CURR-GRAPH-006
def upgrade() -> None:
    op.create_table(
        "skill_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("from_slugs", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("to_slugs", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("rationale", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('split', 'merge', 'rename', 'retire')", name=op.f("ck_skill_transitions_skill_transitions_kind")
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_version_id"],
            ["curriculum_versions.id"],
            name=op.f("fk_skill_transitions_curriculum_version_id_curriculum_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_transitions")),
    )
    op.create_index("ix_skill_transitions_version_id", "skill_transitions", ["curriculum_version_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_transitions_version_id", table_name="skill_transitions")
    op.drop_table("skill_transitions")

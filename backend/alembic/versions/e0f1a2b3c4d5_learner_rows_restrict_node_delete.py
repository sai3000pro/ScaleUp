"""Learner rows restrict skill-node deletion; nodes retire in place instead.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None

LEARNER_TABLES = (("node_progress", "node_progress_node_id_fkey"), ("attempts", "attempts_node_id_fkey"))


def _repoint(table: str, name: str, ondelete: str) -> None:
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, "skill_nodes", ["node_id"], ["id"], ondelete=ondelete)


# @spec CURR-GRAPH-005
def upgrade() -> None:
    op.add_column("skill_nodes", sa.Column("retired_at", sa.DateTime(), nullable=True))
    for table, name in LEARNER_TABLES:
        _repoint(table, name, "RESTRICT")


def downgrade() -> None:
    for table, name in LEARNER_TABLES:
        _repoint(table, name, "CASCADE")
    op.drop_column("skill_nodes", "retired_at")

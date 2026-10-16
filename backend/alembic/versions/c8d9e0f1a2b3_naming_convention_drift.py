"""Settle the naming-convention drift between the models and the live schema.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2

Two earlier revisions each noticed that `alembic revision --autogenerate`
proposed dropping unique constraints and rewriting indexes that no model change
asked for, and each deferred the fix. This revision is that fix, so a generated
diff contains only what a model change intends.

The disagreement has one shape: a column declared `unique=True, index=True`
means one *unique index* under the metadata naming convention, while the first
migration for each table wrote a separate `uq_` constraint plus a non-unique
`ix_` index. Both forms enforce the same rule; this revision moves the live
schema to the model's form. One column default is settled the same way. Nothing here changes what any row may contain.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column): a `uq_` constraint plus a non-unique `ix_` index become one unique index.
UNIQUE_INDEXED = (
    ("course_shares", "course_id"),
    ("oauth_exchange_codes", "code_hash"),
    ("oauth_states", "state_hash"),
    ("password_reset_tokens", "token_hash"),
    ("performance_metric_bundles", "attempt_id"),
    ("refresh_sessions", "token_hash"),
)


# @spec OPS-MIGRATE-006
def upgrade() -> None:
    for table, column in UNIQUE_INDEXED:
        op.drop_constraint(f"uq_{table}_{column}", table, type_="unique")
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=True)

    # `token_hash` on course_shares is unique but not separately indexed in the
    # model; the unique constraint's own index is the lookup path.
    op.drop_index("ix_course_shares_token_hash", table_name="course_shares")

    op.alter_column("questions", "question_type", server_default="short_answer")


def downgrade() -> None:
    op.alter_column("questions", "question_type", server_default=None)
    op.create_index("ix_course_shares_token_hash", "course_shares", ["token_hash"], unique=False)
    for table, column in reversed(UNIQUE_INDEXED):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)
        op.create_unique_constraint(f"uq_{table}_{column}", table, [column])


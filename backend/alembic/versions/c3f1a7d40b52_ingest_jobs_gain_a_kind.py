"""ingest_jobs gain a kind discriminator; document_id becomes conditional

Adds the `reindex` job kind. A reindex rebuilds the derived stores (Chroma and
Neo4j) for a whole course from Postgres, so it has no single document to point
at -- but an *ingest* still must have one.

Rather than dropping the NOT NULL (which would allow a document-less ingest row,
a shape nothing in the pipeline can execute), the invariant is made conditional
on the new `kind` column:

    kind = 'ingest'  -> document_id IS NOT NULL
    kind = 'reindex' -> document_id IS NULL

Revision ID: c3f1a7d40b52
Revises: b8e9530ac08a
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f1a7d40b52"
down_revision: str | None = "b8e9530ac08a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("kind", sa.String(length=16), server_default="ingest", nullable=False),
    )
    op.alter_column("ingest_jobs", "document_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint("kind_valid", "ingest_jobs", "kind IN ('ingest','reindex')")
    op.create_check_constraint(
        "kind_document",
        "ingest_jobs",
        "(kind = 'ingest' AND document_id IS NOT NULL) OR (kind = 'reindex' AND document_id IS NULL)",
    )


def downgrade() -> None:
    """LOSSY, deliberately and unavoidably.

    Re-tightening `document_id` to NOT NULL cannot succeed while any reindex row
    exists, and a reindex row has no document to invent one from -- it never
    referenced a document, so there is nothing to preserve. They are deleted.

    Reindex jobs are pure bookkeeping about a rebuild of derived data: losing the
    history of one loses no user data and no course content. That is the only
    reason this downgrade is acceptable at all.
    """
    op.execute(sa.text("DELETE FROM ingest_jobs WHERE kind = 'reindex'"))
    op.drop_constraint("kind_document", "ingest_jobs", type_="check")
    op.drop_constraint("kind_valid", "ingest_jobs", type_="check")
    op.alter_column("ingest_jobs", "document_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("ingest_jobs", "kind")

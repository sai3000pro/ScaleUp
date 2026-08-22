"""add immutable, reviewable curriculum graph versions

Revision ID: 5f6a7b8c9d01
Revises: 49db625e8d49
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5f6a7b8c9d01"
down_revision: str | None = "49db625e8d49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instruments")),
        sa.UniqueConstraint("slug", name=op.f("uq_instruments_slug")),
    )

    op.create_table(
        "curriculum_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("compiler_version", sa.String(length=32), server_default="curriculum-compiler-v1", nullable=False),
        sa.Column("source_bundle_sha256", sa.String(length=64), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'review', 'published', 'retired')",
            name=op.f("ck_curriculum_versions_status_valid"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_curriculum_versions_version_positive")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["curriculum_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculum_versions")),
        sa.UniqueConstraint("course_id", "slug", "version", name="course_curriculum_version"),
    )
    op.create_index(op.f("ix_curriculum_versions_course_id"), "curriculum_versions", ["course_id"], unique=False)
    op.create_index(op.f("ix_curriculum_versions_instrument_id"), "curriculum_versions", ["instrument_id"], unique=False)
    op.create_index(op.f("ix_curriculum_versions_supersedes_id"), "curriculum_versions", ["supersedes_id"], unique=False)

    op.create_table(
        "skill_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False),
        sa.Column("assessable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name=op.f("ck_skill_definitions_difficulty_range")),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_definitions")),
        sa.UniqueConstraint("instrument_id", "slug", name="instrument_skill_slug"),
    )
    op.create_index(op.f("ix_skill_definitions_instrument_id"), "skill_definitions", ["instrument_id"], unique=False)

    op.create_table(
        "curriculum_nodes",
        sa.Column("curriculum_version_id", sa.Uuid(), nullable=False),
        sa.Column("skill_definition_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("section", sa.String(length=120), nullable=True),
        sa.Column("source_chunk_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("assessment_capability", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_definition_id"], ["skill_definitions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("curriculum_version_id", "skill_definition_id", name=op.f("pk_curriculum_nodes")),
        sa.UniqueConstraint("curriculum_version_id", "skill_definition_id", name="curriculum_node_skill"),
    )
    op.create_index(op.f("ix_curriculum_nodes_version_id"), "curriculum_nodes", ["curriculum_version_id"], unique=False)

    op.create_table(
        "prerequisite_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_version_id", sa.Uuid(), nullable=False),
        sa.Column("prereq_skill_id", sa.Uuid(), nullable=False),
        sa.Column("target_skill_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("support", sa.Integer(), server_default="1", nullable=False),
        sa.Column("relation_type", sa.String(length=32), server_default="prerequisite", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=32), nullable=True),
        sa.Column("cycle_path", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'accepted', 'rejected', 'ambiguous')",
            name=op.f("ck_prerequisite_candidates_status_valid"),
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_prerequisite_candidates_confidence_range")),
        sa.ForeignKeyConstraint(["curriculum_version_id"], ["curriculum_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prereq_skill_id"], ["skill_definitions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_skill_id"], ["skill_definitions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prerequisite_candidates")),
        sa.UniqueConstraint(
            "curriculum_version_id",
            "prereq_skill_id",
            "target_skill_id",
            name="curriculum_candidate_edge",
        ),
    )
    op.create_index(
        op.f("ix_prerequisite_candidates_version_id"),
        "prerequisite_candidates",
        ["curriculum_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prerequisite_candidates_version_status"),
        "prerequisite_candidates",
        ["curriculum_version_id", "status"],
        unique=False,
    )

    op.create_table(
        "curriculum_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["prerequisite_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculum_evidence")),
    )
    op.create_index(op.f("ix_curriculum_evidence_candidate_id"), "curriculum_evidence", ["candidate_id"], unique=False)

    op.create_table(
        "curriculum_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected', 'ambiguous')",
            name=op.f("ck_curriculum_reviews_decision_valid"),
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["prerequisite_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculum_reviews")),
    )
    op.create_index(op.f("ix_curriculum_reviews_candidate_id"), "curriculum_reviews", ["candidate_id"], unique=False)
    op.create_index(op.f("ix_curriculum_reviews_reviewer_id"), "curriculum_reviews", ["reviewer_id"], unique=False)

    op.add_column(
        "skill_nodes",
        sa.Column("curriculum_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "skill_nodes",
        sa.Column("skill_definition_id", sa.Uuid(), nullable=True),
    )
    op.create_index(op.f("ix_skill_nodes_curriculum_version_id"), "skill_nodes", ["curriculum_version_id"], unique=False)
    op.create_index(op.f("ix_skill_nodes_skill_definition_id"), "skill_nodes", ["skill_definition_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_skill_nodes_curriculum_version_id_curriculum_versions"),
        "skill_nodes",
        "curriculum_versions",
        ["curriculum_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_skill_nodes_skill_definition_id_skill_definitions"),
        "skill_nodes",
        "skill_definitions",
        ["skill_definition_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_skill_nodes_skill_definition_id_skill_definitions"), "skill_nodes", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_skill_nodes_curriculum_version_id_curriculum_versions"), "skill_nodes", type_="foreignkey"
    )
    op.drop_index(op.f("ix_skill_nodes_skill_definition_id"), table_name="skill_nodes")
    op.drop_index(op.f("ix_skill_nodes_curriculum_version_id"), table_name="skill_nodes")
    op.drop_column("skill_nodes", "skill_definition_id")
    op.drop_column("skill_nodes", "curriculum_version_id")
    op.drop_index(op.f("ix_curriculum_reviews_reviewer_id"), table_name="curriculum_reviews")
    op.drop_index(op.f("ix_curriculum_reviews_candidate_id"), table_name="curriculum_reviews")
    op.drop_table("curriculum_reviews")
    op.drop_index(op.f("ix_curriculum_evidence_candidate_id"), table_name="curriculum_evidence")
    op.drop_table("curriculum_evidence")
    op.drop_index(op.f("ix_prerequisite_candidates_version_status"), table_name="prerequisite_candidates")
    op.drop_index(op.f("ix_prerequisite_candidates_version_id"), table_name="prerequisite_candidates")
    op.drop_table("prerequisite_candidates")
    op.drop_index(op.f("ix_curriculum_nodes_version_id"), table_name="curriculum_nodes")
    op.drop_table("curriculum_nodes")
    op.drop_index(op.f("ix_skill_definitions_instrument_id"), table_name="skill_definitions")
    op.drop_table("skill_definitions")
    op.drop_index(op.f("ix_curriculum_versions_supersedes_id"), table_name="curriculum_versions")
    op.drop_index(op.f("ix_curriculum_versions_instrument_id"), table_name="curriculum_versions")
    op.drop_index(op.f("ix_curriculum_versions_course_id"), table_name="curriculum_versions")
    op.drop_table("curriculum_versions")
    op.drop_table("instruments")
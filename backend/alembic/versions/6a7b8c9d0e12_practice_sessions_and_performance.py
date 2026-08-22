"""add instrument practice and performance records

Revision ID: 6a7b8c9d0e12
Revises: 5f6a7b8c9d01
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6a7b8c9d0e12"
down_revision: str | None = "5f6a7b8c9d01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "score_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("format", sa.String(length=16), server_default="musicxml", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("tempo_bpm", sa.Float(), nullable=False),
        sa.Column("duration_beats", sa.Float(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("format IN ('musicxml')", name=op.f("ck_score_assets_format_valid")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_assets")),
        sa.UniqueConstraint("course_id", "content_sha256", name="course_score_hash"),
    )
    op.create_index(op.f("ix_score_assets_course_id"), "score_assets", ["course_id"], unique=False)

    op.create_table(
        "exercises",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("score_asset_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("evaluator_version", sa.String(length=32), server_default="piano-dtw-v1", nullable=False),
        sa.Column("difficulty", sa.Integer(), server_default="3", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name=op.f("ck_exercises_difficulty_range")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["skill_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["score_asset_id"], ["score_assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exercises")),
        sa.UniqueConstraint("course_id", "slug", name="course_exercise_slug"),
    )
    op.create_index(op.f("ix_exercises_course_id"), "exercises", ["course_id"], unique=False)
    op.create_index(op.f("ix_exercises_node_id"), "exercises", ["node_id"], unique=False)

    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'completed', 'cancelled')", name=op.f("ck_practice_sessions_status_valid")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_sessions")),
    )
    op.create_index(op.f("ix_practice_sessions_user_id"), "practice_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_practice_sessions_course_id"), "practice_sessions", ["course_id"], unique=False)
    op.create_index(op.f("ix_practice_sessions_exercise_id"), "practice_sessions", ["exercise_id"], unique=False)

    op.create_table(
        "performance_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observed_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("alignment_confidence", sa.Float(), nullable=False),
        sa.Column("exp_awarded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed', 'needs_review', 'failed')",
            name=op.f("ck_performance_attempts_status_valid"),
        ),
        sa.CheckConstraint("overall_score BETWEEN 0 AND 1", name=op.f("ck_performance_attempts_overall_score_range")),
        sa.ForeignKeyConstraint(["session_id"], ["practice_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_attempts")),
        sa.UniqueConstraint("user_id", "idempotency_key", name="performance_user_idempotency"),
    )
    op.create_index(op.f("ix_performance_attempts_session_id"), "performance_attempts", ["session_id"], unique=False)
    op.create_index(op.f("ix_performance_attempts_user_id"), "performance_attempts", ["user_id"], unique=False)
    op.create_index(op.f("ix_performance_attempts_course_id"), "performance_attempts", ["course_id"], unique=False)
    op.create_index(op.f("ix_performance_attempts_exercise_id"), "performance_attempts", ["exercise_id"], unique=False)

    op.create_table(
        "performance_metric_bundles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("evaluator_version", sa.String(length=32), nullable=False),
        sa.Column("expected_note_count", sa.Integer(), nullable=False),
        sa.Column("observed_note_count", sa.Integer(), nullable=False),
        sa.Column("matched_note_count", sa.Integer(), nullable=False),
        sa.Column("missed_note_count", sa.Integer(), nullable=False),
        sa.Column("extra_note_count", sa.Integer(), nullable=False),
        sa.Column("pitch_accuracy", sa.Float(), nullable=False),
        sa.Column("rhythm_accuracy", sa.Float(), nullable=False),
        sa.Column("tempo_bpm", sa.Float(), nullable=True),
        sa.Column("tempo_deviation_percent", sa.Float(), nullable=True),
        sa.Column("alignment_confidence", sa.Float(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("low_confidence", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["performance_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_metric_bundles")),
        sa.UniqueConstraint("attempt_id", name=op.f("uq_performance_metric_bundles_attempt_id")),
    )
    op.create_index(
        op.f("ix_performance_metric_bundles_attempt_id"),
        "performance_metric_bundles",
        ["attempt_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_performance_metric_bundles_attempt_id"), table_name="performance_metric_bundles")
    op.drop_table("performance_metric_bundles")
    op.drop_constraint(op.f("performance_user_idempotency"), "performance_attempts", type_="unique")
    op.drop_index(op.f("ix_performance_attempts_exercise_id"), table_name="performance_attempts")
    op.drop_index(op.f("ix_performance_attempts_course_id"), table_name="performance_attempts")
    op.drop_index(op.f("ix_performance_attempts_user_id"), table_name="performance_attempts")
    op.drop_index(op.f("ix_performance_attempts_session_id"), table_name="performance_attempts")
    op.drop_table("performance_attempts")
    op.drop_index(op.f("ix_practice_sessions_exercise_id"), table_name="practice_sessions")
    op.drop_index(op.f("ix_practice_sessions_course_id"), table_name="practice_sessions")
    op.drop_index(op.f("ix_practice_sessions_user_id"), table_name="practice_sessions")
    op.drop_table("practice_sessions")
    op.drop_index(op.f("ix_exercises_node_id"), table_name="exercises")
    op.drop_index(op.f("ix_exercises_course_id"), table_name="exercises")
    op.drop_table("exercises")
    op.drop_index(op.f("ix_score_assets_course_id"), table_name="score_assets")
    op.drop_table("score_assets")

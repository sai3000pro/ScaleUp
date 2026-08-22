"""Instrument exercises and persisted performance evaluation records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScoreAsset(Base):
    __tablename__ = "score_assets"
    __table_args__ = (
        CheckConstraint("format IN ('musicxml')", name="format_valid"),
        UniqueConstraint("course_id", "content_sha256", name="course_score_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(16), default="musicxml", server_default="musicxml")
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    tempo_bpm: Mapped[float] = mapped_column(Float)
    duration_beats: Mapped[float] = mapped_column(Float)
    asset_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())



class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="course_exercise_slug"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill_nodes.id", ondelete="CASCADE"), index=True)
    score_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("score_assets.id", ondelete="RESTRICT"))
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text)
    evaluator_version: Mapped[str] = mapped_column(String(32), default="piano-dtw-v1", server_default="piano-dtw-v1")
    difficulty: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())



class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    __table_args__ = (CheckConstraint("status IN ('active', 'completed', 'cancelled')", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class PerformanceAttempt(Base):
    __tablename__ = "performance_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('completed', 'needs_review', 'failed')", name="status_valid"),
        CheckConstraint("overall_score BETWEEN 0 AND 1", name="overall_score_range"),
        UniqueConstraint("user_id", "idempotency_key", name="performance_user_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    observed_notes: Mapped[list] = mapped_column(JSONB)
    overall_score: Mapped[float] = mapped_column(Float)
    alignment_confidence: Mapped[float] = mapped_column(Float)
    exp_awarded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    feedback_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feedback_persona: Mapped[str | None] = mapped_column(String(80), nullable=True)
    feedback_tone: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_strengths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    feedback_corrections: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    feedback_next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())



class StoredVoiceArtifact(Base):
    """Content-addressed cache of synthesized feedback audio.

    Keyed by ``cache_key`` (sha256 over voice_key + spoken_text), so the same
    text spoken with the same voice is synthesized at most once -- repeat
    requests are served from here instead of billing another ElevenLabs call.
    The idempotency key is the primary key, which makes concurrent duplicates a
    constraint violation the service rolls back and recovers from.
    """

    __tablename__ = "voice_artifacts"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("performance_attempts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    voice_key: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(8))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    spoken_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Recording(Base):
    """Content-addressed original audio for one practice take.

    The browser's pitch detector extracts canonical notes, but the raw take is
    the evidence those notes came from -- preserved here, deduplicated by
    (user, content sha256), and deletable by its owner. The bytes live in
    Postgres like voice artifacts do; recordings are short demo clips, not
    media-library uploads.
    """

    __tablename__ = "recordings"
    __table_args__ = (UniqueConstraint("user_id", "content_sha256", name="recording_user_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("performance_attempts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(16))
    byte_size: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PerformanceMetricBundle(Base):
    __tablename__ = "performance_metric_bundles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performance_attempts.id", ondelete="CASCADE"), unique=True, index=True
    )
    evaluator_version: Mapped[str] = mapped_column(String(32))
    expected_note_count: Mapped[int] = mapped_column(Integer)
    observed_note_count: Mapped[int] = mapped_column(Integer)
    matched_note_count: Mapped[int] = mapped_column(Integer)
    missed_note_count: Mapped[int] = mapped_column(Integer)
    extra_note_count: Mapped[int] = mapped_column(Integer)
    # Nullable because drums are rhythm-only: pitch is inapplicable, not zero.
    pitch_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    rhythm_accuracy: Mapped[float] = mapped_column(Float)
    technique_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    intonation_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    intonation_deviation_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Dynamics: how loudly the learner played relative to what was written.
    # Nullable because a score with no dynamic markings has no dynamics to get
    # wrong, and because a take from before this existed genuinely has no value
    # -- NULL says that, where 0.0 would claim a failure.
    dynamics_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    dynamic_range_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    dynamics_contrast: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Physical form from browser-derived landmarks. A NEW column rather than a
    # reuse of `technique_accuracy`, which already means guitar fretboard
    # position -- folding posture into it would change what every stored guitar
    # row means.
    posture_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    posture_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The per-metric readings INCLUDING their raw geometry. Without the raw
    # value a threshold retune is impossible after the fact, which would make
    # every posture number permanently unauditable.
    posture_metrics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Which pitch detector produced the observations, so a bad take is
    # attributable to the analyzer rather than to the player.
    analyzer: Mapped[str | None] = mapped_column(String(24), nullable=True)
    tempo_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    tempo_deviation_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    alignment_confidence: Mapped[float] = mapped_column(Float)
    overall_score: Mapped[float] = mapped_column(Float)
    low_confidence: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

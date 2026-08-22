"""Bookkeeping for a live coaching take.

Deliberately holds no score, no EXP, and no mastery. A streaming take is graded
by the same `submit_attempt` a clip take is, and these rows point at the
`performance_attempts` row that produced. Two progression systems is exactly the
failure this repo has avoided everywhere else.

What it does hold is **divergence telemetry**: what the online matcher believed
while the take was happening, next to the attempt the batch scorer produced from
the same notes. That makes "how good is the live matcher" a query rather than an
opinion.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CoachSession(Base):
    __tablename__ = "coach_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'finalized', 'abandoned')", name="coach_status_valid"),
    )

    # Client-generated, and the primary key: this is what makes finalizing a
    # take idempotent across a dropped socket and an HTTP fallback.
    take_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    practice_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"), index=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("performance_attempts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    protocol_version: Mapped[str] = mapped_column(String(16), default="coach.v1", server_default="coach.v1")
    observed_note_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    utterance_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    suppressed_turn_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    live_matched_note_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    live_missed_note_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    live_extra_note_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(nullable=True)


class CoachUtterance(Base):
    __tablename__ = "coach_utterances"
    __table_args__ = (UniqueConstraint("take_id", "sequence", name="coach_utterance_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    take_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coach_sessions.take_id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    cue: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    provider: Mapped[str] = mapped_column(String(32), default="deterministic", server_default="deterministic")
    voice_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    spoken_text: Mapped[str] = mapped_column(Text)
    # True when the learner started playing again before the coach finished.
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    take_clock_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

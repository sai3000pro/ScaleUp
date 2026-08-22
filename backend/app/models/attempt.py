"""Generated questions and graded attempts.

`attempts` carries `prompt_version` and `llm_call_id` from day one: this table is
the active-learning dataset later, and "which prompt produced this grade?" is
unanswerable retroactively if you did not record it at the time.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "question_type IN ('short_answer','mcq','cloze','code')",
            name="question_type_valid",
        ),
        Index("ix_questions_node_id", "node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill_nodes.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))

    question_type: Mapped[str] = mapped_column(String(16), default="short_answer", server_default="short_answer")
    question_text: Mapped[str] = mapped_column(Text)
    # [{"id": "option-a", "text": "..."}] for MCQ; [] otherwise.
    options: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    correct_option_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Accepted normalized answers for cloze; never returned to the learner.
    accepted_answers: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # Static metadata for code drills. The answer is never executed by the app.
    code_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code_requirements: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # [{"id": "kp1", "point": "...", "weight": 0.4}, ...]
    rubric: Mapped[list] = mapped_column(JSONB)
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    source_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")

    prompt_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("status IN ('issued','graded','abandoned')", name="status_valid"),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('correct','partial','incorrect')",
            name="verdict_valid",
        ),
        CheckConstraint("score IS NULL OR (score BETWEEN 0 AND 1)", name="score_range"),
        UniqueConstraint("user_id", "idempotency_key", name="user_idempotency"),
        Index("ix_attempts_user_node", "user_id", "node_id", "created_at"),
        Index("ix_attempts_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill_nodes.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))

    status: Mapped[str] = mapped_column(String(16), default="issued", server_default="issued")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    points_hit: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    points_missed: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")

    exp_awarded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rescue_bonus_applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Idempotency: a repeated Idempotency-Key returns the same attempt rather
    # than paying for another generation call.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    grade_llm_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="SET NULL"), nullable=True
    )
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    graded_at: Mapped[datetime | None] = mapped_column(nullable=True)

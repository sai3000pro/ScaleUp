"""Persisted, reviewable goal-to-curriculum proposals."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PROPOSAL_STATUSES = ("draft", "approved", "ingesting", "completed")
SOURCE_STATUSES = ("proposed", "approved", "ingesting", "ingested", "failed")


class CurriculumProposal(Base):
    __tablename__ = "curriculum_proposals"
    __table_args__ = (
        CheckConstraint("status IN ('draft','approved','ingesting','completed')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal: Mapped[str] = mapped_column(Text)
    target_outcome: Mapped[str] = mapped_column(Text, default="", server_default="")
    prior_knowledge: Mapped[str] = mapped_column(Text, default="", server_default="")
    application_context: Mapped[str] = mapped_column(Text, default="", server_default="")
    proposal_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("curriculum_proposals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    learner_level: Mapped[str] = mapped_column(String(16), default="beginner", server_default="beginner")
    weekly_minutes: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    format_preference: Mapped[str] = mapped_column(String(16), default="mixed", server_default="mixed")
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CurriculumSource(Base):
    __tablename__ = "curriculum_sources"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','approved','ingesting','ingested','failed')",
            name="status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_proposals.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    snippet: Mapped[str] = mapped_column(Text, default="", server_default="")
    discovery_angle: Mapped[str] = mapped_column(String(24), default="general", server_default="general")
    published_at: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    quality_reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    policy_status: Mapped[str] = mapped_column(String(24), default="review_required", server_default="review_required")
    robots_url: Mapped[str] = mapped_column(Text)
    robots_status: Mapped[str] = mapped_column(String(16), default="not_checked", server_default="not_checked")
    license_status: Mapped[str] = mapped_column(String(24), default="not_identified", server_default="not_identified")
    policy_reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    policy_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    policy_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    selected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), default="proposed", server_default="proposed")
    ingest_job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    ingest_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

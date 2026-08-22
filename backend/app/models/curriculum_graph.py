"""Versioned curriculum graphs and their review evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CURRICULUM_VERSION_STATUSES = ("draft", "review", "published", "retired")
CANDIDATE_STATUSES = ("draft", "accepted", "rejected", "ambiguous")
REVIEW_DECISIONS = ("accepted", "rejected", "ambiguous")


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(48), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CurriculumVersion(Base):
    __tablename__ = "curriculum_versions"
    __table_args__ = (
        UniqueConstraint("course_id", "slug", "version", name="course_curriculum_version"),
        CheckConstraint(
            "status IN ('draft', 'review', 'published', 'retired')",
            name="status_valid",
        ),
        CheckConstraint("version > 0", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    compiler_version: Mapped[str] = mapped_column(
        String(32), default="curriculum-compiler-v1", server_default="curriculum-compiler-v1"
    )
    source_bundle_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("curriculum_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SkillDefinition(Base):
    __tablename__ = "skill_definitions"
    __table_args__ = (
        UniqueConstraint("instrument_id", "slug", name="instrument_skill_slug"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    assessable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class CurriculumNode(Base):
    __tablename__ = "curriculum_nodes"
    __table_args__ = (
        UniqueConstraint("curriculum_version_id", "skill_definition_id", name="curriculum_node_skill"),
        Index("ix_curriculum_nodes_version_id", "curriculum_version_id"),
    )

    curriculum_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"), primary_key=True
    )
    skill_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_definitions.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    section: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")
    assessment_capability: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class PrerequisiteCandidate(Base):
    __tablename__ = "prerequisite_candidates"
    __table_args__ = (
        UniqueConstraint("curriculum_version_id", "prereq_skill_id", "target_skill_id", name="curriculum_candidate_edge"),
        CheckConstraint(
            "status IN ('draft', 'accepted', 'rejected', 'ambiguous')",
            name="status_valid",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        Index("ix_prerequisite_candidates_version_status", "curriculum_version_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    curriculum_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"), index=True
    )
    prereq_skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill_definitions.id", ondelete="RESTRICT"))
    target_skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill_definitions.id", ondelete="RESTRICT"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    support: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    relation_type: Mapped[str] = mapped_column(String(32), default="prerequisite", server_default="prerequisite")
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cycle_path: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CurriculumEvidence(Base):
    __tablename__ = "curriculum_evidence"
    __table_args__ = (Index("ix_curriculum_evidence_candidate_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prerequisite_candidates.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    quote: Mapped[str] = mapped_column(Text)
    extractor_version: Mapped[str] = mapped_column(String(32))
    prompt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CurriculumReview(Base):
    __tablename__ = "curriculum_reviews"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prerequisite_candidates.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (
        CheckConstraint("decision IN ('accepted', 'rejected', 'ambiguous')", name="decision_valid"),
    )

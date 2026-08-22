"""Wire shapes for the bounded goal-to-curriculum planner."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CurriculumProposalCreate(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    target_outcome: str = Field(default="", max_length=300)
    prior_knowledge: str = Field(default="", max_length=300)
    application_context: str = Field(default="", max_length=300)
    learner_level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    weekly_minutes: int = Field(default=120, ge=15, le=600)
    format_preference: Literal["mixed", "textbook", "course", "papers"] = "mixed"
    max_sources: int = Field(default=8, ge=1, le=12)


class CurriculumSourceOut(BaseModel):
    id: uuid.UUID
    rank: int
    title: str
    url: str
    domain: str
    snippet: str
    discovery_angle: str
    published_at: str | None
    quality_score: float
    quality_reasons: list[str]
    policy_status: str
    robots_url: str
    robots_status: str
    license_status: str
    policy_reasons: list[str]
    policy_checked_at: datetime | None
    policy_acknowledged: bool
    selected: bool
    status: str
    ingest_job_id: uuid.UUID | None
    ingest_error: str | None


class CurriculumProposalOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    goal: str
    target_outcome: str
    prior_knowledge: str
    application_context: str
    proposal_version: int
    supersedes_id: uuid.UUID | None
    learner_level: str
    weekly_minutes: int
    format_preference: str
    provider: str
    status: str
    created_at: datetime
    sources: list[CurriculumSourceOut]


class CurriculumApproval(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=12)
    acknowledge_policy: bool = False


class CurriculumIngestItem(BaseModel):
    source_id: uuid.UUID
    job_id: uuid.UUID | None
    status: str
    error: str | None


class CurriculumIngestAccepted(BaseModel):
    proposal_id: uuid.UUID
    course_id: uuid.UUID
    accepted: list[CurriculumIngestItem]


class CurriculumConceptIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=2000)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    assessable: bool = True
    key_terms: list[str] = Field(default_factory=list, max_length=16)
    source_chunk_ids: list[uuid.UUID] = Field(default_factory=list, max_length=32)
    section: str | None = Field(default=None, max_length=120)


class CurriculumEvidenceIn(BaseModel):
    chunk_id: uuid.UUID
    quote: str = Field(min_length=1, max_length=1000)
    extractor_version: str = Field(default="curriculum-compiler-v1", max_length=32)
    prompt_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    source_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class CurriculumEdgeIn(BaseModel):
    prereq: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=64)
    target: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=64)
    confidence: float = Field(default=1.0, ge=0, le=1)
    support: int = Field(default=1, ge=1)
    rationale: str = Field(default="", max_length=2000)
    evidence: list[CurriculumEvidenceIn] = Field(default_factory=list, max_length=8)


class CurriculumVersionCreate(BaseModel):
    instrument: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=48)
    instrument_title: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    compiler_version: str = Field(default="curriculum-compiler-v1", max_length=32)
    source_bundle_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    concepts: list[CurriculumConceptIn] = Field(min_length=1, max_length=500)
    edges: list[CurriculumEdgeIn] = Field(default_factory=list, max_length=2000)


class CurriculumVersionOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    instrument: str
    slug: str
    title: str
    version: int
    status: str
    compiler_version: str
    node_count: int
    candidate_count: int
    rejected_count: int
    created_at: datetime
    published_at: datetime | None


class CurriculumCandidateReviewIn(BaseModel):
    decision: Literal["accepted", "rejected", "ambiguous"]
    reason: str = Field(default="", max_length=2000)


class CurriculumCandidateOut(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    prereq: str
    target: str
    confidence: float
    support: int
    status: str
    rationale: str | None
    rejection_reason: str | None
    cycle_path: list[str]
    evidence_count: int


class CurriculumPublishOut(BaseModel):
    version_id: uuid.UUID
    course_id: uuid.UUID
    graph_version: int
    node_count: int
    edge_count: int

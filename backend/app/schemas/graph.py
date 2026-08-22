from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class NodeRef(BaseModel):
    id: uuid.UUID
    title: str


class SourceEvidence(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    section_path: str | None
    page_start: int
    # A bounded, whitespace-normalised excerpt from the authoritative chunk.
    excerpt: str


class NodeProgressOut(BaseModel):
    state: str
    exp: int
    level: int
    mastery: float  # EMA of graded scores; does not decay
    proficiency: float  # mastery after time decay -- what the ring shows
    due_at: datetime | None
    overdue_days: float


class GraphNodeOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    summary: str
    difficulty: int
    depth: int
    assessable: bool
    # The outline heading this skill came from. Provenance and a grouping key,
    # never structure -- the chapter is not a prerequisite. Null for a document
    # whose outline was too thin to use.
    section: str | None = None
    progress: NodeProgressOut
    blocked_by: list[NodeRef] = []
    sources: list[SourceEvidence] = []


class GraphEdgeOut(BaseModel):
    id: str
    # `source` is the PREREQUISITE, `target` depends on it -- named to match
    # React Flow exactly so the frontend needs no translation layer.
    source: uuid.UUID
    target: uuid.UUID
    confidence: float
    support: int
    rationale: str | None
    sources: list[SourceEvidence] = []


class GraphStats(BaseModel):
    total: int
    locked: int
    available: int
    learning: int
    decaying: int
    mastered: int


class GraphSnapshot(BaseModel):
    course_id: uuid.UUID
    graph_version: int
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    stats: GraphStats

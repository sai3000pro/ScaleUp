"""Wire shapes for the admin surface: reindex, projection health, rejections."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReindexScope(StrEnum):
    """Which derived stores a reindex rebuilds.

    Kept as a parameter rather than hardcoded to `all` because the two halves
    have wildly different costs: rebuilding the Neo4j projection is one bulk
    write over a few hundred rows and is free, while re-embedding a 400-page book
    against a real key is thousands of chunks of billable input. Someone whose
    Neo4j container was wiped should not have to pay for the vectors again.
    """

    ALL = "all"
    GRAPH = "graph"  # Neo4j only
    VECTORS = "vectors"  # Chroma only


class ReindexAccepted(BaseModel):
    """202 body. Mirrors `IngestAccepted` so the polling UI needs no new branch."""

    job_id: uuid.UUID
    course_id: uuid.UUID
    scope: ReindexScope
    # True when an identical reindex was already running and this request joined
    # it rather than starting a second. Endpoints are idempotent (see CLAUDE.md).
    deduplicated: bool = False


class ProjectionStatus(BaseModel):
    """The monitorable scalar `CLAUDE.md` names as the design's consistency story.

    Never raises on an unreachable store: a status endpoint that 500s when Neo4j
    is down is useless exactly when it is needed. Unreachability is reported as
    `reachable: false` with `stale: true`, because a projection that cannot be
    read cannot be trusted to be current.
    """

    course_id: uuid.UUID
    graph_version: int
    node_count: int
    edge_count: int
    chunk_count: int

    neo4j_reachable: bool
    projected_version: int | None
    stale: bool

    chroma_reachable: bool
    vector_count: int | None

    # Set when a store could not be reached, so the caller can show the cause
    # rather than an unexplained `false`.
    detail: str | None = None


class RejectionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prereq_slug: str
    target_slug: str
    reason: str
    confidence: float | None
    # The chain the edge would have closed. For `reason == "cycle"` this is the
    # debugging artifact; for every other reason it is empty.
    cycle_path: list[str]
    created_at: datetime


class RejectionsPage(BaseModel):
    """Paginated, because pagination is not optional here.

    `skill_edge_rejections` is written on every persist and a bad prompt version
    produces thousands of rows in one ingest -- which is precisely when someone
    opens this endpoint.
    """

    course_id: uuid.UUID
    total: int
    # `{"cycle": 41, "low_confidence": 1180, ...}`. The grouping is over the
    # WHOLE course, not the current page: "what is this prompt getting wrong?"
    # is a question about the run, and a per-page tally would answer a different
    # one every time you clicked next.
    by_reason: dict[str, int]
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    rows: list[RejectionRow]

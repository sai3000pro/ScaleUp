"""Explore: search, ask, and the guided path.

The three reads that turn a graph you can look at into a graph you can use. All
three are projections of data the pipeline already produces -- Chroma's chunk
vectors and `domain.dag.topological_depths` -- so nothing here has a write path.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.schemas.drill import SourceRef


class SearchHit(BaseModel):
    node_id: uuid.UUID
    slug: str
    title: str
    summary: str
    assessable: bool
    depth: int
    # 0..1, comparable across the two matchers -- see `search_service`.
    score: float
    # Which matcher found it: `title`, `content`, or `both`.
    match: str
    # The passage that matched, for a content hit; the node's own summary for a
    # title-only one. Never null, so the UI needs no branch.
    snippet: str
    source: SourceRef | None = None


class SearchResults(BaseModel):
    query: str
    results: list[SearchHit]
    # False when the vector index could not be reached and the answer is
    # title-only. Reported rather than hidden: "no semantic hits" and "semantic
    # search is down" look identical to a user otherwise.
    semantic: bool


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class Citation(BaseModel):
    node_id: uuid.UUID
    node_title: str
    slug: str
    chunk_id: uuid.UUID
    # Verified to be a substring of the cited chunk before it reaches here.
    quote: str
    source: SourceRef


class AskAnswer(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    # How many passages the model was shown. Zero means retrieval found nothing,
    # which is a different failure from "the model had nothing to say".
    retrieved: int


class PathStep(BaseModel):
    order: int
    node_id: uuid.UUID
    slug: str
    title: str
    summary: str
    depth: int
    difficulty: int
    state: str
    mastery: float
    # Mastery has cleared the prerequisite threshold, so the walk has moved past
    # this step.
    done: bool


class CoursePath(BaseModel):
    course_id: uuid.UUID
    steps: list[PathStep]
    # The first step not yet done -- "start here", or "next" once some are.
    next_node_id: uuid.UUID | None
    completed: int
    total: int

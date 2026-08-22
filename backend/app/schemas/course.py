from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.shelves import LEARNER


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    source_type: str
    source_uri: str | None
    page_count: int | None
    chunk_count: int
    created_at: datetime


class DocumentUrlIn(BaseModel):
    """A web page to ingest.

    A plain string rather than pydantic's `HttpUrl`, deliberately. Validation
    lives in `app.ingestion.fetch.assert_public_url`, which has to run anyway --
    it re-runs on every redirect hop, where no pydantic type is involved -- and
    splitting the rules across two places is how one of them ends up laxer than
    the other. The cap is on length only, which is the one thing worth refusing
    before the SSRF check has a chance to look at it.
    """

    url: str = Field(min_length=1, max_length=2048)


class CourseFromGoalIn(BaseModel):
    """A learner's own sentence. The instrument is read out of it, not chosen."""

    goal: str = Field(min_length=3, max_length=300)


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: str
    #: Where this course came from: "learner" for one they created, "prebuilt" for
    #: one the project offers ready-made, "internal" for one seeded only so the
    #: system is developable offline. Declared in `app.core.shelves`, never read off
    #: the title or the compiler that built the curriculum.
    shelf: str = LEARNER
    graph_version: int
    node_count: int
    edge_count: int
    mastered_count: int
    created_at: datetime


class CourseDetail(CourseOut):
    documents: list[DocumentSummary] = []
    #: How this course's published curriculum was built. `None` before one is
    #: published. Shown to the learner: a tree the project authored and a tree
    #: the system proposed are both playable, and the label is what keeps that
    #: honest.
    curriculum_provenance: str | None = None


class CourseList(BaseModel):
    courses: list[CourseOut]


class IngestAccepted(BaseModel):
    document: DocumentSummary
    job_id: uuid.UUID
    # True when these exact bytes were already ingested into this course. The
    # original document and its job are returned unchanged rather than starting
    # a second run.
    deduplicated: bool

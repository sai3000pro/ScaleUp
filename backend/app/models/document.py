"""Documents, their parsed pages, their chunks, and the ingest job that made them."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

INGEST_STATES = (
    "queued",
    "parsing",
    "chunking",
    "embedding",
    "extracting",
    "reducing",
    "finalizing",
    "succeeded",
    "failed",
    "cancelled",
)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Re-uploading the same bytes to the same course is a no-op, not a
        # second ingest. This is the outermost layer of idempotency.
        UniqueConstraint("course_id", "content_sha256", name="course_content"),
        CheckConstraint("source_type IN ('pdf', 'epub', 'html', 'text')", name="source_type_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(8), default="pdf")
    filename: Mapped[str] = mapped_column(String(400))
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DocumentPage(Base):
    """Raw parsed text, kept so re-chunking never re-parses a 1000-page PDF."""

    __tablename__ = "document_pages"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="document_ordinal"),
        Index("ix_chunks_course_id", "course_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # Denormalised so retrieval can filter to a course without a join.
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    # e.g. "3 / 3.2 / 3.2.1" -- fed into the extraction prompt, and most of what
    # stops the model inventing a concept called "Introduction" forty times.
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    # Chroma is the vector index; this is the id we stored there.
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


INGEST_JOB_KINDS = ("ingest", "reindex")


class IngestJob(Base):
    """A unit of background work against one course.

    Two kinds share this table, and the discriminator is load-bearing:

    * `ingest`  -- parse/chunk/embed/extract ONE document into the course graph.
    * `reindex` -- rebuild the derived stores (Chroma, then Neo4j) for the WHOLE
      course from Postgres. It has no document, because it reads every document's
      committed chunks and writes no Postgres at all.

    `document_id` was NOT NULL, which is the honest invariant for an ingest and
    an impossible one for a reindex. Rather than dropping it -- which would let a
    document-less ingest row exist -- it is made *conditional* on `kind` by the
    CHECK below. The invariant is preserved; it is just now stated per kind.
    """

    __tablename__ = "ingest_jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued','parsing','chunking','embedding','extracting',"
            "'reducing','finalizing','succeeded','failed','cancelled')",
            name="state_valid",
        ),
        CheckConstraint("kind IN ('ingest','reindex')", name="kind_valid"),
        CheckConstraint(
            "(kind = 'ingest' AND document_id IS NOT NULL) OR "
            "(kind = 'reindex' AND document_id IS NULL)",
            name="kind_document",
        ),
        Index("ix_ingest_jobs_course_state", "course_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), default="ingest", server_default="ingest")
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )

    # sha256(user || course || content || pipeline_version). Unique, so an
    # identical re-upload returns the original job instead of starting a second.
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)

    state: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    units_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    units_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stage_detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_root_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(16), default="1")

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    # `created_at` is when the API accepted the job; this is when a worker
    # actually began processing it. Keeping both makes queue latency visible.
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

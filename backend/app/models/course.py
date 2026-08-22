from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

COURSE_STATUSES = ("draft", "ingesting", "ready", "failed")


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'ingesting', 'ready', 'failed')",
            name="status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")

    # Bumped on every graph write. The Neo4j projection stamps the version it
    # built from, so a read path can detect a stale projection and fall back to
    # Postgres rather than serving wrong structure.
    graph_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Set when this course is a deep copy of another ("copy to my account").
    # NULL for courses created normally. Doubles as the copy idempotency key:
    # the partial unique index on (owner_id, copied_from_id) means one learner
    # can copy a given course at most once -- a second copy returns the first.
    # SET NULL on source deletion, because the source's own lifecycle must not
    # take the copy's provenance down with it.
    copied_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

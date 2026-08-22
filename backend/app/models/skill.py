"""The skill graph.

Edge direction convention, obeyed everywhere in this repo:
`prereq_id -> target_id` means "learn prereq before target". The API renames
these to `source`/`target` to match React Flow, and nothing invents a third
naming.
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

REJECTION_REASONS = ("self_loop", "duplicate", "unknown_node", "low_confidence", "cycle")


class SkillNode(Base):
    __tablename__ = "skill_nodes"
    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="course_slug"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)

    # The merge key. Two extraction windows describing the same concept must
    # produce the same slug, which is why the JSON schema pins it to a regex.
    slug: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    key_terms: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)

    # Topological layer from Kahn's algorithm; becomes the dagre rank so the
    # rendered tree layers by genuine prerequisite depth.
    depth: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    # False for structural concepts too thin to write a question about. They
    # still carry the tree's shape but never appear in drills or quests.
    assessable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # The outline heading this skill was found under -- "Duality", "Integer
    # Programs". Provenance and a grouping key for the canvas, NOT structure:
    # the chapter a concept was printed in is not one of its prerequisites, and
    # emitting it as an edge made half the graph a table of contents. Nullable
    # because a document with no usable outline still produces nodes.
    section: Mapped[str | None] = mapped_column(String(120), nullable=True)

    source_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")
    mention_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Nullable for legacy textbook graphs; populated when a published curriculum
    # version is projected into the learner graph.
    curriculum_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("curriculum_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    skill_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_definitions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SkillEdge(Base):
    __tablename__ = "skill_edges"
    __table_args__ = (
        # The database refuses self-loops; app/domain/dag.py refuses cycles.
        CheckConstraint("prereq_id <> target_id", name="no_self_loop"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        Index("ix_skill_edges_target_id", "target_id"),
        Index("ix_skill_edges_course_id", "course_id"),
    )

    prereq_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    support: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # True when this edge survives transitive reduction. The full set is stored;
    # only the reduced set is rendered, because ~40% of extracted edges are
    # transitively implied and drawing them makes an unreadable hairball.
    is_reduced: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The target skill's source passages are the evidence for why this
    # prerequisite relation was accepted. Stored separately from node
    # provenance so an edge can be inspected without reconstructing the graph.
    source_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SkillEdgeRejection(Base):
    """Edges the extractor proposed and the DAG builder refused.

    This table is the primary debugging material for prompt iteration:
    `SELECT reason, count(*) FROM skill_edge_rejections GROUP BY 1` after a real
    ingest tells you exactly what the model is getting wrong.
    """

    __tablename__ = "skill_edge_rejections"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('self_loop','duplicate','unknown_node','low_confidence','cycle')",
            name="reason_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    prereq_slug: Mapped[str] = mapped_column(String(64))
    target_slug: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The chain the edge would have closed. Far more useful than "cycle".
    cycle_path: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

"""Per-user, per-node review state.

Stores only facts about the last review. `proficiency` and the node's visual
state are computed on read -- storing them would guarantee drift the moment a
threshold changed, and would need a cron job to stay fresh as the clock moves.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeProgress(Base):
    __tablename__ = "node_progress"
    __table_args__ = (
        CheckConstraint("mastery BETWEEN 0 AND 1", name="mastery_range"),
        CheckConstraint("ease >= 1.3", name="ease_floor"),
        Index("ix_node_progress_user_due", "user_id", "due_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_nodes.id", ondelete="CASCADE"), primary_key=True
    )

    exp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    level: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    # EMA of graded scores. Does NOT decay -- decay is applied on read.
    mastery: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")

    ease: Mapped[float] = mapped_column(Float, default=2.5, server_default="2.5")
    interval_days: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    reps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lapses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    last_reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

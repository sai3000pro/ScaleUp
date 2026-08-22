from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CharacterProfile(Base):
    """Identity choices for the learner's RPG character.

    Learning facts remain in User, Attempt, and NodeProgress. This table stores
    only choices that cannot be derived: the character name, appearance, class,
    and perks the learner has spent account levels on.
    """

    __tablename__ = "character_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    character_name: Mapped[str] = mapped_column(String(80))
    avatar_key: Mapped[str] = mapped_column(String(32), default="owl", server_default="owl")
    archetype: Mapped[str] = mapped_column(String(32), default="scholar", server_default="scholar")
    skin_tone: Mapped[str] = mapped_column(String(32), default="sand", server_default="sand")
    hair_style: Mapped[str] = mapped_column(String(32), default="sweep", server_default="sweep")
    hair_color: Mapped[str] = mapped_column(String(32), default="chestnut", server_default="chestnut")
    outfit_color: Mapped[str] = mapped_column(String(32), default="azure", server_default="azure")
    accessory: Mapped[str] = mapped_column(String(32), default="none", server_default="none")
    unlocked_perks: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

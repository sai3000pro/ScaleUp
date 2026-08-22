from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.character import ACCESSORIES, ARCHETYPES, AVATARS, HAIR_COLORS, HAIR_STYLES, OUTFIT_COLORS, SKIN_TONES

AvatarKey = Literal["owl", "fox", "robot", "wizard", "cat", "dragon"]
Archetype = Literal["scholar", "builder", "explorer", "mentor"]
SkinTone = Literal["moon", "sand", "honey", "copper", "ebony"]
HairStyle = Literal["sweep", "curls", "bob", "mohawk", "crown"]
HairColor = Literal["ink", "chestnut", "silver", "violet", "rose"]
OutfitColor = Literal["azure", "violet", "coral", "mint", "gold"]
Accessory = Literal["none", "glasses", "headband", "crown", "earring"]


class CharacterCreate(BaseModel):
    character_name: str = Field(min_length=1, max_length=80)
    avatar_key: AvatarKey = "owl"
    archetype: Archetype = "scholar"
    skin_tone: SkinTone = "sand"
    hair_style: HairStyle = "sweep"
    hair_color: HairColor = "chestnut"
    outfit_color: OutfitColor = "azure"
    accessory: Accessory = "none"


class CharacterUpdate(BaseModel):
    character_name: str | None = Field(default=None, min_length=1, max_length=80)
    avatar_key: AvatarKey | None = None
    archetype: Archetype | None = None
    skin_tone: SkinTone | None = None
    hair_style: HairStyle | None = None
    hair_color: HairColor | None = None
    outfit_color: OutfitColor | None = None
    accessory: Accessory | None = None


class CharacterProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    character_name: str
    avatar_key: str
    archetype: str
    skin_tone: str
    hair_style: str
    hair_color: str
    outfit_color: str
    accessory: str
    unlocked_perks: list[str]
    created_at: datetime


class CharacterStatsOut(BaseModel):
    focus: int = Field(ge=0, le=99)
    memory: int = Field(ge=0, le=99)
    resilience: int = Field(ge=0, le=99)
    curiosity: int = Field(ge=0, le=99)


class CharacterPerkOut(BaseModel):
    id: str
    title: str
    description: str
    cost: int
    unlocked: bool


class AchievementOut(BaseModel):
    id: str
    title: str
    description: str
    progress: int = Field(ge=0)
    target: int = Field(gt=0)
    unlocked: bool


class CharacterSheet(BaseModel):
    profile: CharacterProfileOut | None
    level: int
    total_exp: int
    exp_into_level: int
    exp_for_next_level: int
    streak_days: int
    stats: CharacterStatsOut
    perks: list[CharacterPerkOut]
    achievements: list[AchievementOut]
    available_perk_points: int = Field(ge=0)


# Keep these imports visible to static contract readers and make the accepted
# vocabulary explicit at the schema boundary.
assert ARCHETYPES and AVATARS and SKIN_TONES and HAIR_STYLES and HAIR_COLORS and OUTFIT_COLORS and ACCESSORIES

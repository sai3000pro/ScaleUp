"""Wire shapes for the RPG campaign briefing."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class CampaignSkillRef(BaseModel):
    id: uuid.UUID
    title: str


class CampaignTreeShape(BaseModel):
    playable_skills: int = Field(ge=0)
    branches: int = Field(ge=0)
    prerequisite_links: int = Field(ge=0)
    depth: int = Field(ge=0)
    depth_counts: dict[str, int]
    starting_skills: list[CampaignSkillRef]


class CampaignOutcomeCoverage(BaseModel):
    outcome: str
    terms: list[str]
    matched_terms: list[str]
    missing_terms: list[str]
    coverage: float = Field(ge=0, le=1)
    signal: str


class CampaignBriefingOut(BaseModel):
    course_id: uuid.UUID
    goal: str | None
    target_outcome: str
    proposal_version: int | None
    tree_shape: CampaignTreeShape
    outcome_coverage: CampaignOutcomeCoverage


class CampaignSideQuest(BaseModel):
    capability: str
    title: str
    reason: str
    source_query: str
    action: str


class CampaignOutcomeEvaluationOut(BaseModel):
    course_id: uuid.UUID
    outcome: str
    provider: str
    mode: str
    evaluated_skill_count: int = Field(ge=0)
    readiness: float = Field(ge=0, le=1)
    matched_skills: list[CampaignSkillRef]
    missing_capabilities: list[str]
    side_quests: list[CampaignSideQuest]
    rationale: str

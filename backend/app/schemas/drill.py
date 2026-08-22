from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.graph import NodeProgressOut


class SourceRef(BaseModel):
    document_id: uuid.UUID
    section_path: str | None
    page_start: int


QuestionType = Literal["short_answer", "mcq", "cloze", "code"]


class QuestionOption(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=300)


class DrillOut(BaseModel):
    attempt_id: uuid.UUID
    node_id: uuid.UUID
    node_title: str
    question: str
    question_type: QuestionType
    options: list[QuestionOption] = []
    code_language: str | None = None
    difficulty: int
    sources: list[SourceRef] = []


class GradeRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)


class GradeResult(BaseModel):
    attempt_id: uuid.UUID
    node_id: uuid.UUID
    score: float
    verdict: str
    feedback: str
    points_hit: list[str] = []
    points_missed: list[str] = []
    exp_awarded: int
    rescue_bonus_applied: bool
    level_before: int
    level_after: int
    level_up: bool
    account_level_before: int
    account_level_after: int
    account_level_up: bool
    user_total_exp: int
    progress: NodeProgressOut
    # Newly reachable because this node crossed the prerequisite threshold.
    # Drives the unlock cascade animation, which is the payoff of the tech-tree
    # metaphor.
    unlocked_node_ids: list[uuid.UUID] = []

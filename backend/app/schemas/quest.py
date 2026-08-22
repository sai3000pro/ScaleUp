from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class Quest(BaseModel):
    node_id: uuid.UUID
    node_title: str
    course_id: uuid.UUID
    course_title: str
    # `overdue` is a decayed skill being rescued; `frontier` is a top-up so a new
    # user never opens an empty board.
    reason: str
    overdue_days: float
    proficiency: float
    due_at: datetime | None
    reward_exp: int


class QuestBoard(BaseModel):
    date: date
    streak_days: int
    total_reward_exp: int
    quests: list[Quest]

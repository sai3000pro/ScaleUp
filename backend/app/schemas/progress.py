from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class ProgressTrendPoint(BaseModel):
    date: date
    attempts: int
    average_score: float = Field(ge=0, le=1)
    mastery: float = Field(ge=0, le=1)
    exp_earned: int = Field(ge=0)


class ProgressSourceCoverage(BaseModel):
    document_id: uuid.UUID
    filename: str
    skills_total: int = Field(ge=0)
    skills_started: int = Field(ge=0)
    attempts: int = Field(ge=0)


class ProgressAnalytics(BaseModel):
    course_id: uuid.UUID
    total_skills: int = Field(ge=0)
    started_skills: int = Field(ge=0)
    mastered_skills: int = Field(ge=0)
    total_attempts: int = Field(ge=0)
    average_score: float | None = Field(default=None, ge=0, le=1)
    exp_earned: int = Field(ge=0)
    review_days: int = Field(ge=0)
    tracked_days: int = Field(ge=0)
    consistency: float = Field(ge=0, le=1)
    mastery_trend: list[ProgressTrendPoint]
    source_coverage: list[ProgressSourceCoverage]


class DailyMetricsOut(BaseModel):
    day: date
    attempts: int
    means: dict[str, float]


class MetricComparisonOut(BaseModel):
    key: str
    current: float
    previous: float | None
    change: float
    # Which way the number moved.
    trend: str
    improvement_percentage: float | None
    # Whether that movement is good news. Null when the metric has no declared
    # polarity -- "we do not know" is a real answer.
    improved: bool | None


class PracticeReport(BaseModel):
    """How a learner's practice has moved. Computed on read, never stored."""

    course_id: uuid.UUID
    exercise_id: uuid.UUID | None
    window_days: int
    attempt_count: int
    practice_days: int
    summary: str
    insights: list[str]
    daily: list[DailyMetricsOut]
    comparisons: list[MetricComparisonOut]

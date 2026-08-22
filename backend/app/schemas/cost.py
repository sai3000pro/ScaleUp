from __future__ import annotations

from pydantic import BaseModel


class RoleCost(BaseModel):
    role: str
    model: str
    # Which prompt version produced this spend. Grouping on it is what makes
    # "did quality change after I edited the rubric?" answerable at all.
    prompt_version: str
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: int | None


class CourseCost(BaseModel):
    course_id: str
    total_calls: int
    failed_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    budget_usd: float
    budget_remaining_usd: float
    budget_exceeded: bool
    by_role: list[RoleCost]

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


# @spec LLM-LEDGER-006
class PromptVersionOutcome(BaseModel):
    """Outcome counts for one prompt version of one role.

    Grouped by (role, prompt_id, prompt_version) so the same role before and
    after a prompt edit lands in different rows -- the comparison the ledger
    stores prompt identity for.
    """

    role: str
    prompt_id: str
    prompt_version: str
    calls: int
    ok: int
    # Anything that is neither ok nor cancelled: a barge-in is a real outcome,
    # not a failure.
    failed: int
    cancelled: int
    avg_latency_ms: int | None
    cost_usd: float


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
    by_prompt_version: list[PromptVersionOutcome]

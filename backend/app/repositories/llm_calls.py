"""Reads and writes for the `llm_calls` ledger.

The ledger is written on its OWN short-lived session, committed immediately and
independently of whatever transaction the caller is in. That is deliberate: a
call that cost real money happened whether or not the surrounding unit of work
later rolls back, and an ingest that fails halfway is exactly when you most want
to know what it spent before it died.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import sync_session
from app.llm.base import BudgetExceededError
from app.models import LlmCall

logger = logging.getLogger(__name__)

__all__ = ["STATUSES", "record", "cost_summary", "assert_budget"]

# Mirrors the CHECK constraint on the table.
# `cancelled` is a streamed call the consumer stopped reading -- a barge-in,
# or a take that ended mid-utterance. It burned tokens and is a distinct
# outcome; recording it as `ok` would make "how often does the learner talk
# over the coach?" unanswerable.
STATUSES = frozenset({"ok", "schema_error", "provider_error", "timeout", "refusal", "cancelled"})


# @spec LLM-BUDGET-001, LLM-BUDGET-002, LLM-BUDGET-003
def assert_budget(*, course_id: uuid.UUID, estimated_cost_usd: Decimal, budget_usd: Decimal) -> None:
    """Reject a billable call whose conservative estimate exceeds the course cap.

    This runs in the same short-lived sync-session style as ledger writes, so it
    works from both Celery and FastAPI threadpools. Zero-cost fake calls skip the
    database entirely, preserving the no-Postgres offline development loop.
    """
    if estimated_cost_usd <= 0:
        return

    with sync_session() as session:
        spent = session.scalar(
            select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(LlmCall.course_id == course_id)
        )
        spent_usd = Decimal(str(spent or 0))
        if spent_usd + estimated_cost_usd > budget_usd:
            raise BudgetExceededError(
                budget_usd=budget_usd,
                spent_usd=spent_usd,
                estimated_usd=estimated_cost_usd,
            )


# @spec LLM-PROMPT-003, LLM-LEDGER-004, LLM-LEDGER-006
def record(
    *,
    role: str,
    provider: str,
    model: str,
    prompt_id: str,
    prompt_version: str,
    prompt_sha256: str,
    request_fingerprint: str,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: Decimal = Decimal(0),
    latency_ms: int | None = None,
    error: str | None = None,
    course_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Append one row. Never raises. Returns the row id, or None if it was lost.

    A bookkeeping failure must not turn a successful extraction into a failed
    one -- the ledger is there to observe the pipeline, not to gate it. That is
    also why the id is optional to the caller: `attempts.grade_llm_call_id` is a
    nullable FK precisely so a swallowed ledger write cannot take a graded
    attempt down with it.

    The id is generated here rather than read back after the flush so it is
    known before the commit, and because this session commits independently (see
    the module docstring) the row is durable by the time the caller assigns it --
    which is what satisfies the foreign key from a *different* transaction.
    """
    call_id = uuid.uuid4()
    try:
        with sync_session() as session:
            session.add(
                LlmCall(
                    id=call_id,
                    role=role,
                    provider=provider,
                    model=model,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    prompt_sha256=prompt_sha256,
                    request_fingerprint=request_fingerprint,
                    status=status if status in STATUSES else "provider_error",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    # Errors can be enormous (a whole model response). Store
                    # enough to identify the failure, not the whole payload.
                    error=None if error is None else error[:2000],
                    course_id=course_id,
                )
            )
    except Exception:  # noqa: BLE001 - deliberately swallowed, see docstring
        logger.warning("could not write llm_calls row for role=%s status=%s", role, status, exc_info=True)
        return None
    return call_id


# @spec LLM-BUDGET-004
async def cost_summary(session: AsyncSession, course_id: uuid.UUID, budget_usd: Decimal) -> dict:
    """What did this course cost, broken down by role?

    Grouped by (role, model, prompt_version) because "extraction got better
    after I edited the prompt" is only answerable if spend is attributable to
    the exact prompt version that produced it.
    """
    rows = (await session.execute(
        select(
            LlmCall.role,
            LlmCall.model,
            LlmCall.prompt_version,
            func.count().label("calls"),
            func.sum(case((LlmCall.status == "ok", 1), else_=0)).label("ok"),
            func.coalesce(func.sum(LlmCall.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCall.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LlmCall.cost_usd), 0).label("cost_usd"),
            func.avg(LlmCall.latency_ms).label("avg_latency_ms"),
        )
        .where(LlmCall.course_id == course_id)
        .group_by(LlmCall.role, LlmCall.model, LlmCall.prompt_version)
        .order_by(func.sum(LlmCall.cost_usd).desc())
    )).all()

    by_role = [
        {
            "role": row.role,
            "model": row.model,
            "prompt_version": row.prompt_version,
            "calls": int(row.calls),
            "failed": int(row.calls) - int(row.ok or 0),
            "input_tokens": int(row.input_tokens),
            "output_tokens": int(row.output_tokens),
            "cost_usd": float(row.cost_usd or 0),
            "avg_latency_ms": int(row.avg_latency_ms) if row.avg_latency_ms is not None else None,
        }
        for row in rows
    ]

    total_cost_usd = round(sum(item["cost_usd"] for item in by_role), 6)
    budget_float = float(budget_usd)
    return {
        "course_id": str(course_id),
        "total_calls": sum(item["calls"] for item in by_role),
        "failed_calls": sum(item["failed"] for item in by_role),
        "total_input_tokens": sum(item["input_tokens"] for item in by_role),
        "total_output_tokens": sum(item["output_tokens"] for item in by_role),
        "total_cost_usd": total_cost_usd,
        "budget_usd": budget_float,
        "budget_remaining_usd": round(max(budget_float - total_cost_usd, 0), 6),
        "budget_exceeded": total_cost_usd >= budget_float,
        "by_role": by_role,
    }

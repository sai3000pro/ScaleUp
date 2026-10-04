"""Validation helpers and timing instrumentation for bounded scoring requests."""

from __future__ import annotations

from time import perf_counter
from typing import Callable, TypeVar

from app.evaluation.scoring_limits import DEMO_SCORING_BUDGET_MS, MAX_OBSERVED_NOTES, MAX_SCORING_PAYLOAD_BYTES


def validate_scoring_payload_size(payload_bytes: int) -> None:
    """Refuse an oversized raw HTTP body before request-model parsing."""
    if payload_bytes > MAX_SCORING_PAYLOAD_BYTES:
        raise ValueError(f"Scoring payload exceeds the {MAX_SCORING_PAYLOAD_BYTES // 1024} KiB demo limit.")


def validate_scoring_budget(payload_bytes: int, observed_note_count: int) -> None:
    """Refuse payloads outside the bounded synchronous demo envelope."""
    validate_scoring_payload_size(payload_bytes)
    if observed_note_count > MAX_OBSERVED_NOTES:
        raise ValueError(f"At most {MAX_OBSERVED_NOTES} observed notes are allowed per scoring request.")


def scoring_latency_exceeded(elapsed_ms: float) -> bool:
    """Whether measured evaluator time exceeds the informational demo target."""
    return elapsed_ms > DEMO_SCORING_BUDGET_MS


def scoring_request_budget(payload_bytes: int, observed_note_count: int) -> dict[str, int | float]:
    """The numeric budgets surfaced in the service contract and tests."""
    return {
        "max_payload_bytes": MAX_SCORING_PAYLOAD_BYTES,
        "max_observed_notes": MAX_OBSERVED_NOTES,
        "max_scoring_ms": DEMO_SCORING_BUDGET_MS,
        "payload_bytes": payload_bytes,
        "observed_notes": observed_note_count,
    }


T = TypeVar("T")


def measure_scoring_ms(operation: Callable[[], T]) -> tuple[T, float]:
    """Run a pure scoring operation and return its result and elapsed ms."""
    started = perf_counter()
    result = operation()
    return result, (perf_counter() - started) * 1000

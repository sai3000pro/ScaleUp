from __future__ import annotations

import pytest

from app.evaluation.quality_budget import (
    DEMO_SCORING_BUDGET_MS,
    MAX_OBSERVED_NOTES,
    MAX_SCORING_PAYLOAD_BYTES,
    scoring_latency_exceeded,
    scoring_request_budget,
    validate_scoring_budget,
)


def test_scoring_budget_admits_within_limits_and_reports_numeric_contract() -> None:
    validate_scoring_budget(MAX_SCORING_PAYLOAD_BYTES, MAX_OBSERVED_NOTES)

    assert scoring_request_budget(128, 4) == {
        "max_payload_bytes": MAX_SCORING_PAYLOAD_BYTES,
        "max_observed_notes": MAX_OBSERVED_NOTES,
        "max_scoring_ms": DEMO_SCORING_BUDGET_MS,
        "payload_bytes": 128,
        "observed_notes": 4,
    }


def test_scoring_budget_rejects_oversized_payloads_and_note_lists() -> None:
    with pytest.raises(ValueError, match="256 KiB"):
        validate_scoring_budget(MAX_SCORING_PAYLOAD_BYTES + 1, 4)
    with pytest.raises(ValueError, match="At most 256"):
        validate_scoring_budget(128, MAX_OBSERVED_NOTES + 1)


def test_latency_measurement_reports_target_but_does_not_gate_live_requests() -> None:
    assert scoring_latency_exceeded(DEMO_SCORING_BUDGET_MS) is False
    assert scoring_latency_exceeded(DEMO_SCORING_BUDGET_MS + 0.1) is True

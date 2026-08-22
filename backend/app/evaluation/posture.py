"""Reducing browser-derived posture metrics to one persistable score.

The geometry happens in the browser, against MediaPipe landmarks, because raw
video must never leave the page. What arrives here is already an explainable
per-metric reading: a value in 0..1, a confidence, a status, and -- crucially --
the `raw` geometric quantity it came from, so a threshold retune later is
possible at all.

This module's whole job is to decide what may be counted. The rule is the same
one the rest of the evaluator follows: **a measurement nobody could take is not
a failing measurement.** A laptop webcam at a piano usually cannot see the
learner's hips, so `torso_lean` will frequently arrive as `not_detected`. Scoring
that as 0.0 would tell a learner their posture is bad because their camera is
low, and would drag a real performance score down with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "MIN_POSTURE_CONFIDENCE",
    "POSTURE_STATUSES",
    "PostureMetric",
    "PostureScore",
    "score_posture",
]

# Below this the metric is reported but never counted. Coverage that thin is a
# camera problem, not a posture problem.
MIN_POSTURE_CONFIDENCE = 0.5

# Only these two mean "we measured something". `not_detected` means the camera
# could not see the required landmarks; `low_confidence` means it saw them too
# rarely to trust.
COUNTABLE_STATUSES = frozenset({"good", "needs_attention"})
POSTURE_STATUSES = frozenset({"not_detected", "low_confidence", "needs_attention", "good"})


@dataclass(frozen=True, slots=True)
class PostureMetric:
    key: str
    value: float
    confidence: float
    status: str
    raw: float | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class PostureScore:
    posture_accuracy: float | None
    posture_version: str
    measured_metric_count: int
    low_confidence: bool


# @spec OBS-RED-004, OBS-RED-005, OBS-RED-006, OBS-RED-008
def score_posture(metrics: Sequence[PostureMetric], *, version: str) -> PostureScore:
    """Confidence-weighted mean of the metrics that were actually measurable.

    Returns `posture_accuracy=None` when nothing qualified, which the caller
    must treat as "this dimension does not apply to this attempt" rather than as
    a zero -- the weighting in the evaluator registry redistributes a None
    component's weight across the ones that are present, so an attempt with the
    camera off scores exactly as it would have before posture existed.
    """
    countable = [
        metric
        for metric in metrics
        if metric.status in COUNTABLE_STATUSES and metric.confidence >= MIN_POSTURE_CONFIDENCE
    ]
    if not countable:
        return PostureScore(
            posture_accuracy=None,
            posture_version=version,
            measured_metric_count=0,
            low_confidence=True,
        )

    weight = sum(metric.confidence for metric in countable)
    if weight <= 0:
        return PostureScore(None, version, 0, True)
    weighted = sum(metric.value * metric.confidence for metric in countable) / weight

    return PostureScore(
        posture_accuracy=round(max(0.0, min(1.0, weighted)), 4),
        posture_version=version,
        measured_metric_count=len(countable),
        # Fewer than half the submitted metrics survived: the reading is real
        # but thin, and the examiner should say so rather than lead with it.
        low_confidence=len(countable) * 2 < len(metrics),
    )

"""Trumpet scoring: the shared monophonic pitch/rhythm core.

A trumpet is a fixed-pitch monophonic instrument, so its observable metrics are
pitch, rhythm, and tempo -- exactly what the piano core already measures. This
module is deliberately thin: it routes through the shared scorer with a trumpet
evaluator version rather than duplicating the DTW machinery. Embouchure,
breath, and tonguing signals are not yet observable from audio in this stack
and are not claimed; camera/metrics work remains a documented follow-on.
"""

from __future__ import annotations

from app.evaluation.piano import PerformedNote, PianoPerformanceScore, score_performance

__all__ = ["PerformedNote", "TrumpetPerformanceScore", "score_trumpet_performance"]

# The piano score carries the same fields and semantics for trumpet; it is not
# a reinterpretation, it is the shared monophonic contract.
TrumpetPerformanceScore = PianoPerformanceScore


# @spec EVAL-INST-005
def score_trumpet_performance(
    score,
    observed_notes: list[PerformedNote] | tuple[PerformedNote, ...],
    evaluator_version: str = "trumpet-dtw-v1",
) -> TrumpetPerformanceScore:
    return score_performance(score, observed_notes, evaluator_version=evaluator_version)

"""Explainable piano scoring over canonical note events.

Audio feature extraction is deliberately outside this module. A browser or DSP
adapter converts a recording into ``PerformedNote`` values; this module then
produces deterministic metrics from those values and a normalized MusicXML score.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.evaluation.dtw import DTWAlignment, align
from app.evaluation.musicxml import MusicXMLScore


@dataclass(frozen=True, slots=True)
class PerformedNote:
    """One note observation emitted by a future audio feature extractor."""

    pitch_midi: float
    onset_seconds: float
    duration_seconds: float = 0.0
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not isfinite(self.pitch_midi) or not 0 <= self.pitch_midi <= 127:
            raise ValueError("Performed MIDI pitch must be finite and between 0 and 127.")
        if not isfinite(self.onset_seconds) or self.onset_seconds < 0:
            raise ValueError("Performed note onset must be finite and non-negative.")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("Performed note duration must be finite and non-negative.")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Performed note confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class _ExpectedNote:
    pitch_midi: int
    onset_beats: float
    onset_seconds: float


@dataclass(frozen=True, slots=True)
class PianoPerformanceScore:
    evaluator_version: str
    expected_note_count: int
    observed_note_count: int
    matched_note_count: int
    missed_note_count: int
    extra_note_count: int
    # Nullable so rhythm-only instruments (drums) can share the same bundle
    # contract without inventing a pitch score.
    pitch_accuracy: float | None
    rhythm_accuracy: float
    tempo_bpm: float | None
    tempo_deviation_percent: float | None
    alignment_confidence: float
    overall_score: float
    # Set by the violin evaluator; None for instruments that do not measure
    # intonation. Defaults keep the piano/trumpet constructors untouched.
    intonation_accuracy: float | None = None
    intonation_deviation_cents: float | None = None

    @property
    def low_confidence(self) -> bool:
        return self.alignment_confidence < 0.5


def _expected_notes(score: MusicXMLScore) -> list[_ExpectedNote]:
    seconds_per_beat = 60.0 / score.tempo_bpm
    return [
        _ExpectedNote(
            pitch_midi=note.pitch_midi,
            onset_beats=note.onset_beats,
            onset_seconds=note.onset_beats * seconds_per_beat,
        )
        for note in score.pitched_notes
        if note.pitch_midi is not None
    ]


# Named rather than inlined so the online matcher in `online.py` can import
# them. Two notions of "close enough" that drift apart would make a live cue
# contradict the grade the same take is about to receive.
PITCH_COST_WEIGHT = 0.55
TIMING_COST_WEIGHT = 0.35
CONFIDENCE_COST_WEIGHT = 0.10


def _distance(expected: object, observed: object, timing_tolerance: float) -> float:
    expected_note = expected
    observed_note = observed
    if not isinstance(expected_note, _ExpectedNote) or not isinstance(observed_note, PerformedNote):
        raise TypeError("Piano DTW distance received an unexpected event type.")
    pitch_cost = min(abs(expected_note.pitch_midi - observed_note.pitch_midi) / 6.0, 1.0)
    timing_cost = min(abs(expected_note.onset_seconds - observed_note.onset_seconds) / timing_tolerance, 1.0)
    confidence_cost = 1.0 - observed_note.confidence
    return PITCH_COST_WEIGHT * pitch_cost + TIMING_COST_WEIGHT * timing_cost + CONFIDENCE_COST_WEIGHT * confidence_cost


def _quality(expected: _ExpectedNote, observed: PerformedNote, timing_tolerance: float) -> tuple[float, float]:
    pitch_quality = max(0.0, 1.0 - abs(expected.pitch_midi - observed.pitch_midi) / 0.5)
    rhythm_quality = max(
        0.0,
        1.0 - abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance,
    )
    confidence = observed.confidence
    return pitch_quality * confidence, rhythm_quality * confidence


# @spec EVAL-ALIGN-003
def _tempo_metrics(
    score: MusicXMLScore,
    expected: list[_ExpectedNote],
    observed: list[PerformedNote],
    alignment: DTWAlignment,
) -> tuple[float | None, float | None]:
    matches = alignment.matches
    if len(matches) < 2:
        return None, None

    first = matches[0]
    last = matches[-1]
    if first.expected_index is None or last.expected_index is None:
        return None, None
    if first.observed_index is None or last.observed_index is None:
        return None, None

    expected_span_beats = expected[last.expected_index].onset_beats - expected[first.expected_index].onset_beats
    observed_span_seconds = observed[last.observed_index].onset_seconds - observed[first.observed_index].onset_seconds
    if expected_span_beats <= 0 or observed_span_seconds <= 0:
        return None, None

    tempo_bpm = expected_span_beats * 60.0 / observed_span_seconds
    deviation = abs(tempo_bpm - score.tempo_bpm) / score.tempo_bpm * 100.0
    return round(tempo_bpm, 3), round(deviation, 3)


# @spec EVAL-INST-002, EVAL-ALIGN-002, EVAL-ALIGN-004, EVAL-ALIGN-005
def score_performance(
    score: MusicXMLScore,
    observed_notes: list[PerformedNote] | tuple[PerformedNote, ...],
    evaluator_version: str = "piano-dtw-v1",
) -> PianoPerformanceScore:
    """Score pitch and rhythm using DTW alignment.

    Pitch and rhythm accuracy are measured against expected notes, so a missed
    note contributes zero rather than disappearing from the denominator. Extra
    observations are reported and lower the overall score separately. This
    keeps feedback specific: "three missed, one extra" is more actionable than a
    single opaque percentage.
    """
    expected = _expected_notes(score)
    observed = sorted(observed_notes, key=lambda note: (note.onset_seconds, note.pitch_midi))
    if not expected:
        raise ValueError("A piano score must contain at least one pitched note.")

    seconds_per_beat = 60.0 / score.tempo_bpm
    timing_tolerance = max(0.18, seconds_per_beat * 0.5)
    alignment = align(
        expected,
        observed,
        distance=lambda left, right: _distance(left, right, timing_tolerance),
        deletion_cost=1.0,
        insertion_cost=0.85,
    )

    pitch_total = 0.0
    rhythm_total = 0.0
    for step in alignment.matches:
        if step.expected_index is not None and step.observed_index is not None:
            pitch_quality, rhythm_quality = _quality(
                expected[step.expected_index], observed[step.observed_index], timing_tolerance
            )
            pitch_total += pitch_quality
            rhythm_total += rhythm_quality

    expected_count = len(expected)
    observed_count = len(observed)
    matched_count = len(alignment.matches)
    missed_count = len(alignment.deletions)
    extra_count = len(alignment.insertions)
    pitch_accuracy = round(pitch_total / expected_count, 4)
    rhythm_accuracy = round(rhythm_total / expected_count, 4)
    alignment_confidence = round(
        max(0.0, min(1.0, 1.0 - alignment.distance / max(expected_count, observed_count))),
        4,
    )
    extra_penalty = expected_count / max(expected_count + extra_count, 1)
    overall_score = round(max(0.0, min(1.0, (0.6 * pitch_accuracy + 0.4 * rhythm_accuracy) * extra_penalty)), 4)
    tempo_bpm, tempo_deviation = _tempo_metrics(score, expected, observed, alignment)

    return PianoPerformanceScore(
        evaluator_version=evaluator_version,
        expected_note_count=expected_count,
        observed_note_count=observed_count,
        matched_note_count=matched_count,
        missed_note_count=missed_count,
        extra_note_count=extra_count,
        pitch_accuracy=pitch_accuracy,
        rhythm_accuracy=rhythm_accuracy,
        tempo_bpm=tempo_bpm,
        tempo_deviation_percent=tempo_deviation,
        alignment_confidence=alignment_confidence,
        overall_score=overall_score,
    )

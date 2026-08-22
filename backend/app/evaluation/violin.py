"""Violin scoring: pitch, rhythm, and intonation over the shared DTW core.

Violin's distinguishing measurement is *intonation*: the same written note can
be a few cents sharp or flat, which is exactly what a future pitch tracker can
emit and what a beginner needs corrected. The scorer therefore accepts a per
note `cents_deviation` (positive = sharp, negative = flat, `0.0` dead centre,
`None` not measured) and reports intonation accuracy and mean absolute
deviation alongside the piano-compatible pitch/rhythm/tempo metrics. Where no
note carried a reading, intonation is reported as unmeasured and its weight
redistributes -- it is never a score of zero. Bowing, posture, and wrist
checks stay in the camera (MediaPipe) path -- audio cannot see them.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.evaluation.dtw import DTWAlignment, align
from app.evaluation.musicxml import MusicXMLScore

# How far off-centre a note can be before intonation is treated as fully wrong.
# A quarter-tone is 50 cents; treating ~half a quarter-tone as the failure
# point keeps the scale strict enough to be useful without punishing the
# tolerance of a working instrument.
INTONATION_FAIL_CENTS = 30.0


@dataclass(frozen=True, slots=True)
class ViolinNote:
    """One violin observation.

    `cents_deviation` is `None` when intonation was not measured and a number
    when it was -- including `0.0`, which is a real reading meaning dead centre.
    The two must stay distinguishable: the shipped detector reports no cents at
    all, so `None` is the ordinary case, and collapsing it onto `0.0` would
    either credit every learner with perfect intonation or throw every
    perfectly-tuned note out of the average.
    """

    pitch_midi: float
    onset_seconds: float
    duration_seconds: float = 0.0
    confidence: float = 1.0
    cents_deviation: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.pitch_midi) or not 0 <= self.pitch_midi <= 127:
            raise ValueError("Violin MIDI pitch must be finite and between 0 and 127.")
        if not isfinite(self.onset_seconds) or self.onset_seconds < 0:
            raise ValueError("Violin note onset must be finite and non-negative.")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("Violin note duration must be finite and non-negative.")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Violin note confidence must be between 0 and 1.")
        if self.cents_deviation is not None and not isfinite(self.cents_deviation):
            raise ValueError("Violin cents deviation must be finite.")


@dataclass(frozen=True, slots=True)
class _ExpectedViolinNote:
    pitch_midi: int
    onset_beats: float
    onset_seconds: float


@dataclass(frozen=True, slots=True)
class ViolinPerformanceScore:
    evaluator_version: str
    expected_note_count: int
    observed_note_count: int
    matched_note_count: int
    missed_note_count: int
    extra_note_count: int
    pitch_accuracy: float
    rhythm_accuracy: float
    intonation_accuracy: float | None
    intonation_deviation_cents: float | None
    tempo_bpm: float | None
    tempo_deviation_percent: float | None
    alignment_confidence: float
    overall_score: float

    @property
    def low_confidence(self) -> bool:
        return self.alignment_confidence < 0.5


def _expected_notes(score: MusicXMLScore) -> list[_ExpectedViolinNote]:
    seconds_per_beat = 60.0 / score.tempo_bpm
    return [
        _ExpectedViolinNote(
            pitch_midi=note.pitch_midi,
            onset_beats=note.onset_beats,
            onset_seconds=note.onset_beats * seconds_per_beat,
        )
        for note in score.pitched_notes
        if note.pitch_midi is not None
    ]


def _distance(expected: object, observed: object, timing_tolerance: float) -> float:
    if not isinstance(expected, _ExpectedViolinNote) or not isinstance(observed, ViolinNote):
        raise TypeError("Violin DTW distance received an unexpected event type.")
    pitch_cost = min(abs(expected.pitch_midi - observed.pitch_midi) / 6.0, 1.0)
    timing_cost = min(abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance, 1.0)
    confidence_cost = 1.0 - observed.confidence
    return 0.45 * pitch_cost + 0.35 * timing_cost + 0.20 * confidence_cost


# @spec EVAL-INST-010
def _intonation_quality(cents_deviation: float) -> float:
    """0.0 at INTONATION_FAIL_CENTS or beyond, 1.0 dead centre, linear between."""
    deviation = abs(cents_deviation)
    if deviation >= INTONATION_FAIL_CENTS:
        return 0.0
    return 1.0 - deviation / INTONATION_FAIL_CENTS


def _quality(
    expected: _ExpectedViolinNote, observed: ViolinNote, timing_tolerance: float
) -> tuple[float, float]:
    pitch_quality = max(0.0, 1.0 - abs(expected.pitch_midi - observed.pitch_midi) / 0.5)
    rhythm_quality = max(0.0, 1.0 - abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance)
    confidence = observed.confidence
    return pitch_quality * confidence, rhythm_quality * confidence


def _tempo_metrics(
    score: MusicXMLScore,
    expected: list[_ExpectedViolinNote],
    observed: list[ViolinNote],
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


# @spec EVAL-INST-004, EVAL-INST-009
def score_violin_performance(
    score: MusicXMLScore,
    observed_notes: list[ViolinNote] | tuple[ViolinNote, ...],
    evaluator_version: str = "violin-dtw-v1",
) -> ViolinPerformanceScore:
    """Score pitch, rhythm, and intonation with a single DTW alignment."""
    expected = _expected_notes(score)
    observed = sorted(observed_notes, key=lambda note: (note.onset_seconds, note.pitch_midi))
    if not expected:
        raise ValueError("A violin score must contain at least one pitched note.")

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
    intonation_total = 0.0
    intonation_count = 0
    cents_total = 0.0
    for step in alignment.matches:
        if step.expected_index is not None and step.observed_index is not None:
            exp = expected[step.expected_index]
            obs = observed[step.observed_index]
            pitch_quality, rhythm_quality = _quality(exp, obs, timing_tolerance)
            pitch_total += pitch_quality
            rhythm_total += rhythm_quality
            if obs.cents_deviation is not None:
                intonation_total += _intonation_quality(obs.cents_deviation) * obs.confidence
                cents_total += abs(obs.cents_deviation)
                intonation_count += 1

    expected_count = len(expected)
    observed_count = len(observed)
    pitch_accuracy = round(pitch_total / expected_count, 4)
    rhythm_accuracy = round(rhythm_total / expected_count, 4)
    intonation_accuracy = round(intonation_total / intonation_count, 4) if intonation_count else None
    intonation_deviation = round(cents_total / intonation_count, 3) if intonation_count else None
    alignment_confidence = round(
        max(0.0, min(1.0, 1.0 - alignment.distance / max(expected_count, observed_count))),
        4,
    )
    extra_penalty = expected_count / max(expected_count + len(alignment.insertions), 1)
    if intonation_accuracy is not None:
        base = 0.5 * pitch_accuracy + 0.3 * rhythm_accuracy + 0.2 * intonation_accuracy
    else:
        base = 0.6 * pitch_accuracy + 0.4 * rhythm_accuracy
    overall_score = round(max(0.0, min(1.0, base * extra_penalty)), 4)
    tempo_bpm, tempo_deviation = _tempo_metrics(score, expected, observed, alignment)

    return ViolinPerformanceScore(
        evaluator_version=evaluator_version,
        expected_note_count=expected_count,
        observed_note_count=observed_count,
        matched_note_count=len(alignment.matches),
        missed_note_count=len(alignment.deletions),
        extra_note_count=len(alignment.insertions),
        pitch_accuracy=pitch_accuracy,
        rhythm_accuracy=rhythm_accuracy,
        intonation_accuracy=intonation_accuracy,
        intonation_deviation_cents=intonation_deviation,
        tempo_bpm=tempo_bpm,
        tempo_deviation_percent=tempo_deviation,
        alignment_confidence=alignment_confidence,
        overall_score=overall_score,
    )

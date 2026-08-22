"""Drums scoring: rhythm and drum identity, with pitch explicitly inapplicable.

Drums are the shape that must NOT be forced into the piano metric schema: a
kick drum has no pitch to get right, so `pitch_accuracy` is always None and the
overall score is rhythm-only. The MusicXML score is a sequence of *unpitched*
events; the written display-step/display-octave identifies which drum was
intended (mirroring how guitar tab carries string/fret that audio cannot
hear), and the observed hits may carry the same identity when the adapter can
detect it. A hit without identity is scored leniently for rhythm only.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.evaluation.dtw import DTWAlignment, align
from app.evaluation.musicxml import MusicXMLScore

# Written drum identity by (display-step, display-octave), chosen to match the
# seeded rock-groove exercise. Adding a drum is adding a row here, not touching
# the scoring math.
EXPECTED_DRUM_BY_POSITION = {
    ("C", 5): "kick",
    ("D", 5): "snare",
    ("F#", 5): "hihat",
}

KNOWN_DRUM_IDS = frozenset({"kick", "snare", "hihat", "crash", "ride", "tom"})


@dataclass(frozen=True, slots=True)
class DrumHit:
    """One percussion observation. `drum` identifies which drum, when known."""

    onset_seconds: float
    duration_seconds: float = 0.0
    confidence: float = 1.0
    drum: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.onset_seconds) or self.onset_seconds < 0:
            raise ValueError("Drum hit onset must be finite and non-negative.")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("Drum hit duration must be finite and non-negative.")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Drum hit confidence must be between 0 and 1.")
        if self.drum is not None and self.drum not in KNOWN_DRUM_IDS:
            raise ValueError(f"Unknown drum id: {self.drum!r}.")


@dataclass(frozen=True, slots=True)
class _ExpectedDrumHit:
    onset_beats: float
    onset_seconds: float
    drum: str


@dataclass(frozen=True, slots=True)
class DrumsPerformanceScore:
    evaluator_version: str
    expected_note_count: int
    observed_note_count: int
    matched_note_count: int
    missed_note_count: int
    extra_note_count: int
    # Drums have no pitch: this is always None and the wire schema treats it as
    # "inapplicable" rather than a score of zero.
    pitch_accuracy: float | None = None
    rhythm_accuracy: float = 0.0
    tempo_bpm: float | None = None
    tempo_deviation_percent: float | None = None
    alignment_confidence: float = 0.0
    overall_score: float = 0.0

    @property
    def low_confidence(self) -> bool:
        return self.alignment_confidence < 0.5


def _expected_hits(score: MusicXMLScore) -> list[_ExpectedDrumHit]:
    seconds_per_beat = 60.0 / score.tempo_bpm
    hits: list[_ExpectedDrumHit] = []
    for note in score.notes:
        if note.pitch_midi is None and note.unpitched_step is not None:
            drum = EXPECTED_DRUM_BY_POSITION.get((note.unpitched_step, note.unpitched_octave))
            if drum is not None:
                hits.append(
                    _ExpectedDrumHit(
                        onset_beats=note.onset_beats,
                        onset_seconds=note.onset_beats * seconds_per_beat,
                        drum=drum,
                    )
                )
    return hits


def _distance(expected: object, observed: object, timing_tolerance: float) -> float:
    if not isinstance(expected, _ExpectedDrumHit) or not isinstance(observed, DrumHit):
        raise TypeError("Drums DTW distance received an unexpected event type.")
    timing_cost = min(abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance, 1.0)
    drum_cost = 0.0 if (observed.drum is None or observed.drum == expected.drum) else 1.0
    confidence_cost = 1.0 - observed.confidence
    return 0.55 * timing_cost + 0.35 * drum_cost + 0.10 * confidence_cost


def _quality(expected: _ExpectedDrumHit, observed: DrumHit, timing_tolerance: float) -> float:
    rhythm_quality = max(0.0, 1.0 - abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance)
    drum_quality = 1.0 if (observed.drum is None or observed.drum == expected.drum) else 0.0
    return rhythm_quality * drum_quality * observed.confidence


def _tempo_metrics(
    score: MusicXMLScore,
    expected: list[_ExpectedDrumHit],
    observed: list[DrumHit],
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


# @spec EVAL-INST-006, EVAL-INST-007
def score_drums_performance(
    score: MusicXMLScore,
    observed_hits: list[DrumHit] | tuple[DrumHit, ...],
    evaluator_version: str = "drums-rhythm-v1",
) -> DrumsPerformanceScore:
    """Score rhythm and drum identity with a single DTW alignment. No pitch."""
    expected = _expected_hits(score)
    observed = sorted(observed_hits, key=lambda hit: (hit.onset_seconds, hit.drum or ""))
    if not expected:
        raise ValueError("A drums score must contain at least one percussion event mapped to a known drum.")

    seconds_per_beat = 60.0 / score.tempo_bpm
    timing_tolerance = max(0.18, seconds_per_beat * 0.5)
    alignment = align(
        expected,
        observed,
        distance=lambda left, right: _distance(left, right, timing_tolerance),
        deletion_cost=1.0,
        insertion_cost=0.85,
    )

    rhythm_total = 0.0
    for step in alignment.matches:
        if step.expected_index is not None and step.observed_index is not None:
            rhythm_total += _quality(expected[step.expected_index], observed[step.observed_index], timing_tolerance)

    expected_count = len(expected)
    observed_count = len(observed)
    rhythm_accuracy = round(rhythm_total / expected_count, 4)
    alignment_confidence = round(
        max(0.0, min(1.0, 1.0 - alignment.distance / max(expected_count, observed_count))),
        4,
    )
    extra_penalty = expected_count / max(expected_count + len(alignment.insertions), 1)
    overall_score = round(max(0.0, min(1.0, rhythm_accuracy * extra_penalty)), 4)
    tempo_bpm, tempo_deviation = _tempo_metrics(score, expected, observed, alignment)

    return DrumsPerformanceScore(
        evaluator_version=evaluator_version,
        expected_note_count=expected_count,
        observed_note_count=observed_count,
        matched_note_count=len(alignment.matches),
        missed_note_count=len(alignment.deletions),
        extra_note_count=len(alignment.insertions),
        rhythm_accuracy=rhythm_accuracy,
        tempo_bpm=tempo_bpm,
        tempo_deviation_percent=tempo_deviation,
        alignment_confidence=alignment_confidence,
        overall_score=overall_score,
    )

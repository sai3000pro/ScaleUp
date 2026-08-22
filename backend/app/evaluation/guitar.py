"""Guitar scoring adds fretboard technique to the shared DTW pitch/rhythm core.

Pitch and rhythm are scored exactly like piano; what makes guitar distinct is
*position*: the same pitch is reachable at several (string, fret) locations, and
the written tab tells the learner which one to use. This module scores whether
the performed position matches the written one, without pretending a recording
already yields string/fret — the same future audio adapter that emits pitch can
emit position, and this scorer degrades cleanly when it does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.evaluation.dtw import DTWAlignment, align
from app.evaluation.musicxml import MusicXMLScore

# Standard tuning, open-string MIDI pitches for strings 6..1 (E2 A2 D3 G3 B3 E4).
OPEN_STRING_MIDI = (40, 45, 50, 55, 59, 64)
MIN_STRING = 1
MAX_STRING = 6
MIN_FRET = 0
MAX_FRET = 24

# Onset spread that still counts as one strummed chord event. A real strum
# lands the strings a few milliseconds apart and a six-string strum spans
# roughly a tenth of a second; beyond this window the notes are separate
# events (broken chord / separate attack). Quarter notes at 90bpm are 0.67s
# apart, so this never merges two beats.
CHORD_ONSET_TOLERANCE_SECONDS = 0.12


def open_string_midi(string: int) -> int:
    """Return the open-string pitch for a 1-indexed guitar string."""
    if not MIN_STRING <= string <= MAX_STRING:
        raise ValueError("Guitar string must be between 1 and 6.")
    return OPEN_STRING_MIDI[MAX_STRING - string]


def pitch_for_position(string: int, fret: int) -> int:
    """Return the sounding MIDI pitch of a (string, fret) position."""
    if not MIN_FRET <= fret <= MAX_FRET:
        raise ValueError(f"Guitar fret must be between {MIN_FRET} and {MAX_FRET}.")
    return open_string_midi(string) + fret


@dataclass(frozen=True, slots=True)
class GuitarNote:
    """One guitar observation. Position is optional and validated when present."""

    pitch_midi: float
    onset_seconds: float
    duration_seconds: float = 0.0
    confidence: float = 1.0
    string: int | None = None
    fret: int | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.pitch_midi) or not 0 <= self.pitch_midi <= 127:
            raise ValueError("Guitar MIDI pitch must be finite and between 0 and 127.")
        if not isfinite(self.onset_seconds) or self.onset_seconds < 0:
            raise ValueError("Guitar note onset must be finite and non-negative.")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("Guitar note duration must be finite and non-negative.")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Guitar note confidence must be between 0 and 1.")
        if self.string is not None and not MIN_STRING <= self.string <= MAX_STRING:
            raise ValueError("Guitar string must be between 1 and 6.")
        if self.fret is not None and not MIN_FRET <= self.fret <= MAX_FRET:
            raise ValueError(f"Guitar fret must be between {MIN_FRET} and {MAX_FRET}.")
        if self.string is not None and self.fret is not None:
            expected_pitch = pitch_for_position(self.string, self.fret)
            if int(round(self.pitch_midi)) != expected_pitch:
                raise ValueError(
                    f"Guitar position (string {self.string}, fret {self.fret}) "
                    f"implies pitch {expected_pitch}, not {round(self.pitch_midi)}."
                )


@dataclass(frozen=True, slots=True)
class _ExpectedGuitarNote:
    pitch_midi: int
    onset_beats: float
    onset_seconds: float
    string: int | None
    fret: int | None


@dataclass(frozen=True, slots=True)
class GuitarPerformanceScore:
    evaluator_version: str
    expected_note_count: int
    observed_note_count: int
    matched_note_count: int
    missed_note_count: int
    extra_note_count: int
    pitch_accuracy: float
    rhythm_accuracy: float
    technique_accuracy: float | None
    position_error_count: int
    tempo_bpm: float | None
    tempo_deviation_percent: float | None
    alignment_confidence: float
    overall_score: float

    @property
    def low_confidence(self) -> bool:
        return self.alignment_confidence < 0.5


def _expected_notes(score: MusicXMLScore) -> list[_ExpectedGuitarNote]:
    seconds_per_beat = 60.0 / score.tempo_bpm
    return [
        _ExpectedGuitarNote(
            pitch_midi=note.pitch_midi,
            onset_beats=note.onset_beats,
            onset_seconds=note.onset_beats * seconds_per_beat,
            string=note.string,
            fret=note.fret,
        )
        for note in score.pitched_notes
        if note.pitch_midi is not None
    ]


def _position_cost(expected: _ExpectedGuitarNote, observed: GuitarNote) -> float:
    if expected.string is None or observed.string is None:
        return 0.0
    if expected.string == observed.string and expected.fret == observed.fret:
        return 0.0
    if expected.string == observed.string:
        return 0.5
    return 1.0


def _distance(expected: object, observed: object, timing_tolerance: float) -> float:
    if not isinstance(expected, _ExpectedGuitarNote) or not isinstance(observed, GuitarNote):
        raise TypeError("Guitar DTW distance received an unexpected event type.")
    pitch_cost = min(abs(expected.pitch_midi - observed.pitch_midi) / 6.0, 1.0)
    timing_cost = min(abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance, 1.0)
    confidence_cost = 1.0 - observed.confidence
    return 0.45 * pitch_cost + 0.25 * timing_cost + 0.20 * _position_cost(expected, observed) + 0.10 * confidence_cost


def _quality(
    expected: _ExpectedGuitarNote, observed: GuitarNote, timing_tolerance: float
) -> tuple[float, float]:
    pitch_quality = max(0.0, 1.0 - abs(expected.pitch_midi - observed.pitch_midi) / 0.5)
    rhythm_quality = max(0.0, 1.0 - abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance)
    confidence = observed.confidence
    return pitch_quality * confidence, rhythm_quality * confidence


def _tempo_metrics(
    score: MusicXMLScore,
    expected: list[_ExpectedGuitarNote],
    observed: list[GuitarNote],
    alignment: DTWAlignment,
) -> tuple[float | None, float | None]:
    matches = alignment.matches
    if len(matches) < 2:
        return None, None
    first = matches[0]
    last = matches[-1]
    if None in (first.expected_index, first.observed_index, last.expected_index, last.observed_index):
        return None, None
    expected_span_beats = expected[last.expected_index].onset_beats - expected[first.expected_index].onset_beats
    observed_span_seconds = observed[last.observed_index].onset_seconds - observed[first.observed_index].onset_seconds
    if expected_span_beats <= 0 or observed_span_seconds <= 0:
        return None, None
    tempo_bpm = expected_span_beats * 60.0 / observed_span_seconds
    deviation = abs(tempo_bpm - score.tempo_bpm) / score.tempo_bpm * 100.0
    return round(tempo_bpm, 3), round(deviation, 3)


# @spec EVAL-INST-003, EVAL-INST-011
def score_guitar_performance(
    score: MusicXMLScore,
    observed_notes: list[GuitarNote] | tuple[GuitarNote, ...],
    evaluator_version: str = "guitar-dtw-v1",
) -> GuitarPerformanceScore:
    """Score pitch, rhythm, and fretboard position with a single DTW alignment."""
    expected = _expected_notes(score)
    observed = sorted(observed_notes, key=lambda note: (note.onset_seconds, note.pitch_midi))
    if not expected:
        raise ValueError("A guitar score must contain at least one pitched note.")

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
    positioned_expected = 0
    positioned_correct = 0
    position_errors = 0
    for step in alignment.matches:
        if step.expected_index is not None and step.observed_index is not None:
            exp = expected[step.expected_index]
            obs = observed[step.observed_index]
            pitch_quality, rhythm_quality = _quality(exp, obs, timing_tolerance)
            pitch_total += pitch_quality
            rhythm_total += rhythm_quality
            if exp.string is not None and obs.string is not None:
                positioned_expected += 1
                if exp.string == obs.string and exp.fret == obs.fret:
                    positioned_correct += 1
                else:
                    position_errors += 1

    expected_count = len(expected)
    observed_count = len(observed)
    pitch_accuracy = round(pitch_total / expected_count, 4)
    rhythm_accuracy = round(rhythm_total / expected_count, 4)
    technique_accuracy = round(positioned_correct / positioned_expected, 4) if positioned_expected else None
    alignment_confidence = round(
        max(0.0, min(1.0, 1.0 - alignment.distance / max(expected_count, observed_count))),
        4,
    )
    extra_penalty = expected_count / max(expected_count + len(alignment.insertions), 1)
    base = 0.6 * pitch_accuracy + 0.4 * rhythm_accuracy
    if technique_accuracy is not None:
        base = 0.5 * pitch_accuracy + 0.3 * rhythm_accuracy + 0.2 * technique_accuracy
    overall_score = round(max(0.0, min(1.0, base * extra_penalty)), 4)
    tempo_bpm, tempo_deviation = _tempo_metrics(score, expected, observed, alignment)

    return GuitarPerformanceScore(
        evaluator_version=evaluator_version,
        expected_note_count=expected_count,
        observed_note_count=observed_count,
        matched_note_count=len(alignment.matches),
        missed_note_count=len(alignment.deletions),
        extra_note_count=len(alignment.insertions),
        pitch_accuracy=pitch_accuracy,
        rhythm_accuracy=rhythm_accuracy,
        technique_accuracy=technique_accuracy,
        position_error_count=position_errors,
        tempo_bpm=tempo_bpm,
        tempo_deviation_percent=tempo_deviation,
        alignment_confidence=alignment_confidence,
        overall_score=overall_score,
    )


# ── open-chord / strumming scoring ───────────────────────────────────────
#
# Same evaluator contract as single-note fretting -- pitch_accuracy, rhythm,
# technique, tempo -- but the event is a *chord*: every expected note that
# shares an onset is one chord, and observed notes whose onsets land within
# CHORD_ONSET_TOLERANCE are one strum. Pitch accuracy is the fraction of the
# written chord's notes that actually sounded, so a missing string is a
# missing note, not a wrong one.


@dataclass(frozen=True, slots=True)
class GuitarChord:
    """One observed strummed chord: the sounding pitches and their positions."""

    pitch_midis: frozenset[int]
    onset_seconds: float
    positions: tuple[tuple[int, int], ...] = ()
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not isfinite(self.onset_seconds) or self.onset_seconds < 0:
            raise ValueError("Guitar chord onset must be finite and non-negative.")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Guitar chord confidence must be between 0 and 1.")
        for string, fret in self.positions:
            if not MIN_STRING <= string <= MAX_STRING:
                raise ValueError("Guitar string must be between 1 and 6.")
            if not MIN_FRET <= fret <= MAX_FRET:
                raise ValueError(f"Guitar fret must be between {MIN_FRET} and {MAX_FRET}.")


@dataclass(frozen=True, slots=True)
class _ExpectedGuitarChord:
    pitch_midis: frozenset[int]
    onset_beats: float
    onset_seconds: float
    positions: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _PositionedGuitarNote:
    pitch_midi: int
    onset_seconds: float
    string: int | None
    fret: int | None


def _expected_chords(score: MusicXMLScore) -> list[_ExpectedGuitarChord]:
    """Group score notes by shared onset into chord events."""
    seconds_per_beat = 60.0 / score.tempo_bpm
    by_onset: dict[float, list[_PositionedGuitarNote]] = {}
    for note in score.pitched_notes:
        by_onset.setdefault(note.onset_beats, []).append(
            _PositionedGuitarNote(
                pitch_midi=note.pitch_midi,
                onset_seconds=note.onset_beats * seconds_per_beat,
                string=note.string,
                fret=note.fret,
            )
        )
    return [
        _ExpectedGuitarChord(
            pitch_midis=frozenset(note.pitch_midi for note in notes),
            onset_beats=onset,
            onset_seconds=notes[0].onset_seconds,
            positions=tuple((note.string, note.fret) for note in notes if note.string is not None and note.fret is not None),
        )
        for onset, notes in sorted(by_onset.items())
    ]


def _observed_chords(observed_notes: list[GuitarNote]) -> list[GuitarChord]:
    """Group observed notes by onset proximity into strummed chord events."""
    ordered = sorted(observed_notes, key=lambda note: (note.onset_seconds, note.pitch_midi))
    chords: list[GuitarChord] = []
    for note in ordered:
        if chords and note.onset_seconds - chords[-1].onset_seconds <= CHORD_ONSET_TOLERANCE_SECONDS:
            previous = chords[-1]
            chords[-1] = GuitarChord(
                pitch_midis=frozenset(previous.pitch_midis | {note.pitch_midi}),
                onset_seconds=previous.onset_seconds,
                positions=previous.positions
                + (((note.string, note.fret),) if note.string is not None and note.fret is not None else ()),
                confidence=min(previous.confidence, note.confidence),
            )
        else:
            chords.append(
                GuitarChord(
                    pitch_midis=frozenset({note.pitch_midi}),
                    onset_seconds=note.onset_seconds,
                    positions=((note.string, note.fret),) if note.string is not None and note.fret is not None else (),
                    confidence=note.confidence,
                )
            )
    return chords


def _chord_distance(expected: object, observed: object, timing_tolerance: float) -> float:
    if not isinstance(expected, _ExpectedGuitarChord) or not isinstance(observed, GuitarChord):
        raise TypeError("Guitar chord DTW distance received an unexpected event type.")
    missing = expected.pitch_midis - observed.pitch_midis
    pitch_cost = min(len(missing) / max(len(expected.pitch_midis), 1), 1.0)
    timing_cost = min(abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance, 1.0)
    confidence_cost = 1.0 - observed.confidence
    return 0.5 * pitch_cost + 0.35 * timing_cost + 0.15 * confidence_cost


def _chord_quality(
    expected: _ExpectedGuitarChord, observed: GuitarChord, timing_tolerance: float
) -> tuple[float, float, tuple[tuple[int, int], ...]]:
    """Return (pitch quality, rhythm quality, matched positions)."""
    sounding = expected.pitch_midis & observed.pitch_midis
    pitch_quality = len(sounding) / max(len(expected.pitch_midis), 1)
    rhythm_quality = max(0.0, 1.0 - abs(expected.onset_seconds - observed.onset_seconds) / timing_tolerance)
    confidence = observed.confidence
    expected_positions = {position: True for position in expected.positions}
    matched_positions = tuple(position for position in observed.positions if expected_positions.get(position))
    return pitch_quality * confidence, rhythm_quality * confidence, matched_positions


def score_guitar_chords_performance(
    score: MusicXMLScore,
    observed_notes: list[GuitarNote] | tuple[GuitarNote, ...],
    evaluator_version: str = "guitar-chords-v1",
) -> GuitarPerformanceScore:
    """Score open-chord strumming: pitch coverage, rhythm, and string/fret position.

    Returns the same contract as single-note fretting, so the practice,
    feedback, EXP, and SRS paths need no instrument-specific branching beyond
    routing: `pitch_accuracy` is how much of each written chord actually
    sounded, and `technique_accuracy` is how many sounding strings were fretted
    at the written position.
    """
    expected = _expected_chords(score)
    observed = _observed_chords(observed_notes)
    if not expected:
        raise ValueError("A guitar chord score must contain at least one chord.")

    seconds_per_beat = 60.0 / score.tempo_bpm
    timing_tolerance = max(0.18, seconds_per_beat * 0.5)
    alignment = align(
        expected,
        observed,
        distance=lambda left, right: _chord_distance(left, right, timing_tolerance),
        deletion_cost=1.0,
        insertion_cost=0.85,
    )

    pitch_total = 0.0
    rhythm_total = 0.0
    expected_position_count = 0
    matched_position_count = 0
    for step in alignment.matches:
        if step.expected_index is not None and step.observed_index is not None:
            exp = expected[step.expected_index]
            obs = observed[step.observed_index]
            pitch_quality, rhythm_quality, matched_positions = _chord_quality(exp, obs, timing_tolerance)
            pitch_total += pitch_quality
            rhythm_total += rhythm_quality
            expected_position_count += len(exp.positions)
            matched_position_count += len(matched_positions)

    expected_count = len(expected)
    observed_count = len(observed)
    pitch_accuracy = round(pitch_total / expected_count, 4)
    rhythm_accuracy = round(rhythm_total / expected_count, 4)
    technique_accuracy = round(matched_position_count / expected_position_count, 4) if expected_position_count else None
    alignment_confidence = round(
        max(0.0, min(1.0, 1.0 - alignment.distance / max(expected_count, observed_count))),
        4,
    )
    extra_penalty = expected_count / max(expected_count + len(alignment.insertions), 1)
    # Same shape as the single-note path above: technique is worth 0.2 when the
    # notation named a fingering to compare against, and weighs nothing when it
    # did not. Folding an unmeasured dimension in as 0.0 would tell a learner
    # they lost a fifth of the marks for something the score never contained.
    base = 0.6 * pitch_accuracy + 0.4 * rhythm_accuracy
    if technique_accuracy is not None:
        base = 0.5 * pitch_accuracy + 0.3 * rhythm_accuracy + 0.2 * technique_accuracy
    overall_score = round(max(0.0, min(1.0, base * extra_penalty)), 4)
    tempo_bpm, tempo_deviation = _tempo_metrics(score, expected, observed, alignment)

    return GuitarPerformanceScore(
        evaluator_version=evaluator_version,
        expected_note_count=expected_count,
        observed_note_count=observed_count,
        matched_note_count=len(alignment.matches),
        missed_note_count=len(alignment.deletions),
        extra_note_count=len(alignment.insertions),
        pitch_accuracy=pitch_accuracy,
        rhythm_accuracy=rhythm_accuracy,
        technique_accuracy=technique_accuracy,
        position_error_count=expected_position_count - matched_position_count,
        tempo_bpm=tempo_bpm,
        tempo_deviation_percent=tempo_deviation,
        alignment_confidence=alignment_confidence,
        overall_score=overall_score,
    )

"""One evaluator lookup, replacing a branch that had outgrown itself.

`submit_attempt` chose its scorer with a seventy-line `if instrument == "guitar"
/ elif "violin" / elif ...` chain, threading four loose locals back out for the
metric bundle. Every new instrument widened it, and every new metric added
another local. This module is that chain as two dicts and one result type.

Two properties are worth stating because they are what make it safe to add
dimensions to a scoring system that already has attempts stored against it:

**No scorer is rewritten.** Each adapter builds the observation dataclass its
own scorer already expects and calls it unchanged. The registry adds dynamics
and posture *around* that result; it never reinterprets a field.

**Weights renormalise over what is present.** Piano is declared 0.45 pitch /
0.30 rhythm / 0.15 dynamics / 0.10 posture, but an attempt that sends neither
dynamics nor posture renormalises to exactly 0.6 / 0.4 -- the number the piano
scorer produces today, unchanged to the last decimal. New dimensions therefore
bite only when the client actually measures them, and no historical attempt is
retroactively reinterpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from app.evaluation.drums import DrumHit, score_drums_performance
from app.evaluation.dynamics import DynamicsScore, score_dynamics
from app.evaluation.guitar import GuitarNote, score_guitar_chords_performance, score_guitar_performance
from app.evaluation.musicxml import MusicXMLScore
from app.evaluation.piano import PerformedNote, score_performance
from app.evaluation.posture import PostureScore
from app.evaluation.trumpet import score_trumpet_performance
from app.evaluation.violin import ViolinNote, score_violin_performance

__all__ = [
    "INSTRUMENT_WEIGHTS",
    "EvaluationResult",
    "ObservationIn",
    "ScoreWeights",
    "combine",
    "evaluate",
]


@dataclass(frozen=True, slots=True)
class ObservationIn:
    """One observed event, in the union of every instrument's needs.

    A single shape rather than five keeps the router in `performance_service`
    free of instrument knowledge; each adapter narrows it to what its scorer
    reads and ignores the rest.
    """

    pitch_midi: float | None = None
    onset_seconds: float = 0.0
    duration_seconds: float = 0.0
    confidence: float = 1.0
    string: int | None = None
    fret: int | None = None
    cents_deviation: float | None = None
    drum: str | None = None
    level_db: float | None = None


@dataclass(frozen=True, slots=True)
# @spec EVAL-WEIGHT-004, EVAL-VER-001
class EvaluationResult:
    """Every field a `performance_metric_bundles` row needs, from any instrument."""

    evaluator_version: str
    expected_note_count: int
    observed_note_count: int
    matched_note_count: int
    missed_note_count: int
    extra_note_count: int
    pitch_accuracy: float | None
    rhythm_accuracy: float
    technique_accuracy: float | None
    position_error_count: int
    intonation_accuracy: float | None
    intonation_deviation_cents: float | None
    dynamics_accuracy: float | None
    dynamic_range_db: float | None
    dynamics_contrast: float | None
    posture_accuracy: float | None
    posture_version: str | None
    tempo_bpm: float | None
    tempo_deviation_percent: float | None
    alignment_confidence: float
    overall_score: float
    low_confidence: bool


@dataclass(frozen=True, slots=True)
# @spec EVAL-WEIGHT-005
class ScoreWeights:
    pitch: float = 0.0
    rhythm: float = 0.0
    technique: float = 0.0
    intonation: float = 0.0
    dynamics: float = 0.0
    posture: float = 0.0


INSTRUMENT_WEIGHTS: dict[str, ScoreWeights] = {
    "piano": ScoreWeights(pitch=0.45, rhythm=0.30, dynamics=0.15, posture=0.10),
    "guitar": ScoreWeights(pitch=0.40, rhythm=0.25, technique=0.20, dynamics=0.05, posture=0.10),
    "violin": ScoreWeights(pitch=0.35, rhythm=0.25, intonation=0.20, dynamics=0.10, posture=0.10),
    "trumpet": ScoreWeights(pitch=0.45, rhythm=0.30, dynamics=0.15, posture=0.10),
    "drums": ScoreWeights(rhythm=0.70, dynamics=0.15, posture=0.15),
    # A banjo is a fretted, strummed string instrument: it is scored the way a
    # guitar is, because the thing being measured -- pitch set, strum timing,
    # fret position -- is the same thing.
    "banjo": ScoreWeights(pitch=0.40, rhythm=0.25, technique=0.20, dynamics=0.05, posture=0.10),
}


# @spec EVAL-WEIGHT-001, EVAL-WEIGHT-002, EVAL-WEIGHT-003
def combine(components: Mapping[str, float | None], weights: ScoreWeights) -> float | None:
    """Weighted mean over the components that were actually measured.

    A missing component's weight is redistributed across the rest rather than
    counted as zero. That is the whole reason this is safe to introduce: with
    dynamics and posture absent, the remaining weights renormalise back to the
    ratios the instrument's scorer already used.
    """
    declared = {
        "pitch": weights.pitch,
        "rhythm": weights.rhythm,
        "technique": weights.technique,
        "intonation": weights.intonation,
        "dynamics": weights.dynamics,
        "posture": weights.posture,
    }
    present = {
        name: (components[name], weight)
        for name, weight in declared.items()
        if weight > 0 and components.get(name) is not None
    }
    total_weight = sum(weight for _, weight in present.values())
    if total_weight <= 0:
        return None
    return sum(float(value) * weight for value, weight in present.values()) / total_weight


def _dynamics_for(
    score: MusicXMLScore,
    observations: Sequence[ObservationIn],
) -> DynamicsScore:
    """Pair each written note's level with the level the learner played it at.

    Positional pairing against the score's own note order is deliberate: the
    alignment the DTW scorer produced is about *which* note was played, and
    reusing it here would make a dynamics score depend on a pitch score. If the
    take has a different number of notes, the surplus on either side simply has
    no counterpart and drops out.
    """
    written = [note for note in score.notes if note.pitch_midi is not None or note.unpitched_step is not None]
    expected: list[float | None] = []
    observed: list[float | None] = []
    for index, note in enumerate(written):
        expected.append(score.expected_level_at(note.onset_beats))
        observed.append(observations[index].level_db if index < len(observations) else None)
    return score_dynamics(expected, observed)


def _piano_notes(observations: Sequence[ObservationIn]) -> list[PerformedNote]:
    return [
        PerformedNote(
            pitch_midi=observation.pitch_midi,
            onset_seconds=observation.onset_seconds,
            duration_seconds=observation.duration_seconds,
            confidence=observation.confidence,
        )
        for observation in observations
    ]


def _require_pitches(observations: Sequence[ObservationIn], instrument: str) -> None:
    for observation in observations:
        if observation.pitch_midi is None:
            raise ValueError(f"{instrument} observations require a pitch for every note.")


# (fields for the bundle, the components that feed weighting, the scorer's own
# overall score -- carried through untouched when nothing new was measured).
Evaluator = Callable[
    [MusicXMLScore, Sequence[ObservationIn], str],
    tuple[dict[str, object], dict[str, float | None], float],
]


def _evaluate_piano(score: MusicXMLScore, observations: Sequence[ObservationIn], version: str):
    _require_pitches(observations, "piano")
    result = score_performance(score, _piano_notes(observations), evaluator_version=version)
    return (
        _base_fields(result, technique_accuracy=None, position_error_count=0),
        {"pitch": result.pitch_accuracy, "rhythm": result.rhythm_accuracy},
        result.overall_score,
    )


def _evaluate_trumpet(score: MusicXMLScore, observations: Sequence[ObservationIn], version: str):
    _require_pitches(observations, "trumpet")
    result = score_trumpet_performance(score, _piano_notes(observations), evaluator_version=version)
    return (
        _base_fields(result, technique_accuracy=None, position_error_count=0),
        {"pitch": result.pitch_accuracy, "rhythm": result.rhythm_accuracy},
        result.overall_score,
    )


def _evaluate_guitar(score: MusicXMLScore, observations: Sequence[ObservationIn], version: str):
    _require_pitches(observations, "guitar")
    notes = [
        GuitarNote(
            pitch_midi=observation.pitch_midi,
            onset_seconds=observation.onset_seconds,
            duration_seconds=observation.duration_seconds,
            confidence=observation.confidence,
            string=observation.string,
            fret=observation.fret,
        )
        for observation in observations
    ]
    result = score_guitar_performance(score, notes, evaluator_version=version)
    return (
        _base_fields(
            result,
            technique_accuracy=result.technique_accuracy,
            position_error_count=result.position_error_count,
        ),
        {
            "pitch": result.pitch_accuracy,
            "rhythm": result.rhythm_accuracy,
            "technique": result.technique_accuracy,
        },
        result.overall_score,
    )


def _evaluate_guitar_chords(score: MusicXMLScore, observations: Sequence[ObservationIn], version: str):
    _require_pitches(observations, "guitar")
    notes = [
        GuitarNote(
            pitch_midi=observation.pitch_midi,
            onset_seconds=observation.onset_seconds,
            duration_seconds=observation.duration_seconds,
            confidence=observation.confidence,
            string=observation.string,
            fret=observation.fret,
        )
        for observation in observations
    ]
    result = score_guitar_chords_performance(score, notes, evaluator_version=version)
    return (
        _base_fields(
            result,
            technique_accuracy=result.technique_accuracy,
            position_error_count=result.position_error_count,
        ),
        {
            "pitch": result.pitch_accuracy,
            "rhythm": result.rhythm_accuracy,
            "technique": result.technique_accuracy,
        },
        result.overall_score,
    )


def _evaluate_violin(score: MusicXMLScore, observations: Sequence[ObservationIn], version: str):
    _require_pitches(observations, "violin")
    notes = [
        ViolinNote(
            pitch_midi=observation.pitch_midi,
            onset_seconds=observation.onset_seconds,
            duration_seconds=observation.duration_seconds,
            confidence=observation.confidence,
            cents_deviation=observation.cents_deviation,
        )
        for observation in observations
    ]
    result = score_violin_performance(score, notes, evaluator_version=version)
    fields = _base_fields(result, technique_accuracy=None, position_error_count=0)
    fields["intonation_accuracy"] = result.intonation_accuracy
    fields["intonation_deviation_cents"] = result.intonation_deviation_cents
    return (
        fields,
        {
            "pitch": result.pitch_accuracy,
            "rhythm": result.rhythm_accuracy,
            "intonation": result.intonation_accuracy,
        },
        result.overall_score,
    )


def _evaluate_drums(score: MusicXMLScore, observations: Sequence[ObservationIn], version: str):
    hits = [
        DrumHit(
            onset_seconds=observation.onset_seconds,
            duration_seconds=observation.duration_seconds,
            confidence=observation.confidence,
            drum=observation.drum,
        )
        for observation in observations
    ]
    result = score_drums_performance(score, hits, evaluator_version=version)
    return (
        _base_fields(result, technique_accuracy=None, position_error_count=0),
        {"rhythm": result.rhythm_accuracy},
        result.overall_score,
    )


def _base_fields(result: object, *, technique_accuracy: float | None, position_error_count: int) -> dict[str, object]:
    return {
        "evaluator_version": result.evaluator_version,  # type: ignore[attr-defined]
        "expected_note_count": result.expected_note_count,  # type: ignore[attr-defined]
        "observed_note_count": result.observed_note_count,  # type: ignore[attr-defined]
        "matched_note_count": result.matched_note_count,  # type: ignore[attr-defined]
        "missed_note_count": result.missed_note_count,  # type: ignore[attr-defined]
        "extra_note_count": result.extra_note_count,  # type: ignore[attr-defined]
        "pitch_accuracy": result.pitch_accuracy,  # type: ignore[attr-defined]
        "rhythm_accuracy": result.rhythm_accuracy,  # type: ignore[attr-defined]
        "technique_accuracy": technique_accuracy,
        "position_error_count": position_error_count,
        "intonation_accuracy": None,
        "intonation_deviation_cents": None,
        "tempo_bpm": result.tempo_bpm,  # type: ignore[attr-defined]
        "tempo_deviation_percent": result.tempo_deviation_percent,  # type: ignore[attr-defined]
        "alignment_confidence": result.alignment_confidence,  # type: ignore[attr-defined]
        "low_confidence": result.low_confidence,  # type: ignore[attr-defined]
    }


# `evaluator_version` wins over `instrument`, so one instrument can carry several
# scorers -- which is exactly what guitar single-note versus open-chord needs.
EVALUATORS_BY_VERSION: dict[str, Evaluator] = {
    "guitar-chords-v1": _evaluate_guitar_chords,
}
EVALUATORS_BY_INSTRUMENT: dict[str, Evaluator] = {
    "piano": _evaluate_piano,
    "guitar": _evaluate_guitar,
    "banjo": _evaluate_guitar,
    "violin": _evaluate_violin,
    "trumpet": _evaluate_trumpet,
    "drums": _evaluate_drums,
}
DEFAULT_EVALUATOR: Evaluator = _evaluate_piano


def evaluate(
    instrument: str,
    evaluator_version: str,
    score: MusicXMLScore,
    observations: Sequence[ObservationIn],
    *,
    posture: PostureScore | None = None,
) -> EvaluationResult:
    """Score one take, whatever instrument it is.

    When the take carries no dynamics and no posture, the overall score is the
    instrument scorer's own number, untouched -- not a recomputation that
    happens to agree. That is the property that lets new dimensions ship against
    a table of stored attempts without reinterpreting any of them.
    """
    evaluator = EVALUATORS_BY_VERSION.get(evaluator_version) or EVALUATORS_BY_INSTRUMENT.get(
        instrument, DEFAULT_EVALUATOR
    )
    fields, components, scorer_overall = evaluator(score, observations, evaluator_version)
    weights = INSTRUMENT_WEIGHTS.get(instrument, INSTRUMENT_WEIGHTS["piano"])

    dynamics = _dynamics_for(score, observations)
    fields["dynamics_accuracy"] = dynamics.dynamics_accuracy
    fields["dynamic_range_db"] = dynamics.dynamic_range_db
    fields["dynamics_contrast"] = dynamics.dynamics_contrast
    fields["posture_accuracy"] = posture.posture_accuracy if posture is not None else None
    fields["posture_version"] = posture.posture_version if posture is not None else None

    posture_accuracy = posture.posture_accuracy if posture is not None else None
    if dynamics.dynamics_accuracy is None and posture_accuracy is None:
        overall = scorer_overall
    else:
        # Rescale by the ratio the scorer itself applied. The per-instrument
        # scorers multiply an extra-note penalty into their overall score, and a
        # fresh weighted mean over the components alone would silently drop it.
        baseline = combine(components, weights)
        enriched = combine({**components, "dynamics": dynamics.dynamics_accuracy, "posture": posture_accuracy},
                           weights)
        if baseline is None or enriched is None or baseline <= 0:
            overall = scorer_overall
        else:
            overall = enriched * (scorer_overall / baseline)

    return EvaluationResult(overall_score=round(max(0.0, min(1.0, overall)), 4), **fields)  # type: ignore[arg-type]

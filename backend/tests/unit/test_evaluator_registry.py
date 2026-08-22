"""The registry must be a refactor, not a rescoring.

Every attempt already stored was graded by the per-instrument scorers directly.
If routing through the registry changes any number when the client sends what it
has always sent, then shipping it silently reinterprets that history. So the
central test here is an equality, not a tolerance: registry result == direct
scorer result, field for field, for every instrument.
"""

from __future__ import annotations

import pytest

from app.evaluation.drums import DrumHit, score_drums_performance
from app.evaluation.guitar import GuitarNote, score_guitar_chords_performance, score_guitar_performance
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.piano import PerformedNote, score_performance
from app.evaluation.posture import PostureMetric, PostureScore, score_posture
from app.evaluation.reference_scores import (
    DRUMS_ROCK_GROOVE_XML,
    GUITAR_GCD_STRUM_XML,
    GUITAR_LOW_E_FRETTING_XML,
    PIANO_STEPWISE_SCORE_XML,
    TRUMPET_C_ARPEGGIO_XML,
    VIOLIN_OPEN_STRINGS_XML,
)
from app.evaluation.registry import (
    INSTRUMENT_WEIGHTS,
    ObservationIn,
    ScoreWeights,
    combine,
    evaluate,
)
from app.evaluation.trumpet import score_trumpet_performance
from app.evaluation.violin import ViolinNote, score_violin_performance

CASES = {
    "piano": (PIANO_STEPWISE_SCORE_XML, "piano-dtw-v1"),
    "guitar": (GUITAR_LOW_E_FRETTING_XML, "guitar-dtw-v1"),
    "guitar-chords": (GUITAR_GCD_STRUM_XML, "guitar-chords-v1"),
    "violin": (VIOLIN_OPEN_STRINGS_XML, "violin-dtw-v1"),
    "trumpet": (TRUMPET_C_ARPEGGIO_XML, "trumpet-dtw-v1"),
    "drums": (DRUMS_ROCK_GROOVE_XML, "drums-rhythm-v1"),
}


def _observations(xml: str) -> list[ObservationIn]:
    """A perfect take of the given score, with no dynamics and no posture."""
    score = parse_musicxml(xml)
    seconds_per_beat = 60.0 / score.tempo_bpm
    from app.evaluation.drums import EXPECTED_DRUM_BY_POSITION

    observations = []
    for note in score.notes:
        if note.pitch_midi is None and note.unpitched_step is None:
            pass
        else:
            observations.append(
                ObservationIn(
                    pitch_midi=note.pitch_midi,
                    onset_seconds=note.onset_beats * seconds_per_beat,
                    duration_seconds=note.duration_beats * seconds_per_beat,
                    confidence=1.0,
                    string=note.string,
                    fret=note.fret,
                    cents_deviation=0.0 if note.pitch_midi is not None else None,
                    drum=EXPECTED_DRUM_BY_POSITION.get((note.unpitched_step or "", note.unpitched_octave or 0)),
                )
            )
    return observations


@pytest.mark.parametrize("case", sorted(CASES))
def test_registry_reproduces_the_direct_scorer(case: str) -> None:
    xml, version = CASES[case]
    instrument = "guitar" if case.startswith("guitar") else case
    score = parse_musicxml(xml)
    observations = _observations(xml)

    result = evaluate(instrument, version, score, observations)

    if case == "drums":
        direct = score_drums_performance(
            score,
            [DrumHit(onset_seconds=o.onset_seconds, duration_seconds=o.duration_seconds,
                     confidence=o.confidence, drum=o.drum) for o in observations],
            evaluator_version=version,
        )
    elif case == "guitar":
        direct = score_guitar_performance(
            score,
            [GuitarNote(pitch_midi=o.pitch_midi, onset_seconds=o.onset_seconds,
                        duration_seconds=o.duration_seconds, confidence=o.confidence,
                        string=o.string, fret=o.fret) for o in observations],
            evaluator_version=version,
        )
    elif case == "guitar-chords":
        direct = score_guitar_chords_performance(
            score,
            [GuitarNote(pitch_midi=o.pitch_midi, onset_seconds=o.onset_seconds,
                        duration_seconds=o.duration_seconds, confidence=o.confidence,
                        string=o.string, fret=o.fret) for o in observations],
            evaluator_version=version,
        )
    elif case == "violin":
        direct = score_violin_performance(
            score,
            [ViolinNote(pitch_midi=o.pitch_midi, onset_seconds=o.onset_seconds,
                        duration_seconds=o.duration_seconds, confidence=o.confidence,
                        cents_deviation=o.cents_deviation) for o in observations],
            evaluator_version=version,
        )
    else:
        performed = [
            PerformedNote(pitch_midi=o.pitch_midi, onset_seconds=o.onset_seconds,
                          duration_seconds=o.duration_seconds, confidence=o.confidence)
            for o in observations
        ]
        direct = (
            score_trumpet_performance(score, performed, evaluator_version=version)
            if case == "trumpet"
            else score_performance(score, performed, evaluator_version=version)
        )

    assert result.overall_score == direct.overall_score
    assert result.pitch_accuracy == direct.pitch_accuracy
    assert result.rhythm_accuracy == direct.rhythm_accuracy
    assert result.expected_note_count == direct.expected_note_count
    assert result.observed_note_count == direct.observed_note_count
    assert result.matched_note_count == direct.matched_note_count
    assert result.missed_note_count == direct.missed_note_count
    assert result.extra_note_count == direct.extra_note_count
    assert result.alignment_confidence == direct.alignment_confidence
    assert result.low_confidence == direct.low_confidence
    # Nothing measured means nothing claimed.
    assert result.dynamics_accuracy is None
    assert result.posture_accuracy is None
    assert result.posture_version is None


def test_evaluator_version_beats_instrument_routing() -> None:
    """`guitar-chords-v1` must not be graded as a monophonic guitar line."""
    xml, _ = CASES["guitar-chords"]
    score = parse_musicxml(xml)
    observations = _observations(xml)
    chords = evaluate("guitar", "guitar-chords-v1", score, observations)
    single = evaluate("guitar", "guitar-dtw-v1", score, observations)
    # A perfect take scores 1.0 under either scorer, so the score cannot tell
    # them apart. The counts can: the chord scorer sees four strum events where
    # the monophonic scorer sees twenty-one separate notes.
    assert chords.expected_note_count < single.expected_note_count
    assert chords.evaluator_version == "guitar-chords-v1"


def test_an_unknown_instrument_falls_back_to_piano() -> None:
    xml, _ = CASES["piano"]
    score = parse_musicxml(xml)
    observations = _observations(xml)
    assert evaluate("kazoo", "kazoo-v1", score, observations).overall_score == pytest.approx(
        evaluate("piano", "kazoo-v1", score, observations).overall_score
    )


class TestWeighting:
    def test_absent_components_renormalise_to_todays_ratio(self) -> None:
        """Piano without dynamics or posture must be exactly 0.6 pitch / 0.4 rhythm."""
        weights = INSTRUMENT_WEIGHTS["piano"]
        combined = combine({"pitch": 1.0, "rhythm": 0.0}, weights)
        assert combined == pytest.approx(0.45 / 0.75)
        assert combined == pytest.approx(0.6)

    def test_a_present_component_shifts_the_score(self) -> None:
        weights = INSTRUMENT_WEIGHTS["piano"]
        without = combine({"pitch": 1.0, "rhythm": 1.0}, weights)
        with_posture = combine({"pitch": 1.0, "rhythm": 1.0, "posture": 0.0}, weights)
        assert without == pytest.approx(1.0)
        assert with_posture < without

    def test_no_measurable_component_is_none_not_zero(self) -> None:
        assert combine({"pitch": None, "rhythm": None}, ScoreWeights(pitch=0.5, rhythm=0.5)) is None

    def test_posture_lowers_an_otherwise_perfect_take(self) -> None:
        xml, version = CASES["piano"]
        score = parse_musicxml(xml)
        observations = _observations(xml)
        clean = evaluate("piano", version, score, observations)
        slouched = evaluate(
            "piano", version, score, observations,
            posture=PostureScore(posture_accuracy=0.0, posture_version="posture-v1",
                                 measured_metric_count=2, low_confidence=False),
        )
        assert slouched.overall_score < clean.overall_score
        assert slouched.posture_accuracy == 0.0
        assert slouched.posture_version == "posture-v1"


class TestPostureReduction:
    def test_unmeasurable_posture_is_none(self) -> None:
        metrics = [
            PostureMetric(key="torso_lean", value=0.0, confidence=0.0, status="not_detected"),
            PostureMetric(key="shoulder_level", value=0.4, confidence=0.2, status="low_confidence"),
        ]
        result = score_posture(metrics, version="posture-v1")
        assert result.posture_accuracy is None
        assert result.low_confidence is True
        assert result.measured_metric_count == 0

    def test_confidence_weights_the_mean(self) -> None:
        metrics = [
            PostureMetric(key="torso_lean", value=1.0, confidence=1.0, status="good"),
            PostureMetric(key="shoulder_level", value=0.0, confidence=1.0, status="needs_attention"),
        ]
        assert score_posture(metrics, version="posture-v1").posture_accuracy == pytest.approx(0.5)

    def test_an_uncounted_metric_does_not_drag_the_score_down(self) -> None:
        """A camera that cannot see the hips must not read as bad posture."""
        seen_only = [PostureMetric(key="shoulder_level", value=0.9, confidence=1.0, status="good")]
        with_blind_spot = seen_only + [
            PostureMetric(key="torso_lean", value=0.0, confidence=0.0, status="not_detected")
        ]
        assert score_posture(seen_only, version="v1").posture_accuracy == pytest.approx(
            score_posture(with_blind_spot, version="v1").posture_accuracy
        )

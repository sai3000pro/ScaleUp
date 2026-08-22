"""Piano scoring is deterministic once audio has become note observations."""

from __future__ import annotations

import pytest

from app.evaluation.musicxml import parse_musicxml
from app.evaluation.piano import PerformedNote, score_performance
from app.evaluation.reference_scores import PIANO_STEPWISE_SCORE_XML
from tests.unit.test_musicxml import SCORE


def test_seeded_stepwise_score_has_a_perfect_fixture_path() -> None:
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    seconds_per_beat = 60.0 / score.tempo_bpm
    result = score_performance(
        score,
        [
            PerformedNote(60, 0.0),
            PerformedNote(62, seconds_per_beat),
            PerformedNote(64, 2 * seconds_per_beat),
            PerformedNote(65, 3 * seconds_per_beat),
        ],
    )

    assert result.overall_score == 1.0
    assert result.low_confidence is False


def test_perfect_piano_performance_scores_one() -> None:
    score = parse_musicxml(SCORE)
    observed = [
        PerformedNote(60, 0.0),
        PerformedNote(62, 0.5),
        PerformedNote(64, 1.5),
        PerformedNote(56, 2.0),
    ]

    result = score_performance(score, observed)

    assert result.evaluator_version == "piano-dtw-v1"
    assert result.expected_note_count == 4
    assert result.observed_note_count == 4
    assert result.matched_note_count == 4
    assert result.missed_note_count == 0
    assert result.extra_note_count == 0
    assert result.pitch_accuracy == 1.0
    assert result.rhythm_accuracy == 1.0
    assert result.tempo_bpm == 120.0
    assert result.tempo_deviation_percent == 0.0
    assert result.alignment_confidence == 1.0
    assert result.overall_score == 1.0
    assert result.low_confidence is False


def test_wrong_pitch_and_timing_reduce_metrics_but_remain_explainable() -> None:
    score = parse_musicxml(SCORE)
    observed = [
        PerformedNote(60, 0.0),
        PerformedNote(63, 0.7),
        PerformedNote(64, 1.8),
        PerformedNote(56, 2.4),
    ]

    result = score_performance(score, observed)

    assert result.matched_note_count == 4
    assert result.missed_note_count == 0
    assert result.extra_note_count == 0
    assert 0 < result.pitch_accuracy < 1
    assert 0 < result.rhythm_accuracy < 1
    assert result.tempo_bpm is not None
    assert result.tempo_deviation_percent is not None
    assert result.overall_score < 1


def test_silence_is_low_confidence_and_never_scores_as_a_pass() -> None:
    score = parse_musicxml(SCORE)

    result = score_performance(score, [])

    assert result.observed_note_count == 0
    assert result.missed_note_count == result.expected_note_count
    assert result.extra_note_count == 0
    assert result.overall_score == 0.0
    assert result.alignment_confidence == 0.0
    assert result.low_confidence is True


def test_missing_and_extra_notes_are_reported() -> None:
    score = parse_musicxml(SCORE)
    missing = score_performance(
        score,
        [PerformedNote(60, 0.0), PerformedNote(62, 0.5), PerformedNote(64, 1.5)],
    )
    extra = score_performance(
        score,
        [
            PerformedNote(60, 0.0),
            PerformedNote(62, 0.5),
            PerformedNote(64, 1.5),
            PerformedNote(56, 2.0),
            PerformedNote(60, 2.5),
        ],
    )

    assert missing.missed_note_count >= 1
    assert missing.overall_score < 1
    assert extra.extra_note_count >= 1
    assert extra.overall_score < 1


def test_performed_note_rejects_invalid_observations() -> None:
    with pytest.raises(ValueError, match="pitch"):
        PerformedNote(128, 0.0)
    with pytest.raises(ValueError, match="onset"):
        PerformedNote(60, -0.1)
    with pytest.raises(ValueError, match="confidence"):
        PerformedNote(60, 0.0, confidence=2.0)

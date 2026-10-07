"""Piano scoring is deterministic once audio has become note observations."""

from __future__ import annotations

import pytest

from app.evaluation.musicxml import parse_musicxml
from app.evaluation.piano import PerformedNote, score_performance
from app.evaluation.quality_budget import (
    MAX_SCORING_PAYLOAD_BYTES,
    measure_scoring_ms,
    scoring_latency_exceeded,
)
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


def test_extra_notes_after_a_short_phrase_do_not_expand_the_expected_score() -> None:
    score = parse_musicxml(SCORE)
    observed = [
        PerformedNote(60, 0.0),
        PerformedNote(62, 0.5),
        PerformedNote(64, 1.5),
        PerformedNote(56, 2.0),
        PerformedNote(60, 2.5),
        PerformedNote(62, 2.7),
        PerformedNote(64, 2.9),
        PerformedNote(65, 3.1),
    ]

    result = score_performance(score, observed)

    assert result.expected_note_count == 4
    assert result.extra_note_count >= 4
    assert result.overall_score < 1.0


def test_a_full_duration_second_phrase_can_be_aligned_as_a_repeat() -> None:
    score = parse_musicxml(SCORE)
    observed = [
        PerformedNote(60, 0.0),
        PerformedNote(62, 0.5),
        PerformedNote(64, 1.5),
        PerformedNote(56, 2.0),
        PerformedNote(60, 4.0),
        PerformedNote(62, 4.5),
        PerformedNote(64, 5.5),
        PerformedNote(56, 6.0),
    ]

    result = score_performance(score, observed)

    assert result.expected_note_count == 8
    assert result.extra_note_count == 0
    assert result.overall_score == 1.0


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


def test_golden_evaluator_fixtures_meet_the_demo_latency_and_payload_budgets() -> None:
    score = parse_musicxml(SCORE)
    observations = [
        PerformedNote(60, 0.0),
        PerformedNote(62, 0.5),
        PerformedNote(64, 1.5),
        PerformedNote(56, 2.0),
    ]

    result, elapsed_ms = measure_scoring_ms(lambda: score_performance(score, observations))
    payload_bytes = len(
        (
            '{"observed_notes":['
            + ",".join(
                f'{{"pitch_midi":{note.pitch_midi},"onset_seconds":{note.onset_seconds},'
                f'"duration_seconds":{note.duration_seconds},"confidence":{note.confidence}}}'
                for note in observations
            )
            + '],"posture":null,"recording_id":null,"analyzer":"quality-fixture"}'
        ).encode("utf-8")
    )

    assert result.overall_score == 1.0
    assert scoring_latency_exceeded(elapsed_ms) is False
    assert payload_bytes <= MAX_SCORING_PAYLOAD_BYTES


def test_performed_note_rejects_invalid_observations() -> None:
    with pytest.raises(ValueError, match="pitch"):
        PerformedNote(128, 0.0)
    with pytest.raises(ValueError, match="onset"):
        PerformedNote(60, -0.1)
    with pytest.raises(ValueError, match="confidence"):
        PerformedNote(60, 0.0, confidence=2.0)

"""Violin, trumpet, and drums scoring stays deterministic and instrument-honest.

Violin adds intonation from per-note cents deviation; trumpet reuses the shared
monophonic core; drums score rhythm and drum identity with pitch inapplicable.
"""

from __future__ import annotations

import pytest

from app.evaluation.drums import DrumHit, score_drums_performance
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.piano import PerformedNote
from app.evaluation.reference_scores import (
    DRUMS_ROCK_GROOVE_XML,
    TRUMPET_C_ARPEGGIO_XML,
    VIOLIN_OPEN_STRINGS_XML,
)
from app.evaluation.trumpet import score_trumpet_performance
from app.evaluation.violin import ViolinNote, score_violin_performance

# ── violin ──────────────────────────────────────────────────────────────

def test_violin_perfect_open_strings_score_one_without_intonation() -> None:
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)
    spb = 60.0 / score.tempo_bpm
    result = score_violin_performance(
        score,
        [
            ViolinNote(55, 0.0),
            ViolinNote(62, 1 * spb),
            ViolinNote(69, 2 * spb),
            ViolinNote(76, 3 * spb),
        ],
    )

    assert result.evaluator_version == "violin-dtw-v1"
    assert result.overall_score == 1.0
    assert result.intonation_accuracy is None  # no cents reported -> no claim
    assert result.intonation_deviation_cents is None
    assert result.low_confidence is False


def test_violin_intonation_is_measured_from_cents_deviation() -> None:
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)
    spb = 60.0 / score.tempo_bpm
    result = score_violin_performance(
        score,
        [
            ViolinNote(55, 0.0, cents_deviation=5.0),
            ViolinNote(62, 1 * spb, cents_deviation=-10.0),
            ViolinNote(69, 2 * spb, cents_deviation=25.0),
            ViolinNote(76, 3 * spb, cents_deviation=-60.0),
        ],
    )

    assert result.intonation_accuracy is not None
    assert result.intonation_deviation_cents is not None
    # 5 -> 0.833, 10 -> 0.667, 25 -> 0.167, 60 -> 0.0; mean ~0.417
    assert 0.3 < result.intonation_accuracy < 0.5
    assert result.intonation_deviation_cents == pytest.approx(25.0)
    assert result.overall_score < 1


def test_violin_intonation_degrades_overall_score() -> None:
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)
    spb = 60.0 / score.tempo_bpm
    centred = score_violin_performance(
        score,
        [ViolinNote(55, 0.0), ViolinNote(62, 1 * spb), ViolinNote(69, 2 * spb), ViolinNote(76, 3 * spb)],
    )
    sharp = score_violin_performance(
        score,
        [
            ViolinNote(55, 0.0, cents_deviation=45.0),
            ViolinNote(62, 1 * spb, cents_deviation=45.0),
            ViolinNote(69, 2 * spb, cents_deviation=45.0),
            ViolinNote(76, 3 * spb, cents_deviation=45.0),
        ],
    )

    assert centred.overall_score == 1.0
    assert sharp.intonation_accuracy == 0.0
    assert sharp.overall_score < centred.overall_score


def test_violin_note_rejects_invalid_observations() -> None:
    with pytest.raises(ValueError, match="pitch"):
        ViolinNote(128, 0.0)
    with pytest.raises(ValueError, match="cents"):
        ViolinNote(55, 0.0, cents_deviation=float("nan"))


# ── trumpet ─────────────────────────────────────────────────────────────

def test_trumpet_perfect_arpeggio_scores_one() -> None:
    score = parse_musicxml(TRUMPET_C_ARPEGGIO_XML)
    spb = 60.0 / score.tempo_bpm
    result = score_trumpet_performance(
        score,
        [
            PerformedNote(60, 0.0),
            PerformedNote(64, 1 * spb),
            PerformedNote(67, 2 * spb),
            PerformedNote(72, 3 * spb),
        ],
    )

    assert result.evaluator_version == "trumpet-dtw-v1"
    assert result.overall_score == 1.0
    assert result.pitch_accuracy == 1.0
    assert result.rhythm_accuracy == 1.0
    assert result.low_confidence is False


def test_trumpet_wrong_pitch_lowers_the_score() -> None:
    score = parse_musicxml(TRUMPET_C_ARPEGGIO_XML)
    spb = 60.0 / score.tempo_bpm
    result = score_trumpet_performance(
        score,
        [
            PerformedNote(60, 0.0),
            PerformedNote(65, 1 * spb),  # F natural instead of E
            PerformedNote(67, 2 * spb),
            PerformedNote(72, 3 * spb),
        ],
    )

    assert result.overall_score < 1
    assert result.pitch_accuracy < 1


# ── drums ───────────────────────────────────────────────────────────────

def test_drums_rock_groove_expected_events_are_rhythmic() -> None:
    score = parse_musicxml(DRUMS_ROCK_GROOVE_XML)
    assert score.pitched_notes == ()  # no pitch anywhere in the fixture
    spb = 60.0 / score.tempo_bpm / 2

    result = score_drums_performance(
        score,
        [
            DrumHit(0 * spb, drum="kick"),
            DrumHit(1 * spb, drum="hihat"),
            DrumHit(2 * spb, drum="snare"),
            DrumHit(3 * spb, drum="hihat"),
            DrumHit(4 * spb, drum="kick"),
            DrumHit(5 * spb, drum="hihat"),
            DrumHit(6 * spb, drum="snare"),
            DrumHit(7 * spb, drum="hihat"),
        ],
    )

    assert result.evaluator_version == "drums-rhythm-v1"
    assert result.expected_note_count == 8
    assert result.pitch_accuracy is None
    assert result.overall_score == 1.0
    assert result.low_confidence is False


def test_drums_wrong_drum_identity_is_penalised() -> None:
    score = parse_musicxml(DRUMS_ROCK_GROOVE_XML)
    spb = 60.0 / score.tempo_bpm / 2
    wrong_drum = score_drums_performance(
        score,
        [
            DrumHit(0 * spb, drum="kick"),
            DrumHit(1 * spb, drum="hihat"),
            DrumHit(2 * spb, drum="hihat"),  # should be snare
            DrumHit(3 * spb, drum="hihat"),
            DrumHit(4 * spb, drum="kick"),
            DrumHit(5 * spb, drum="hihat"),
            DrumHit(6 * spb, drum="snare"),
            DrumHit(7 * spb, drum="hihat"),
        ],
    )
    no_identity = score_drums_performance(
        score,
        [
            DrumHit(0 * spb),
            DrumHit(1 * spb),
            DrumHit(2 * spb),
            DrumHit(3 * spb),
            DrumHit(4 * spb),
            DrumHit(5 * spb),
            DrumHit(6 * spb),
            DrumHit(7 * spb),
        ],
    )

    # Unknown identity is scored leniently for rhythm only.
    assert no_identity.overall_score == 1.0
    assert wrong_drum.overall_score < 1


def test_drums_missing_and_extra_hits_are_reported() -> None:
    score = parse_musicxml(DRUMS_ROCK_GROOVE_XML)
    spb = 60.0 / score.tempo_bpm / 2
    missing = score_drums_performance(
        score,
        [
            DrumHit(0 * spb, drum="kick"),
            DrumHit(2 * spb, drum="snare"),
            DrumHit(4 * spb, drum="kick"),
            DrumHit(6 * spb, drum="snare"),
        ],
    )
    extra = score_drums_performance(
        score,
        [
            DrumHit(0 * spb, drum="kick"),
            DrumHit(0.5 * spb, drum="hihat"),
            DrumHit(1 * spb, drum="hihat"),
            DrumHit(2 * spb, drum="snare"),
            DrumHit(3 * spb, drum="hihat"),
            DrumHit(4 * spb, drum="kick"),
            DrumHit(5 * spb, drum="hihat"),
            DrumHit(6 * spb, drum="snare"),
            DrumHit(7 * spb, drum="hihat"),
        ],
    )

    assert missing.missed_note_count >= 4
    assert missing.overall_score < 1
    assert extra.extra_note_count >= 1
    assert extra.overall_score < 1


def test_drum_hit_rejects_invalid_observations() -> None:
    with pytest.raises(ValueError, match="onset"):
        DrumHit(-0.1)
    with pytest.raises(ValueError, match="drum"):
        DrumHit(0.0, drum="tambourine")
    with pytest.raises(ValueError, match="confidence"):
        DrumHit(0.0, confidence=1.5)

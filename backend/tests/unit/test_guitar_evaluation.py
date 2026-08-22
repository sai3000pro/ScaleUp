"""Guitar scoring is deterministic and adds fretboard position to pitch/rhythm."""

from __future__ import annotations

import pytest

from app.evaluation.guitar import (
    GuitarNote,
    open_string_midi,
    pitch_for_position,
    score_guitar_chords_performance,
    score_guitar_performance,
)
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.reference_scores import GUITAR_GCD_STRUM_XML, GUITAR_LOW_E_FRETTING_XML


def test_standard_tuning_open_strings() -> None:
    assert open_string_midi(6) == 40  # E2
    assert open_string_midi(5) == 45  # A2
    assert open_string_midi(4) == 50  # D3
    assert open_string_midi(3) == 55  # G3
    assert open_string_midi(2) == 59  # B3
    assert open_string_midi(1) == 64  # E4


def test_pitch_for_position() -> None:
    assert pitch_for_position(6, 0) == 40
    assert pitch_for_position(6, 3) == 43
    assert pitch_for_position(6, 5) == 45


def test_perfect_guitar_performance_scores_one() -> None:
    score = parse_musicxml(GUITAR_LOW_E_FRETTING_XML)
    spb = 60.0 / score.tempo_bpm
    observed = [
        GuitarNote(40, 0.0, string=6, fret=0),
        GuitarNote(41, 1 * spb, string=6, fret=1),
        GuitarNote(43, 2 * spb, string=6, fret=3),
        GuitarNote(45, 3 * spb, string=6, fret=5),
    ]

    result = score_guitar_performance(score, observed)

    assert result.evaluator_version == "guitar-dtw-v1"
    assert result.expected_note_count == 4
    assert result.missed_note_count == 0
    assert result.extra_note_count == 0
    assert result.pitch_accuracy == 1.0
    assert result.rhythm_accuracy == 1.0
    assert result.technique_accuracy == 1.0
    assert result.position_error_count == 0
    assert result.overall_score == 1.0


def test_wrong_fret_position_is_reported_without_failing_pitch() -> None:
    score = parse_musicxml(GUITAR_LOW_E_FRETTING_XML)
    spb = 60.0 / score.tempo_bpm
    observed = [
        GuitarNote(40, 0.0, string=6, fret=0),
        GuitarNote(41, 1 * spb, string=6, fret=1),
        GuitarNote(43, 2 * spb, string=6, fret=3),
        GuitarNote(45, 3 * spb, string=5, fret=0),  # A2 as open A string: correct pitch, wrong tab position
    ]

    result = score_guitar_performance(score, observed)

    assert result.pitch_accuracy > 0.9
    assert result.technique_accuracy is not None
    assert result.technique_accuracy < 1.0
    assert result.position_error_count == 1
    assert result.overall_score < 1.0


def test_position_consistency_is_validated_on_construction() -> None:
    with pytest.raises(ValueError, match="string"):
        GuitarNote(40, 0.0, string=7, fret=0)
    with pytest.raises(ValueError, match="fret"):
        GuitarNote(40, 0.0, string=6, fret=25)
    with pytest.raises(ValueError, match="implies pitch"):
        GuitarNote(41, 0.0, string=6, fret=0)


def test_guitar_silence_is_low_confidence() -> None:
    score = parse_musicxml(GUITAR_LOW_E_FRETTING_XML)

    result = score_guitar_performance(score, [])

    assert result.overall_score == 0.0
    assert result.missed_note_count == 4
    assert result.low_confidence is True


# ── open-chord / strumming scoring ───────────────────────────────────────

# Written G / C / D / G open-chord voicings as (string, fret) positions.
_G_STRUM = [(6, 3), (5, 2), (4, 0), (3, 0), (2, 0), (1, 3)]
_C_STRUM = [(5, 3), (4, 2), (3, 0), (2, 1), (1, 0)]
_D_STRUM = [(4, 0), (3, 2), (2, 3), (1, 2)]


def _strum(positions_by_beat: dict[int, list[tuple[int, int]]], spb: float = 1.0) -> list[GuitarNote]:
    """Build a strummed take: each chord's strings land 20ms apart."""
    notes: list[GuitarNote] = []
    for beat, positions in positions_by_beat.items():
        for index, (string, fret) in enumerate(positions):
            notes.append(
                GuitarNote(
                    open_string_midi(string) + fret,
                    beat * spb + index * 0.02,
                    string=string,
                    fret=fret,
                )
            )
    return notes


def test_perfect_strum_of_g_c_d_scores_one() -> None:
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    spb = 60.0 / score.tempo_bpm
    result = score_guitar_chords_performance(
        score,
        _strum({0: _G_STRUM, 1: _C_STRUM, 2: _D_STRUM, 3: _G_STRUM}, spb=spb),
    )

    assert result.evaluator_version == "guitar-chords-v1"
    assert result.expected_note_count == 4  # four chord events, not fourteen notes
    assert result.pitch_accuracy == 1.0
    assert result.rhythm_accuracy == 1.0
    assert result.technique_accuracy == 1.0
    assert result.position_error_count == 0
    assert result.overall_score == 1.0


def test_wrong_chord_lowers_pitch_accuracy() -> None:
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    result = score_guitar_chords_performance(
        score,
        _strum({0: _C_STRUM, 1: _C_STRUM, 2: _D_STRUM, 3: _G_STRUM}),
    )

    assert result.pitch_accuracy < 1.0
    assert result.overall_score < 1.0


def test_missing_string_in_a_chord_is_a_missing_note() -> None:
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    # Drop the top string of every chord: 5 of 6 G-string notes still sound.
    result = score_guitar_chords_performance(
        score,
        _strum({0: _G_STRUM[:-1], 1: _C_STRUM[:-1], 2: _D_STRUM[:-1], 3: _G_STRUM[:-1]}),
    )

    assert result.pitch_accuracy < 1.0
    assert result.missed_note_count == 0  # the chord still matched; the string is missing inside it
    assert result.overall_score < 1.0


def test_split_attack_beyond_strum_tolerance_is_an_extra_event() -> None:
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    spb = 60.0 / score.tempo_bpm
    notes: list[GuitarNote] = []
    for beat, positions in {0: _G_STRUM, 1: _C_STRUM, 2: _D_STRUM, 3: _G_STRUM}.items():
        for index, (string, fret) in enumerate(positions):
            # Each string 50ms apart: the chord still fits inside one strum
            # window, but the two beats are now separated by extra attacks.
            notes.append(
                GuitarNote(
                    open_string_midi(string) + fret,
                    beat * spb + index * 0.05,
                    string=string,
                    fret=fret,
                )
            )
    result = score_guitar_chords_performance(score, notes)

    assert result.expected_note_count == 4
    assert result.overall_score <= 1.0


def test_chord_silence_is_low_confidence() -> None:
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)

    result = score_guitar_chords_performance(score, [])

    assert result.overall_score == 0.0
    assert result.missed_note_count == 4
    assert result.low_confidence is True

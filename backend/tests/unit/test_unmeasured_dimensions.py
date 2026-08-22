"""An unmeasured dimension is reported as unmeasured, never as zero.

The segment's governing rule, tested where it is easiest to break: at the seam
between a wire payload that may omit a field and a scorer that has to decide
what the omission meant.

The distinction the whole file turns on is between two facts that a single
`float` cannot tell apart:

    "we measured it, and it was dead centre"   -> 0.0, counts, quality 1.0
    "we did not measure it"                    -> None, excluded, no claim

Collapsing those two produces failures in both directions. Encode "unmeasured"
as 0.0 and a perfect note is thrown out of the average. Encode "measured" as
optional and forget to check, and the scorer raises on the ordinary path.
"""

from __future__ import annotations

import re

import pytest

from app.evaluation.guitar import (
    MAX_FRET,
    MAX_STRING,
    MIN_FRET,
    MIN_STRING,
    GuitarNote,
    open_string_midi,
    score_guitar_chords_performance,
)
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.reference_scores import GUITAR_GCD_STRUM_XML, VIOLIN_OPEN_STRINGS_XML
from app.evaluation.registry import ObservationIn, evaluate
from app.evaluation.violin import ViolinNote, score_violin_performance

# The four open strings of VIOLIN_OPEN_STRINGS_XML, played exactly on time at 60 BPM.
OPEN_STRINGS = ((55, 0.0), (62, 1.0), (69, 2.0), (76, 3.0))


def _violin_notes(cents: float | None) -> list[ViolinNote]:
    return [ViolinNote(pitch, onset, cents_deviation=cents) for pitch, onset in OPEN_STRINGS]


def _violin_observations(cents: float | None) -> list[ObservationIn]:
    """A perfect take as it arrives from the wire, where cents may be absent."""
    return [
        ObservationIn(pitch_midi=pitch, onset_seconds=onset, duration_seconds=1.0, confidence=1.0,
                      cents_deviation=cents)
        for pitch, onset in OPEN_STRINGS
    ]


# ── violin: an absent cents reading is not a reading of zero ──────────────


# @spec EVAL-INST-009
def test_a_take_carrying_no_cents_scores_rather_than_raising() -> None:
    """The ordinary path today: the shipped detector reports no cents at all.

    `PerformedNoteIn.cents_deviation` is optional on the wire, so every violin
    take arrives with it unset. A scorer that cannot represent "absent" turns
    the most common violin submission into a 500.
    """
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)

    result = score_violin_performance(score, _violin_notes(None))

    assert result.intonation_accuracy is None
    assert result.intonation_deviation_cents is None
    # Intonation was not measured, so it costs nothing: this is a perfect take.
    assert result.overall_score == 1.0


# @spec EVAL-INST-009
def test_the_registry_path_survives_a_payload_that_omits_cents() -> None:
    """The crash reproduces through `evaluate`, which is what the API calls."""
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)

    result = evaluate("violin", "violin-dtw-v1", score, _violin_observations(None))

    assert result.intonation_accuracy is None
    assert result.overall_score == 1.0


# ── violin: playing in tune is a measurement, not an absence ──────────────


# @spec EVAL-INST-010
def test_a_note_played_exactly_in_tune_counts_toward_intonation() -> None:
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)

    result = score_violin_performance(score, _violin_notes(0.0))

    assert result.intonation_accuracy == 1.0
    assert result.intonation_deviation_cents == 0.0


# @spec EVAL-INST-010
def test_measured_and_centred_is_distinguishable_from_unmeasured() -> None:
    """The two cases must not collapse: one is a claim, the other is silence."""
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)

    centred = score_violin_performance(score, _violin_notes(0.0))
    unmeasured = score_violin_performance(score, _violin_notes(None))

    assert centred.intonation_accuracy == 1.0
    assert unmeasured.intonation_accuracy is None


# @spec EVAL-INST-010
def test_playing_perfectly_in_tune_does_not_change_the_rubric() -> None:
    """Intonation is worth 0.2 of a violin take, or it is not measured at all.

    It must not be worth 0.2 only while the learner is out of tune. Under a
    rule that excludes centred notes, the last note to come into tune drops
    intonation out of the score entirely and re-weights pitch and rhythm from
    0.5/0.3 to 0.6/0.4 -- so improving changes which formula grades you.
    """
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)

    slightly_flat = _violin_notes(-3.0)
    dead_centre = _violin_notes(0.0)

    flat_result = score_violin_performance(score, slightly_flat)
    centred_result = score_violin_performance(score, dead_centre)

    # Both takes were measured, so both report intonation.
    assert flat_result.intonation_accuracy is not None
    assert centred_result.intonation_accuracy is not None
    # And playing better scores better -- never worse, and never differently graded.
    assert centred_result.intonation_accuracy > flat_result.intonation_accuracy
    assert centred_result.overall_score >= flat_result.overall_score


# @spec EVAL-INST-009
def test_a_cents_reading_that_is_present_is_still_validated() -> None:
    """Optional means absent-or-valid, not unchecked."""
    with pytest.raises(ValueError, match="cents"):
        ViolinNote(55, 0.0, cents_deviation=float("nan"))


# ── guitar chords: an unmeasurable technique costs nothing ────────────────


def _strip_tablature(xml: str) -> str:
    """The same chord score, written without string and fret metadata.

    A score that never named a fingering cannot be marked down for the wrong
    one. This is how a chord chart written as plain notation arrives.
    """
    return re.sub(r"<technical>.*?</technical>", "", xml, flags=re.DOTALL)


def _chord_notes(score) -> list[GuitarNote]:
    seconds_per_beat = 60.0 / score.tempo_bpm
    return [
        GuitarNote(
            pitch_midi=note.pitch_midi,
            onset_seconds=note.onset_beats * seconds_per_beat,
            duration_seconds=note.duration_beats * seconds_per_beat,
            confidence=1.0,
            string=note.string,
            fret=note.fret,
        )
        for note in score.pitched_notes
    ]


# @spec EVAL-INST-011
def test_a_chord_score_without_tablature_reports_technique_as_unmeasured() -> None:
    score = parse_musicxml(_strip_tablature(GUITAR_GCD_STRUM_XML))

    result = score_guitar_chords_performance(score, _chord_notes(score))

    assert result.technique_accuracy is None


# @spec EVAL-INST-011
def test_an_unmeasurable_technique_does_not_cap_a_perfect_take() -> None:
    """Folding a missing dimension in as 0.0 is the one claim the segment forbids.

    Technique carries 0.2 of a chord take. Scored as zero when the notation
    never asked for a fingering, a flawless strum reads as 0.8 -- and the
    learner is told they lost a fifth of the marks for something the score did
    not contain.
    """
    score = parse_musicxml(_strip_tablature(GUITAR_GCD_STRUM_XML))

    result = score_guitar_chords_performance(score, _chord_notes(score))

    assert result.pitch_accuracy == 1.0
    assert result.rhythm_accuracy == 1.0
    assert result.overall_score == 1.0


def _elsewhere_on_the_neck(note: GuitarNote) -> GuitarNote:
    """The same pitch, fingered somewhere else.

    A guitar pitch is playable at several positions, so a wrong fingering is a
    different string and fret for the *same* sounding note -- which is the only
    shape a technique error can take. `GuitarNote` refuses a position that
    contradicts its own pitch, so the alternative has to be a real one.
    """
    if note.string is None or note.fret is None:
        return note
    pitch = int(round(note.pitch_midi))
    for string in range(MIN_STRING, MAX_STRING + 1):
        fret = pitch - open_string_midi(string)
        if string != note.string and MIN_FRET <= fret <= MAX_FRET:
            return GuitarNote(
                pitch_midi=note.pitch_midi,
                onset_seconds=note.onset_seconds,
                duration_seconds=note.duration_seconds,
                confidence=note.confidence,
                string=string,
                fret=fret,
            )
    return note


# @spec EVAL-INST-011
def test_a_measured_technique_still_counts_against_the_take() -> None:
    """Redistribution is for the unmeasured case only, never a way to lose a penalty."""
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    notes = _chord_notes(score)
    misfingered = [_elsewhere_on_the_neck(note) for note in notes]

    clean = score_guitar_chords_performance(score, notes)
    wrong = score_guitar_chords_performance(score, misfingered)

    assert clean.technique_accuracy == 1.0
    assert wrong.technique_accuracy is not None
    assert wrong.technique_accuracy < clean.technique_accuracy
    assert wrong.overall_score < clean.overall_score

"""Examiner feedback is deterministic and grounded in the metric bundle."""

from __future__ import annotations

from app.evaluation.drums import DrumHit, score_drums_performance
from app.evaluation.feedback import PERSONA, generate_feedback, merge_feedback
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.piano import PerformedNote, PianoPerformanceScore, score_performance
from app.evaluation.reference_scores import DRUMS_ROCK_GROOVE_XML, PIANO_STEPWISE_SCORE_XML


def _perfect() -> PianoPerformanceScore:
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    spb = 60.0 / score.tempo_bpm
    return score_performance(
        score,
        [
            PerformedNote(60, 0.0),
            PerformedNote(62, spb),
            PerformedNote(64, 2 * spb),
            PerformedNote(65, 3 * spb),
        ],
    )


def test_perfect_run_is_celebratory_with_strengths_and_no_corrections() -> None:
    feedback = generate_feedback(_perfect(), exercise_title="Stepwise C Major", instrument="piano")

    assert feedback.persona == PERSONA
    assert feedback.tone == "celebratory"
    assert feedback.corrections == ()
    assert any("pitch" in strength for strength in feedback.strengths)
    assert "Raise the tempo" in feedback.next_step


def test_silence_is_gentle_with_no_strengths() -> None:
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    result = score_performance(score, [])

    feedback = generate_feedback(result, exercise_title="Stepwise C Major", instrument="piano")

    assert feedback.tone == "supportive"
    assert feedback.strengths == ()
    assert feedback.corrections
    assert "Slow the tempo" in feedback.next_step


def test_misses_and_extras_produce_specific_corrections() -> None:
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    spb = 60.0 / score.tempo_bpm
    missed = score_performance(
        score,
        [PerformedNote(60, 0.0), PerformedNote(62, spb), PerformedNote(64, 2 * spb)],
    )
    extra = score_performance(
        score,
        [
            PerformedNote(60, 0.0),
            PerformedNote(62, spb),
            PerformedNote(64, 2 * spb),
            PerformedNote(65, 3 * spb),
            PerformedNote(67, 4 * spb),
        ],
    )

    missed_feedback = generate_feedback(missed, exercise_title="Stepwise C Major", instrument="piano")
    extra_feedback = generate_feedback(extra, exercise_title="Stepwise C Major", instrument="piano")

    assert any("missed" in correction for correction in missed_feedback.corrections)
    assert any("extra" in correction for correction in extra_feedback.corrections)


def test_drums_feedback_never_claims_pitch() -> None:
    """Rhythm-only instruments have pitch_accuracy=None; feedback must cope."""
    score = parse_musicxml(DRUMS_ROCK_GROOVE_XML)
    spb = 60.0 / score.tempo_bpm / 2  # eighth notes
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

    feedback = generate_feedback(result, exercise_title="Rock Groove", instrument="drums")

    assert feedback.persona == PERSONA
    assert feedback.tone == "celebratory"
    assert any("rhythm" in strength for strength in feedback.strengths)
    assert not any("pitch" in strength.lower() for strength in feedback.strengths)


def test_violin_intonation_is_coached_when_out_of_centre() -> None:
    from app.evaluation.reference_scores import VIOLIN_OPEN_STRINGS_XML
    from app.evaluation.violin import ViolinNote, score_violin_performance

    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)
    spb = 60.0 / score.tempo_bpm
    result = score_violin_performance(
        score,
        [
            ViolinNote(55, 0.0, cents_deviation=40.0),
            ViolinNote(62, spb, cents_deviation=40.0),
            ViolinNote(69, 2 * spb, cents_deviation=40.0),
            ViolinNote(76, 3 * spb, cents_deviation=40.0),
        ],
    )

    feedback = generate_feedback(result, exercise_title="Open String Scale", instrument="violin")

    assert any("intonation" in correction.lower() or "centre" in correction.lower() for correction in feedback.corrections)
    assert "tuner" in feedback.next_step


def test_next_step_is_instrument_aware() -> None:
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    spb = 60.0 / score.tempo_bpm
    result = score_performance(
        score,
        [
            PerformedNote(60, 0.0),
            PerformedNote(62, spb),
            PerformedNote(64, 2 * spb),
            PerformedNote(65, 3 * spb),
        ],
    )

    piano = generate_feedback(result, exercise_title="Stepwise C Major", instrument="piano")
    guitar = generate_feedback(result, exercise_title="Stepwise C Major", instrument="guitar")

    assert "press" in piano.next_step
    assert "play" in guitar.next_step


def test_feedback_is_deterministic_for_the_same_score() -> None:
    result = _perfect()
    first = generate_feedback(result, exercise_title="Stepwise C Major", instrument="piano")
    second = generate_feedback(result, exercise_title="Stepwise C Major", instrument="piano")

    assert first == second


def test_merge_feedback_with_no_upgrade_keeps_the_deterministic_floor() -> None:
    deterministic = generate_feedback(_perfect(), exercise_title="Stepwise C Major", instrument="piano")

    assert merge_feedback(deterministic, None) == deterministic


def test_merge_feedback_takes_upgrade_fields_and_falls_back_per_field() -> None:
    deterministic = generate_feedback(_perfect(), exercise_title="Stepwise C Major", instrument="piano")

    upgraded = merge_feedback(
        deterministic,
        {
            "summary": "A brilliant run of Stepwise C Major.",
            "tone": "celebratory",
            "strengths": ["Pitch was on target."],
            "corrections": [],
            "next_step": "Now double the tempo.",
        },
    )

    assert upgraded.summary == "A brilliant run of Stepwise C Major."
    assert upgraded.strengths == ("Pitch was on target.",)
    assert upgraded.corrections == ()
    assert upgraded.next_step == "Now double the tempo."
    # persona is not part of the upgrade -> the deterministic floor survives
    assert upgraded.persona == deterministic.persona


def test_merge_feedback_ignores_empty_upgrade_fields() -> None:
    deterministic = generate_feedback(_perfect(), exercise_title="Stepwise C Major", instrument="piano")

    upgraded = merge_feedback(
        deterministic,
        {"summary": "", "tone": "", "strengths": [], "corrections": [], "next_step": ""},
    )

    assert upgraded == deterministic


# @spec COACH-CUE-007, COACH-CUE-008
def test_intonation_coaching_threshold_precedes_failure_and_describes_deviation() -> None:
    from app.evaluation.reference_scores import VIOLIN_OPEN_STRINGS_XML
    from app.evaluation.violin import INTONATION_FAIL_CENTS, ViolinNote, score_violin_performance

    # Intonation ladder: 20 cents to coach, 30 cents to fail (COACH-CUE-007)
    coach_intonation_threshold_cents = 20.0
    assert coach_intonation_threshold_cents < INTONATION_FAIL_CENTS

    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)
    spb = 60.0 / score.tempo_bpm
    # Drifted 25 cents: between 20 (coach) and 30 (fail)
    result = score_violin_performance(
        score,
        [
            ViolinNote(55, 0.0, cents_deviation=25.0),
            ViolinNote(62, spb, cents_deviation=25.0),
            ViolinNote(69, 2 * spb, cents_deviation=25.0),
            ViolinNote(76, 3 * spb, cents_deviation=25.0),
        ],
    )
    feedback = generate_feedback(result, exercise_title="Open String Scale", instrument="violin")
    # Verify accurate wording (COACH-CUE-008)
    assert any("twenty cents" in c.lower() or "centre" in c.lower() for c in feedback.corrections)
    assert not any("quarter-tone" in c.lower() for c in feedback.corrections)

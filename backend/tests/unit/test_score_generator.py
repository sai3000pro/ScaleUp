"""The generator's contract: everything it emits is playable and scorable.

Generating MusicXML that merely parses is not enough. The score has to be one
the instrument's own evaluator agrees with -- so the central test here plays
each generated score back perfectly and asserts the scorer says so. A generator
whose output cannot be scored 1.0 by a flawless performance is broken in a way
that would surface as a learner being marked down for playing correctly.
"""

from __future__ import annotations

import pytest

from app.evaluation.drums import EXPECTED_DRUM_BY_POSITION, DrumHit, score_drums_performance
from app.evaluation.guitar import GuitarNote, score_guitar_chords_performance, score_guitar_performance
from app.evaluation.musicxml import MusicXMLParseError, MusicXMLScore, parse_musicxml
from app.evaluation.piano import PerformedNote, score_performance
from app.evaluation.score_generator import (
    MAX_NOTES,
    STANDARD_TUNING,
    GeneratedNote,
    PatternKind,
    ScoreGenerationError,
    ScoreSpec,
    compose_score,
    evaluator_version_for,
    generate_score,
    notes_from_payload,
    render_musicxml,
    spec_for_node,
)
from app.evaluation.trumpet import score_trumpet_performance
from app.evaluation.violin import ViolinNote, score_violin_performance

INSTRUMENTS = ("piano", "guitar", "violin", "trumpet", "drums")
DIFFICULTIES = (1, 2, 3, 4, 5)
TITLES = (
    "Major Scale",
    "Basic Triad",
    "Simple Chord Progression",
    "Five-Finger Pattern",
    "Eighth-Note Groove",
    "Stepwise Melody",
    "Legato Phrasing",
    "Sight-Reading Basics",
)


def _perfect_observations(score: MusicXMLScore) -> list[dict]:
    """The take a flawless performance of `score` would produce."""
    seconds_per_beat = 60.0 / score.tempo_bpm
    observations: list[dict] = []
    for note in score.notes:
        if note.pitch_midi is None and note.unpitched_step is None:
            # A rest is silence, not an event.
            pass
        else:
            observations.append(
                {
                    "pitch_midi": note.pitch_midi,
                    "onset_seconds": note.onset_beats * seconds_per_beat,
                    "duration_seconds": note.duration_beats * seconds_per_beat,
                    "confidence": 1.0,
                    "string": note.string,
                    "fret": note.fret,
                    "drum": EXPECTED_DRUM_BY_POSITION.get((note.unpitched_step or "", note.unpitched_octave or 0)),
                }
            )
    return observations


def _score_perfectly(instrument: str, evaluator_version: str, score: MusicXMLScore) -> float:
    observations = _perfect_observations(score)
    if instrument == "drums":
        hits = [
            DrumHit(onset_seconds=item["onset_seconds"], duration_seconds=item["duration_seconds"],
                    confidence=1.0, drum=item["drum"])
            for item in observations
        ]
        return score_drums_performance(score, hits, evaluator_version=evaluator_version).overall_score
    if instrument == "guitar":
        notes = [
            GuitarNote(pitch_midi=item["pitch_midi"], onset_seconds=item["onset_seconds"],
                       duration_seconds=item["duration_seconds"], confidence=1.0,
                       string=item["string"], fret=item["fret"])
            for item in observations
        ]
        if evaluator_version == "guitar-chords-v1":
            return score_guitar_chords_performance(score, notes, evaluator_version=evaluator_version).overall_score
        return score_guitar_performance(score, notes, evaluator_version=evaluator_version).overall_score
    if instrument == "violin":
        notes = [
            ViolinNote(pitch_midi=item["pitch_midi"], onset_seconds=item["onset_seconds"],
                       duration_seconds=item["duration_seconds"], confidence=1.0, cents_deviation=0.0)
            for item in observations
        ]
        return score_violin_performance(score, notes, evaluator_version=evaluator_version).overall_score
    performed = [
        PerformedNote(pitch_midi=item["pitch_midi"], onset_seconds=item["onset_seconds"],
                      duration_seconds=item["duration_seconds"], confidence=1.0)
        for item in observations
    ]
    if instrument == "trumpet":
        return score_trumpet_performance(score, performed, evaluator_version=evaluator_version).overall_score
    return score_performance(score, performed, evaluator_version=evaluator_version).overall_score


@pytest.mark.parametrize("instrument", INSTRUMENTS)
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
@pytest.mark.parametrize("title", TITLES)
def test_generated_scores_parse(instrument: str, difficulty: int, title: str) -> None:
    spec = spec_for_node(instrument=instrument, node_slug=f"{instrument}-{difficulty}", node_title=title,
                         difficulty=difficulty)
    generated = generate_score(spec)
    score = parse_musicxml(generated.musicxml)
    assert score.notes
    assert score.tempo_bpm == spec.tempo_bpm
    assert len(score.notes) <= MAX_NOTES


@pytest.mark.parametrize("instrument", INSTRUMENTS)
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
@pytest.mark.parametrize("title", TITLES)
def test_a_perfect_performance_of_a_generated_score_scores_full_marks(
    instrument: str, difficulty: int, title: str
) -> None:
    spec = spec_for_node(instrument=instrument, node_slug=f"{instrument}-{difficulty}", node_title=title,
                         difficulty=difficulty)
    generated = generate_score(spec)
    score = parse_musicxml(generated.musicxml)
    assert _score_perfectly(instrument, generated.evaluator_version, score) >= 0.99


@pytest.mark.parametrize("instrument", INSTRUMENTS)
def test_generation_is_deterministic(instrument: str) -> None:
    spec = spec_for_node(instrument=instrument, node_slug="stable-node", node_title="Stepwise Melody", difficulty=4)
    assert generate_score(spec).musicxml == generate_score(spec).musicxml


@pytest.mark.parametrize("tonic", ["C", "G", "D", "F", "Bb", "A", "Eb"])
def test_every_key_is_playable(tonic: str) -> None:
    for instrument in INSTRUMENTS:
        spec = spec_for_node(instrument=instrument, node_slug="key-test", node_title="Major Scale",
                             difficulty=3, overrides={"tonic": tonic})
        parse_musicxml(generate_score(spec).musicxml)


def test_bars_sum_to_the_time_signature() -> None:
    spec = spec_for_node(instrument="piano", node_slug="bars", node_title="Major Scale", difficulty=4)
    score = parse_musicxml(generate_score(spec).musicxml)
    assert score.beats_per_measure == 4
    assert score.duration_beats == pytest.approx(spec.bars * 4.0)


def test_guitar_positions_are_inside_the_wire_contract() -> None:
    """`PerformedNoteIn` validates string 1-6 and fret 0-24; generation must agree."""
    for difficulty in DIFFICULTIES:
        spec = spec_for_node(instrument="guitar", node_slug="frets", node_title="Major Scale", difficulty=difficulty)
        score = parse_musicxml(generate_score(spec).musicxml)
        for note in score.notes:
            assert note.string is not None and 1 <= note.string <= 6
            assert note.fret is not None and 0 <= note.fret <= 24
            assert STANDARD_TUNING[note.string] + note.fret == note.pitch_midi


def test_drum_positions_round_trip_the_scorer_table() -> None:
    spec = spec_for_node(instrument="drums", node_slug="groove", node_title="Eighth-Note Groove", difficulty=3)
    score = parse_musicxml(generate_score(spec).musicxml)
    for note in score.notes:
        assert note.pitch_midi is None
        assert (note.unpitched_step, note.unpitched_octave) in EXPECTED_DRUM_BY_POSITION


def test_guitar_chords_route_to_the_chord_scorer() -> None:
    assert evaluator_version_for("guitar", PatternKind.CHORD_PROGRESSION) == "guitar-chords-v1"
    assert evaluator_version_for("guitar", PatternKind.SCALE_ASCENDING) == "guitar-dtw-v1"
    assert evaluator_version_for("piano", PatternKind.CHORD_PROGRESSION) == "piano-dtw-v1"
    assert evaluator_version_for("drums", PatternKind.RHYTHM_GROOVE) == "drums-rhythm-v1"


def test_monophonic_instruments_never_get_chords() -> None:
    for instrument in ("violin", "trumpet"):
        spec = spec_for_node(instrument=instrument, node_slug="chords", node_title="Simple Chord Progression",
                             difficulty=4)
        assert spec.pattern is not PatternKind.CHORD_PROGRESSION
        score = parse_musicxml(generate_score(spec).musicxml)
        onsets = [note.onset_beats for note in score.notes]
        assert len(onsets) == len(set(onsets)), "a monophonic score must not stack notes on one onset"


def test_a_grid_too_fine_to_notate_is_rejected() -> None:
    """`duration` is an integer count of `divisions`, so the grid has a limit.

    A 1/17-beat note is representable only at 17 divisions per beat, which is
    past anything real notation uses and a sign the caller has a bug rather than
    an unusual rhythm.
    """
    from fractions import Fraction

    spec = ScoreSpec(instrument="piano", pattern=PatternKind.SCALE_ASCENDING, title="Bad")
    notes = [GeneratedNote(step="C", octave=4, duration_beats=Fraction(1, 17))] * 4
    with pytest.raises(ScoreGenerationError):
        render_musicxml(spec, notes)


def test_a_short_bar_in_the_middle_is_rejected() -> None:
    """A short bar shifts every later onset and silently misgrades rhythm."""
    from fractions import Fraction

    spec = ScoreSpec(instrument="piano", pattern=PatternKind.SCALE_ASCENDING, title="Ragged", bars=2)
    notes = [
        GeneratedNote(step="C", octave=4, duration_beats=Fraction(3)),
        GeneratedNote(step="D", octave=4, duration_beats=Fraction(3)),
        GeneratedNote(step="E", octave=4, duration_beats=Fraction(2)),
    ]
    with pytest.raises(ScoreGenerationError):
        render_musicxml(spec, notes)


def test_a_short_final_bar_is_padded_rather_than_emitted_short() -> None:
    from fractions import Fraction

    spec = ScoreSpec(instrument="piano", pattern=PatternKind.SCALE_ASCENDING, title="Short", bars=1)
    notes = [GeneratedNote(step="C", octave=4, duration_beats=Fraction(1)) for _ in range(3)]
    score = parse_musicxml(render_musicxml(spec, notes))
    assert score.duration_beats == pytest.approx(4.0)


def test_a_bare_sound_element_still_fails_to_parse() -> None:
    """Regression guard for the generator's biggest trap.

    `<sound>` directly under `<measure>` is not an allowed child, so tempo has to
    live inside `<direction>`. If the parser ever starts tolerating it, the
    generator's constraint becomes silently unnecessary and will drift.
    """
    payload = """<?xml version="1.0"?><score-partwise version="4.0">
      <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
      <part id="P1"><measure number="1">
        <attributes><divisions>1</divisions></attributes>
        <sound tempo="90"/>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
      </measure></part></score-partwise>"""
    with pytest.raises(MusicXMLParseError):
        parse_musicxml(payload)


class TestComposedUpgrade:
    """`compose_score` keeps the floor whenever the model's notes do not survive."""

    @staticmethod
    def _spec() -> ScoreSpec:
        return spec_for_node(instrument="piano", node_slug="compose", node_title="Stepwise Melody", difficulty=2)

    def test_a_valid_upgrade_is_used(self) -> None:
        spec = self._spec()
        upgrade = {
            "title": "A Better Melody",
            "notes": [
                {"step": "C", "octave": 4, "beats": 1},
                {"step": "E", "octave": 4, "beats": 1},
                {"step": "G", "octave": 4, "beats": 1},
                {"step": "C", "octave": 5, "beats": 1},
            ],
        }
        composed = compose_score(spec, upgrade)
        assert composed.generator == "llm-v1"
        assert parse_musicxml(composed.musicxml).title == "A Better Melody"

    @pytest.mark.parametrize(
        "upgrade",
        [
            {"notes": []},
            {"notes": [{"step": "C", "octave": 9, "beats": 1}] * 4},          # out of range
            {"notes": [{"step": "C", "octave": 4, "beats": 0.33}] * 4},       # off grid
            {"notes": [{"step": "C", "octave": 4, "beats": 1, "drum": "kick"}] * 4},  # drums on a piano
            {"notes": [{"step": "C", "octave": 4, "beats": 1}] * (MAX_NOTES + 4)},    # too long
            {"nonsense": True},
        ],
    )
    def test_a_bad_upgrade_falls_back_to_the_floor(self, upgrade: dict) -> None:
        spec = self._spec()
        assert compose_score(spec, upgrade).generator == "procedural-v1"

    def test_no_upgrade_is_the_floor(self) -> None:
        spec = self._spec()
        assert compose_score(spec, None).musicxml == generate_score(spec).musicxml

    def test_drums_reject_pitched_notes(self) -> None:
        spec = spec_for_node(instrument="drums", node_slug="d", node_title="Groove", difficulty=2)
        with pytest.raises(ScoreGenerationError):
            notes_from_payload({"notes": [{"step": "C", "octave": 4, "beats": 1}]}, spec)

"""Deterministic MusicXML generation for node-attached exercises.

Every skill node that can be played needs a score behind it. Hand-writing them
does not scale past a demo: the five checked-in reference scores cover five nodes out of
the fifty-odd the shipped curricula define, so most of the tree has nothing to
practise.

This module turns `(instrument, pattern, key, tempo, bars, difficulty)` into
MusicXML. It is the **floor**: pure, seedable, free, and available with no API
keys, exactly like the deterministic examiner in `feedback.py`. An LLM may
compose something more musical on top (see `compose_score`), but it returns a
*note list* which this module renders -- so there is exactly one writer of
MusicXML in the repo, and the instrument-specific fields a model must never
guess (guitar string/fret, drum display positions) are derived here from the
same tables the scorers read.

The parser in `musicxml.py` is a narrow subset and rejects rather than tolerates:
one part, a fixed set of allowed `<measure>` children, integer `duration` counts
of `divisions`, and tempo from `<metronome>` or a `<sound tempo>` attribute --
never a bare `<sound>` element under `<measure>`, which raises. So the last thing
`generate_score` does is parse its own output. A generator that emits something
the scorer cannot read is a bug that fails at generation time rather than in
front of a learner.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from typing import Mapping, Sequence
from xml.sax.saxutils import escape

from app.evaluation.drums import EXPECTED_DRUM_BY_POSITION, KNOWN_DRUM_IDS
from app.evaluation.musicxml import MusicXMLParseError, parse_musicxml

__all__ = [
    "GeneratedNote",
    "GeneratedScore",
    "PatternKind",
    "ScoreGenerationError",
    "ScoreSpec",
    "compose_score",
    "evaluator_version_for",
    "generate_score",
    "notes_from_payload",
    "render_musicxml",
    "spec_for_node",
]


class ScoreGenerationError(ValueError):
    """The requested score cannot be rendered as valid, playable MusicXML."""


class PatternKind(StrEnum):
    SCALE_ASCENDING = "scale_ascending"
    SCALE_DESCENDING = "scale_descending"
    SCALE_UP_DOWN = "scale_up_down"
    ARPEGGIO = "arpeggio"
    FIVE_FINGER = "five_finger"
    INTERVAL_DRILL = "interval_drill"
    CHORD_PROGRESSION = "chord_progression"
    RHYTHM_GROOVE = "rhythm_groove"
    MELODIC_PHRASE = "melodic_phrase"


# ── theory tables ─────────────────────────────────────────────────────────────

_STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# Spelled with sharps and with flats. Which one a key uses is a notation
# decision, not a pitch one -- the parser resolves both to the same MIDI number.
_SHARP_SPELLING = (("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
                   ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0))
_FLAT_SPELLING = (("C", 0), ("D", -1), ("D", 0), ("E", -1), ("E", 0), ("F", 0),
                  ("G", -1), ("G", 0), ("A", -1), ("A", 0), ("B", -1), ("B", 0))
_FLAT_KEYS = frozenset({"F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb", "D-", "E-", "A-", "B-", "G-", "C-"})

MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)

# Strings 1..6, standard tuning. Index 0 is unused so `_TUNING[string]` reads
# naturally against the 1-based `<string>` element MusicXML uses.
STANDARD_TUNING = (0, 64, 59, 55, 50, 45, 40)
MAX_FRET = 12

# Hand-authored open-chord voicings as (string, fret). These reproduce the
# voicings already in the seeded G-C-D strum exercise; the pitches come from
# STANDARD_TUNING rather than being restated, so a tuning change moves both.
OPEN_CHORD_SHAPES: dict[str, tuple[tuple[int, int], ...]] = {
    "G": ((6, 3), (5, 2), (4, 0), (3, 0), (2, 0), (1, 3)),
    "C": ((5, 3), (4, 2), (3, 0), (2, 1), (1, 0)),
    "D": ((4, 0), (3, 2), (2, 3), (1, 2)),
    "E": ((6, 0), (5, 2), (4, 2), (3, 1), (2, 0), (1, 0)),
    "A": ((5, 0), (4, 2), (3, 2), (2, 2), (1, 0)),
    "Em": ((6, 0), (5, 2), (4, 2), (3, 0), (2, 0), (1, 0)),
    "Am": ((5, 0), (4, 2), (3, 2), (2, 1), (1, 0)),
}

# Inverted from the scorer's own table, so adding a drum stays a one-row change
# in `drums.py` rather than two edits that can disagree.
_DRUM_POSITION: dict[str, tuple[str, int]] = {
    drum: position for position, drum in EXPECTED_DRUM_BY_POSITION.items()
}


@dataclass(frozen=True, slots=True)
class InstrumentProfile:
    """What an instrument can physically play, and which scorer reads it."""

    slug: str
    part_name: str
    lowest_midi: int
    highest_midi: int
    comfortable_low: int
    comfortable_high: int
    polyphonic: bool
    pitched: bool
    default_pattern: PatternKind
    default_tempo: int
    evaluator_stem: str


INSTRUMENT_PROFILES: dict[str, InstrumentProfile] = {
    "piano": InstrumentProfile("piano", "Piano", 21, 108, 55, 84, True, True,
                               PatternKind.FIVE_FINGER, 96, "piano-dtw-v1"),
    "guitar": InstrumentProfile("guitar", "Guitar", 40, 76, 40, 72, True, True,
                                PatternKind.SCALE_ASCENDING, 90, "guitar-dtw-v1"),
    "violin": InstrumentProfile("violin", "Violin", 55, 91, 55, 79, False, True,
                                PatternKind.SCALE_ASCENDING, 80, "violin-dtw-v1"),
    "trumpet": InstrumentProfile("trumpet", "Trumpet", 52, 82, 55, 77, False, True,
                                 PatternKind.ARPEGGIO, 88, "trumpet-dtw-v1"),
    "drums": InstrumentProfile("drums", "Drums", 0, 0, 0, 0, True, False,
                               PatternKind.RHYTHM_GROOVE, 92, "drums-rhythm-v1"),
}

DEFAULT_INSTRUMENT = "piano"
# DTW is O(expected x observed) and a practice clip is a demo take, not a
# recital. This bound keeps a generated exercise inside a second of scoring.
MAX_NOTES = 64
_ALLOWED_BEATS = (Fraction(1, 2), Fraction(1), Fraction(3, 2), Fraction(2), Fraction(3), Fraction(4))


@dataclass(frozen=True, slots=True)
class GeneratedNote:
    """One note, rest, or drum hit, before it becomes XML.

    ``step is None`` means a rest. ``chord=True`` means the note sounds with the
    previous one and does not advance the measure cursor, which is exactly the
    semantics `parse_musicxml` implements for `<chord/>`.
    """

    step: str | None = None
    alter: int = 0
    octave: int = 4
    duration_beats: Fraction = Fraction(1)
    chord: bool = False
    string: int | None = None
    fret: int | None = None
    drum: str | None = None

    @property
    def midi(self) -> int | None:
        if self.step is None:
            return None
        return 12 * (self.octave + 1) + _STEP_SEMITONES[self.step] + self.alter


@dataclass(frozen=True, slots=True)
class ScoreSpec:
    instrument: str
    pattern: PatternKind
    title: str
    tonic: str = "C"
    mode: str = "major"
    tempo_bpm: int = 96
    beats_per_measure: int = 4
    beat_type: int = 4
    bars: int = 2
    difficulty: int = 3
    octave: int = 4
    # The node slug. Determinism comes from hashing this rather than from an RNG
    # seed, so the same node always yields the same exercise across processes.
    seed: str = ""


@dataclass(frozen=True, slots=True)
class GeneratedScore:
    musicxml: str
    spec: ScoreSpec
    notes: tuple[GeneratedNote, ...]
    evaluator_version: str
    asset_metadata: dict[str, object]
    generator: str


# ── determinism ───────────────────────────────────────────────────────────────


def _unit(seed: str, index: int) -> float:
    """A stable float in [0, 1) from a seed and an index.

    `fake_provider` has an equivalent helper, deliberately not imported:
    `app/evaluation/` is a leaf and must not depend on `app/llm/`.
    """
    digest = hashlib.sha256(f"{seed}:{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _choice(seed: str, index: int, options: Sequence[int]) -> int:
    if not options:
        raise ScoreGenerationError("Cannot choose from an empty option list.")
    return options[int(_unit(seed, index) * len(options)) % len(options)]


# ── pitch helpers ─────────────────────────────────────────────────────────────


def _tonic_pitch_class(tonic: str) -> int:
    letter = tonic[:1].upper()
    if letter not in _STEP_SEMITONES:
        raise ScoreGenerationError(f"Unknown tonic: {tonic!r}.")
    accidental = tonic[1:]
    shift = 0
    if accidental in {"#", "s"}:
        shift = 1
    elif accidental in {"b", "-"}:
        shift = -1
    elif accidental != "":
        raise ScoreGenerationError(f"Unknown tonic accidental in {tonic!r}.")
    return (_STEP_SEMITONES[letter] + shift) % 12


def _spell(midi: int, tonic: str) -> tuple[str, int, int]:
    """MIDI number to (step, alter, octave), spelled to suit the key."""
    if not 0 <= midi <= 127:
        raise ScoreGenerationError(f"Pitch {midi} falls outside the MIDI range.")
    table = _FLAT_SPELLING if tonic in _FLAT_KEYS else _SHARP_SPELLING
    step, alter = table[midi % 12]
    octave = midi // 12 - 1
    # A flat spelling of C or F borrows from the octave above (Cb4 sounds as B3),
    # so the written octave has to follow the letter, not the pitch class.
    if alter == -1 and step == "C":
        octave += 1
    return step, alter, octave


def _scale_midis(spec: ScoreSpec, count: int, *, descending: bool = False) -> list[int]:
    steps = MINOR_STEPS if spec.mode.lower().startswith("min") else MAJOR_STEPS
    root = 12 * (spec.octave + 1) + _tonic_pitch_class(spec.tonic)
    ladder = [root + 12 * (index // len(steps)) + steps[index % len(steps)] for index in range(count)]
    if descending:
        ladder.reverse()
    return ladder


# How far up the scale an exercise is allowed to travel, by difficulty. Without
# this the ladder is as long as there are notes to fill, so a 32-note exercise
# climbs four and a half octaves -- past every instrument in the profile table
# and well past anything a learner at that level should be handed.
_DIFFICULTY_DEGREES = {1: 5, 2: 8, 3: 8, 4: 15, 5: 15}


def _octave_shifts(low: int, high: int, profile: InstrumentProfile) -> list[int]:
    """Whole-octave transpositions that land [low, high] inside the instrument."""
    return [
        shift for shift in range(-8, 9)
        if profile.lowest_midi <= low + 12 * shift and high + 12 * shift <= profile.highest_midi
    ]


def _ladder(spec: ScoreSpec, profile: InstrumentProfile) -> list[int]:
    """The bounded set of pitches a pattern may draw from, in ascending order.

    Shrinks on *placement*, not on span. A two-octave phrase is 24 semitones and
    fits inside the trumpet's 30, yet no whole-octave shift puts it between E3
    and Bb5 -- one end always hangs over. Testing the span alone declares that
    phrase fine and then fails when it is transposed.
    """
    degrees = _DIFFICULTY_DEGREES[max(1, min(5, spec.difficulty))]
    rungs = _scale_midis(spec, degrees)
    while len(rungs) > 2 and not _octave_shifts(rungs[0], rungs[-1], profile):
        rungs.pop()
    if not _octave_shifts(rungs[0], rungs[-1], profile):
        raise ScoreGenerationError(
            f"No phrase fits {profile.slug} ({profile.lowest_midi}-{profile.highest_midi}) in {spec.tonic}."
        )
    return rungs


def _cycle(values: Sequence[int], slots: int) -> list[int]:
    if not values:
        raise ScoreGenerationError("Cannot build a phrase from an empty pitch set.")
    return [values[index % len(values)] for index in range(slots)]


def _fit_to_instrument(midis: Sequence[int], profile: InstrumentProfile) -> list[int]:
    """Transpose by whole octaves so the phrase sits in the instrument's range.

    Chooses a shift rather than stepping toward one. Stepping up off the low
    bound and then down off the high bound oscillates forever whenever the
    phrase is wider than the comfortable band but still inside the playable one
    -- which is the normal case for a two-octave scale on guitar.
    """
    if not midis:
        return []
    low, high = min(midis), max(midis)
    span = high - low
    if span > profile.highest_midi - profile.lowest_midi:
        raise ScoreGenerationError(
            f"Phrase spans {span} semitones; {profile.slug} covers "
            f"{profile.highest_midi - profile.lowest_midi}."
        )

    playable = _octave_shifts(low, high, profile)
    if not playable:
        raise ScoreGenerationError(
            f"Phrase spanning {low}-{high} cannot be transposed into {profile.slug} "
            f"({profile.lowest_midi}-{profile.highest_midi})."
        )
    comfortable_centre = (profile.comfortable_low + profile.comfortable_high) / 2
    best = min(playable, key=lambda shift: abs((low + high) / 2 + 12 * shift - comfortable_centre))
    return [value + 12 * best for value in midis]


def _string_and_fret(midi: int) -> tuple[int, int]:
    """Lowest-numbered playable string for a pitch, preferring low frets.

    Strings run 1 (high E) to 6 (low E), which is also the range
    `PerformedNoteIn.string` validates, so a position generated here is always a
    position the wire contract accepts.
    """
    candidates = [
        (string, midi - STANDARD_TUNING[string])
        for string in range(1, 7)
        if 0 <= midi - STANDARD_TUNING[string] <= MAX_FRET
    ]
    if not candidates:
        raise ScoreGenerationError(f"Pitch {midi} is not playable in standard tuning below fret {MAX_FRET}.")
    # Highest string number with the pitch still reachable = lowest position on
    # the neck, which is where a beginner exercise belongs.
    string, fret = max(candidates, key=lambda pair: pair[0])
    return string, fret


# ── patterns ──────────────────────────────────────────────────────────────────


def _beats_per_bar(spec: ScoreSpec) -> Fraction:
    return Fraction(spec.beats_per_measure * 4, spec.beat_type)


def _note_value(spec: ScoreSpec) -> Fraction:
    """The shortest written value the difficulty allows."""
    if spec.difficulty <= 2:
        return Fraction(1)
    return Fraction(1, 2)


def _pitched_pattern(spec: ScoreSpec, profile: InstrumentProfile) -> list[GeneratedNote]:
    value = _note_value(spec)
    slots = int(_beats_per_bar(spec) * spec.bars / value)
    slots = min(slots, MAX_NOTES)
    if slots <= 0:
        raise ScoreGenerationError("The requested bars and time signature leave no room for notes.")

    rungs = _ladder(spec, profile)
    if spec.pattern is PatternKind.FIVE_FINGER:
        midis = _cycle(rungs[:5], slots)
    elif spec.pattern is PatternKind.SCALE_ASCENDING:
        midis = _cycle(rungs, slots)
    elif spec.pattern is PatternKind.SCALE_DESCENDING:
        midis = _cycle(list(reversed(rungs)), slots)
    elif spec.pattern is PatternKind.SCALE_UP_DOWN:
        midis = _cycle(rungs + list(reversed(rungs[1:-1])), slots)
    elif spec.pattern is PatternKind.ARPEGGIO:
        steps = MINOR_STEPS if spec.mode.lower().startswith("min") else MAJOR_STEPS
        root = rungs[0]
        shape = [root + steps[0], root + steps[2], root + steps[4], root + 12]
        midis = _cycle([value for value in shape if value - root <= rungs[-1] - rungs[0] or value == root + 12], slots)
    elif spec.pattern is PatternKind.INTERVAL_DRILL:
        midis = _cycle([rungs[(index * 2) % len(rungs)] for index in range(len(rungs))], slots)
    elif spec.pattern is PatternKind.MELODIC_PHRASE:
        # Seeded, not random: the same node always produces the same phrase.
        choices = tuple(range(len(rungs)))
        midis = [rungs[_choice(spec.seed or spec.title, index, choices)] for index in range(slots)]
        # Open and close on the tonic so the phrase reads as a phrase.
        midis[0] = rungs[0]
        midis[-1] = rungs[0]
    else:
        raise ScoreGenerationError(f"Pattern {spec.pattern!r} is not a pitched pattern.")

    fitted = _fit_to_instrument(midis, profile)
    notes: list[GeneratedNote] = []
    for midi in fitted:
        step, alter, octave = _spell(midi, spec.tonic)
        string, fret = _string_and_fret(midi) if profile.slug == "guitar" else (None, None)
        notes.append(
            GeneratedNote(step=step, alter=alter, octave=octave, duration_beats=value, string=string, fret=fret)
        )
    return notes


_CHORD_PROGRESSION = ("G", "C", "D", "G")


def _chord_pattern(spec: ScoreSpec, profile: InstrumentProfile) -> list[GeneratedNote]:
    """A chord progression as simultaneous notes sharing one onset.

    On guitar these are open-position voicings carrying string/fret, and
    `evaluator_version_for` routes the exercise to the chord scorer, which
    groups written notes by shared onset and observed notes by strum spread.
    Everything else polyphonic gets root-position triads with no tab.

    Chords land twice a bar at most. One strum per beat looked reasonable and
    is not: six voices on every beat of four bars is 96 events, well past the
    ceiling DTW is comfortable with.
    """
    per_bar = _beats_per_bar(spec)
    chords_per_bar = 2 if spec.difficulty >= 3 and per_bar >= 4 else 1
    value = per_bar / chords_per_bar
    notes: list[GeneratedNote] = []

    for index in range(spec.bars * chords_per_bar):
        name = _CHORD_PROGRESSION[index % len(_CHORD_PROGRESSION)]
        if profile.slug == "guitar":
            voicing = [(STANDARD_TUNING[string] + fret, string, fret) for string, fret in OPEN_CHORD_SHAPES[name]]
        else:
            root = 12 * (spec.octave + 1) + _tonic_pitch_class(name)
            triad = _fit_to_instrument([root, root + 4, root + 7], profile)
            voicing = [(midi, None, None) for midi in triad]
        for offset, (midi, string, fret) in enumerate(voicing):
            step, alter, octave = _spell(midi, spec.tonic)
            notes.append(
                GeneratedNote(
                    step=step,
                    alter=alter,
                    octave=octave,
                    duration_beats=value,
                    chord=offset > 0,
                    string=string,
                    fret=fret,
                )
            )

    if len(notes) > MAX_NOTES:
        raise ScoreGenerationError(f"Chord pattern produced {len(notes)} notes; the ceiling is {MAX_NOTES}.")
    return notes


def _groove_pattern(spec: ScoreSpec) -> list[GeneratedNote]:
    """A rock groove: hihat on every beat, kick on 1 and 3, snare on 2 and 4."""
    beats = int(_beats_per_bar(spec))
    notes: list[GeneratedNote] = []
    for bar in range(spec.bars):
        for beat in range(beats):
            layer = ["hihat"]
            if beat % 4 in {0, 2}:
                layer.append("kick" if beat % 4 == 0 else "snare")
            elif beat % 2 == 1:
                layer.append("snare")
            for offset, drum in enumerate(layer):
                step, octave = _DRUM_POSITION[drum]
                notes.append(
                    GeneratedNote(
                        step=step,
                        octave=octave,
                        duration_beats=Fraction(1),
                        chord=offset > 0,
                        drum=drum,
                    )
                )
        del bar
    if len(notes) > MAX_NOTES:
        raise ScoreGenerationError("Groove pattern exceeded the note ceiling; reduce bars.")
    return notes


# ── rendering ─────────────────────────────────────────────────────────────────


def _divisions_for(notes: Sequence[GeneratedNote]) -> int:
    """The smallest divisions value that makes every duration an integer.

    `parse_musicxml` reads `duration` with `_required_int`, so a fractional
    count is not a rounding question -- it fails to parse.
    """
    denominator = 1
    for note in notes:
        denominator = denominator * note.duration_beats.denominator // _gcd(denominator, note.duration_beats.denominator)
    if denominator > 16:
        raise ScoreGenerationError(f"Durations need {denominator} divisions per beat; the grid is too fine.")
    return denominator


def _gcd(left: int, right: int) -> int:
    while right:
        left, right = right, left % right
    return left


def _measures(spec: ScoreSpec, notes: Sequence[GeneratedNote]) -> list[list[GeneratedNote]]:
    """Split a flat note list on bar lines, verifying each bar sums exactly."""
    per_bar = _beats_per_bar(spec)
    measures: list[list[GeneratedNote]] = []
    current: list[GeneratedNote] = []
    filled = Fraction(0)
    for note in notes:
        advance = Fraction(0) if note.chord else note.duration_beats
        if filled + advance > per_bar and not note.chord:
            measures.append(current)
            current = []
            filled = Fraction(0)
        current.append(note)
        filled += advance
    if current:
        measures.append(current)

    for index, measure in enumerate(measures):
        total = sum((note.duration_beats for note in measure if not note.chord), Fraction(0))
        if total != per_bar:
            # Pad the final bar with a rest rather than emitting a short measure:
            # a short bar shifts every later onset and silently misgrades rhythm.
            if index == len(measures) - 1 and total < per_bar:
                measure.append(GeneratedNote(step=None, duration_beats=per_bar - total))
            else:
                raise ScoreGenerationError(
                    f"Measure {index + 1} holds {total} beats but the time signature needs {per_bar}."
                )
    return measures


def _note_xml(note: GeneratedNote, divisions: int) -> str:
    units = note.duration_beats * divisions
    if units.denominator != 1 or units <= 0:
        raise ScoreGenerationError(f"Duration {note.duration_beats} is not an integer at {divisions} divisions.")
    parts = ["<note>"]
    if note.chord:
        parts.append("<chord/>")
    if note.step is None:
        parts.append("<rest/>")
    elif note.drum is not None:
        parts.append(f"<unpitched><display-step>{note.step}</display-step>"
                     f"<display-octave>{note.octave}</display-octave></unpitched>")
    else:
        alter = f"<alter>{note.alter}</alter>" if note.alter else ""
        parts.append(f"<pitch><step>{note.step}</step>{alter}<octave>{note.octave}</octave></pitch>")
    parts.append(f"<duration>{units.numerator}</duration><voice>1</voice>")
    if note.string is not None and note.fret is not None:
        parts.append(f"<notations><technical><string>{note.string}</string>"
                     f"<fret>{note.fret}</fret></technical></notations>")
    parts.append("</note>")
    return "".join(parts)


def render_musicxml(spec: ScoreSpec, notes: Sequence[GeneratedNote]) -> str:
    """Render a note list as MusicXML the evaluator's parser accepts."""
    if not notes:
        raise ScoreGenerationError("A score must contain at least one note.")
    if len(notes) > MAX_NOTES:
        raise ScoreGenerationError(f"A generated score may hold at most {MAX_NOTES} notes.")
    profile = INSTRUMENT_PROFILES.get(spec.instrument, INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT])
    divisions = _divisions_for(notes)
    measures = _measures(spec, notes)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<score-partwise version="4.0">',
        f"  <work><work-title>{escape(spec.title)}</work-title></work>",
        f'  <part-list><score-part id="P1"><part-name>{escape(profile.part_name)}</part-name>'
        "</score-part></part-list>",
        '  <part id="P1">',
    ]
    for index, measure in enumerate(measures, start=1):
        lines.append(f'    <measure number="{index}">')
        if index == 1:
            lines.append(f"      <attributes><divisions>{divisions}</divisions>"
                         f"<time><beats>{spec.beats_per_measure}</beats>"
                         f"<beat-type>{spec.beat_type}</beat-type></time></attributes>")
            # Tempo lives inside <direction>. A bare <sound> element directly
            # under <measure> is an unsupported child and raises on parse.
            lines.append("      <direction><direction-type><metronome>"
                         "<beat-unit>quarter</beat-unit>"
                         f"<per-minute>{spec.tempo_bpm}</per-minute>"
                         "</metronome></direction-type></direction>")
        for note in measure:
            lines.append(f"      {_note_xml(note, divisions)}")
        lines.append("    </measure>")
    lines.append("  </part>")
    lines.append("</score-partwise>")
    return "\n".join(lines) + "\n"


# ── public API ────────────────────────────────────────────────────────────────


# @spec EVAL-VER-001, EVAL-VER-002
def evaluator_version_for(instrument: str, pattern: PatternKind) -> str:
    """Pick the scorer this exercise must be graded by.

    Getting this wrong is silent: `submit_attempt` chooses the evaluator from
    this string, so a chord score labelled `guitar-dtw-v1` is graded as a
    monophonic line and every strum reads as five extra notes.
    """
    if instrument == "guitar" and pattern is PatternKind.CHORD_PROGRESSION:
        return "guitar-chords-v1"
    profile = INSTRUMENT_PROFILES.get(instrument, INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT])
    return profile.evaluator_stem


_DIFFICULTY_BARS = {1: 1, 2: 2, 3: 2, 4: 4, 5: 4}
_DIFFICULTY_TEMPO = {1: 72, 2: 84, 3: 96, 4: 108, 5: 120}
# Keyword cues from the node's own title, so a node called "Major Scale" gets a
# scale and one called "Basic Triad" gets an arpeggio, with no per-instrument
# branching and no curriculum-specific table.
_TITLE_CUES: tuple[tuple[str, PatternKind], ...] = (
    ("chord progression", PatternKind.CHORD_PROGRESSION),
    ("open chord", PatternKind.CHORD_PROGRESSION),
    ("triad", PatternKind.ARPEGGIO),
    ("arpeggio", PatternKind.ARPEGGIO),
    ("scale", PatternKind.SCALE_UP_DOWN),
    ("five-finger", PatternKind.FIVE_FINGER),
    ("five finger", PatternKind.FIVE_FINGER),
    ("interval", PatternKind.INTERVAL_DRILL),
    ("groove", PatternKind.RHYTHM_GROOVE),
    ("rhythm", PatternKind.RHYTHM_GROOVE),
    ("beat", PatternKind.RHYTHM_GROOVE),
    ("melody", PatternKind.MELODIC_PHRASE),
    ("phrase", PatternKind.MELODIC_PHRASE),
    ("sight", PatternKind.MELODIC_PHRASE),
    ("open string", PatternKind.SCALE_ASCENDING),
)


# @spec EVAL-GEN-001
def spec_for_node(
    *,
    instrument: str,
    node_slug: str,
    node_title: str,
    difficulty: int,
    overrides: Mapping[str, object] | None = None,
) -> ScoreSpec:
    """Derive a playable exercise spec from a skill node.

    Difficulty drives length, tempo, and the shortest written value; the node's
    own title picks the pattern. Both are overridable, because a curriculum
    author knows better than a keyword match.
    """
    profile = INSTRUMENT_PROFILES.get(instrument, INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT])
    clamped = max(1, min(5, difficulty))
    lowered = node_title.lower()
    pattern = profile.default_pattern
    for cue, candidate in _TITLE_CUES:
        if cue in lowered and pattern is profile.default_pattern:
            pattern = candidate
    if not profile.pitched:
        pattern = PatternKind.RHYTHM_GROOVE
    elif pattern is PatternKind.CHORD_PROGRESSION and not profile.polyphonic:
        pattern = PatternKind.ARPEGGIO
    elif pattern is PatternKind.RHYTHM_GROOVE and profile.pitched:
        pattern = PatternKind.FIVE_FINGER

    spec = ScoreSpec(
        instrument=profile.slug,
        pattern=pattern,
        title=f"{node_title} Exercise",
        tempo_bpm=_DIFFICULTY_TEMPO[clamped],
        bars=_DIFFICULTY_BARS[clamped],
        difficulty=clamped,
        octave=4 if profile.slug != "guitar" else 3,
        seed=node_slug,
    )
    if overrides:
        spec = _apply_overrides(spec, overrides)
    return spec


_OVERRIDE_INTS = frozenset({"tempo_bpm", "bars", "beats_per_measure", "beat_type", "difficulty", "octave"})
_OVERRIDE_STRS = frozenset({"tonic", "mode", "title"})


def _apply_overrides(spec: ScoreSpec, overrides: Mapping[str, object]) -> ScoreSpec:
    changes: dict[str, object] = {}
    for key, value in overrides.items():
        if value is None:
            pass
        elif key == "pattern":
            changes["pattern"] = PatternKind(str(value))
        elif key in _OVERRIDE_INTS:
            changes[key] = int(value)  # type: ignore[arg-type]
        elif key in _OVERRIDE_STRS:
            changes[key] = str(value)
    return replace(spec, **changes)  # type: ignore[arg-type]


def _notes_for(spec: ScoreSpec) -> list[GeneratedNote]:
    profile = INSTRUMENT_PROFILES.get(spec.instrument, INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT])
    if spec.pattern is PatternKind.RHYTHM_GROOVE:
        return _groove_pattern(spec)
    if spec.pattern is PatternKind.CHORD_PROGRESSION:
        return _chord_pattern(spec, profile)
    return _pitched_pattern(spec, profile)


def _metadata(spec: ScoreSpec, generator: str, extra: Mapping[str, object] | None = None) -> dict[str, object]:
    profile = INSTRUMENT_PROFILES.get(spec.instrument, INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT])
    metadata: dict[str, object] = {
        # Load-bearing: `submit_attempt` reads `instrument` to choose a scorer.
        "instrument": profile.slug,
        "monophonic": not profile.polyphonic,
        "rhythm_only": not profile.pitched,
        "generator": generator,
        "pattern": str(spec.pattern),
        "key": f"{spec.tonic} {spec.mode}",
        "bars": spec.bars,
        "difficulty": spec.difficulty,
        "generator_seed": spec.seed,
    }
    if extra:
        metadata.update(extra)
    return metadata


def _finalize(spec: ScoreSpec, notes: Sequence[GeneratedNote], generator: str,
              extra: Mapping[str, object] | None = None) -> GeneratedScore:
    musicxml = render_musicxml(spec, notes)
    try:
        parse_musicxml(musicxml)
    except MusicXMLParseError as exc:
        raise ScoreGenerationError(f"Generated score is not readable by the evaluator: {exc}") from exc
    return GeneratedScore(
        musicxml=musicxml,
        spec=spec,
        notes=tuple(notes),
        evaluator_version=evaluator_version_for(spec.instrument, spec.pattern),
        asset_metadata=_metadata(spec, generator, extra),
        generator=generator,
    )


# @spec EVAL-GEN-001, EVAL-GEN-002, EVAL-GEN-003, EVAL-GEN-004
def generate_score(spec: ScoreSpec) -> GeneratedScore:
    """The deterministic floor. Always available, always valid, never billed."""
    return _finalize(spec, _notes_for(spec), "procedural-v1")


def notes_from_payload(payload: Mapping[str, object], spec: ScoreSpec) -> tuple[GeneratedNote, ...]:
    """Turn a validated `score_notes` payload into renderable notes.

    The model supplies pitch and rhythm only. String/fret and drum display
    positions are derived here from the instrument tables, because a wrong fret
    becomes a wrong technique score and a wrong drum becomes a missed hit -- and
    both would look like the learner's fault.
    """
    profile = INSTRUMENT_PROFILES.get(spec.instrument, INSTRUMENT_PROFILES[DEFAULT_INSTRUMENT])
    raw = payload.get("notes")
    if not isinstance(raw, list) or not raw:
        raise ScoreGenerationError("Composed score carries no notes.")

    notes: list[GeneratedNote] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ScoreGenerationError("Composed note is not an object.")
        beats = Fraction(str(entry.get("beats", 1))).limit_denominator(4)
        if beats not in _ALLOWED_BEATS:
            raise ScoreGenerationError(f"Composed note has an off-grid duration: {beats}.")
        drum = entry.get("drum")
        step = entry.get("step")
        chord = bool(entry.get("chord", False))

        if not profile.pitched:
            if not isinstance(drum, str) or drum not in KNOWN_DRUM_IDS or drum not in _DRUM_POSITION:
                raise ScoreGenerationError(f"Composed drum note names an unplayable drum: {drum!r}.")
            position_step, position_octave = _DRUM_POSITION[drum]
            notes.append(GeneratedNote(step=position_step, octave=position_octave,
                                       duration_beats=beats, chord=chord, drum=drum))
        elif drum is not None:
            raise ScoreGenerationError("A pitched instrument cannot be given drum notes.")
        elif step is None:
            notes.append(GeneratedNote(step=None, duration_beats=beats))
        else:
            candidate = GeneratedNote(
                step=str(step),
                alter=int(entry.get("alter", 0) or 0),
                octave=int(entry.get("octave", spec.octave)),
                duration_beats=beats,
                chord=chord,
            )
            midi = candidate.midi
            if midi is None or not profile.lowest_midi <= midi <= profile.highest_midi:
                raise ScoreGenerationError(
                    f"Composed pitch {midi} is outside the {profile.slug} range "
                    f"({profile.lowest_midi}-{profile.highest_midi})."
                )
            if profile.slug == "guitar":
                string, fret = _string_and_fret(midi)
                candidate = replace(candidate, string=string, fret=fret)
            notes.append(candidate)

    if len(notes) > MAX_NOTES:
        raise ScoreGenerationError(f"Composed score holds {len(notes)} notes; the ceiling is {MAX_NOTES}.")
    if not profile.polyphonic and any(note.chord for note in notes):
        raise ScoreGenerationError(f"{profile.slug} is monophonic and cannot be given chords.")
    return tuple(notes)


def compose_score(spec: ScoreSpec, upgrade: Mapping[str, object] | None) -> GeneratedScore:
    """Prefer a composed score, but only if it survives every check.

    Same discipline as `merge_feedback`: the deterministic result is the floor,
    the model is an upgrade, and any failure keeps the floor rather than
    surfacing an error to a learner who just wanted something to play.
    """
    floor = generate_score(spec)
    if not upgrade:
        return floor
    title = upgrade.get("title")
    composed_spec = replace(spec, title=str(title)) if isinstance(title, str) and title.strip() else spec
    try:
        notes = notes_from_payload(upgrade, composed_spec)
        return _finalize(composed_spec, notes, "llm-v1", {"floor_generator": floor.generator})
    except (ScoreGenerationError, ValueError, TypeError, KeyError):
        return floor

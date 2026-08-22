"""Normalize the small, useful subset of MusicXML needed by piano exercises.

The evaluator consumes canonical note events rather than XML. Keeping this parser
pure makes scores fast to test and lets a future richer MusicXML reader
sit behind the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from xml.etree import ElementTree


class MusicXMLParseError(ValueError):
    """The score is malformed or outside the supported normalization subset."""


# Written dynamic levels on a 0..1 scale. The numbers are not loudness -- no
# score says how many decibels `f` is, and it depends on the room, the
# instrument, and the player. They are an ORDERING with even spacing, which is
# all a scorer can honestly compare a performance against.
DYNAMIC_LEVELS: dict[str, float] = {
    "ppp": 0.0, "pp": 0.14, "p": 0.29, "mp": 0.43,
    "mf": 0.57, "f": 0.71, "ff": 0.86, "fff": 1.0,
}


@dataclass(frozen=True, slots=True)
class DynamicMark:
    """One written dynamic instruction, positioned on the beat grid."""

    onset_beats: float
    mark: str          # ppp..fff, or "crescendo"/"diminuendo" for a hairpin
    kind: str          # level | hairpin_start | hairpin_stop
    level: float | None = None


@dataclass(frozen=True, slots=True)
class ScoreNote:
    """One normalized score event.

    Pitched notes carry ``pitch_midi``; rests and unpitched (percussion) events
    carry ``pitch_midi=None``. Unpitched events additionally carry the written
    ``display-step``/``display-octave`` so a drums scorer can recover which
    drum was intended without inventing a pitch.
    """

    pitch_midi: int | None
    onset_beats: float
    duration_beats: float
    voice: str
    staff: int | None = None
    string: int | None = None
    fret: int | None = None
    unpitched_step: str | None = None
    unpitched_octave: int | None = None


@dataclass(frozen=True, slots=True)
# @spec EVAL-NOTE-005
class MusicXMLScore:
    title: str
    tempo_bpm: float
    divisions: int
    beats_per_measure: int | None
    beat_type: int | None
    notes: tuple[ScoreNote, ...]
    duration_beats: float
    # Defaulted, so every existing construction and test is untouched. An empty
    # tuple means "this score says nothing about dynamics", which is different
    # from "play everything at one level" and is scored as inapplicable.
    dynamics: tuple[DynamicMark, ...] = ()

    @property
    def pitched_notes(self) -> tuple[ScoreNote, ...]:
        """Return sounding notes in deterministic onset order."""
        return tuple(note for note in self.notes if note.pitch_midi is not None)

    def expected_level_at(self, onset_beats: float) -> float | None:
        """The written dynamic level in force at a beat, 0..1.

        Returns None when the score carries no dynamics at all -- the honest
        answer, and the one that keeps a scorer from marking a learner against
        an instruction nobody wrote. Inside an open hairpin the level ramps
        linearly toward the next written level, which is what a crescendo means
        to a player even though the notation says nothing about rate.
        """
        levels = [mark for mark in self.dynamics if mark.kind == "level" and mark.level is not None]
        if not levels:
            return None

        current = None
        for mark in levels:
            if mark.onset_beats <= onset_beats:
                current = mark
        if current is None:
            current = levels[0]

        hairpin = None
        for mark in self.dynamics:
            if mark.kind == "hairpin_start" and current.onset_beats <= mark.onset_beats <= onset_beats:
                hairpin = mark
            elif mark.kind == "hairpin_stop" and hairpin is not None and mark.onset_beats <= onset_beats:
                hairpin = None
        if hairpin is None:
            return current.level

        following = [mark for mark in levels if mark.onset_beats > hairpin.onset_beats]
        target = following[0] if following else None
        if target is None:
            # An unresolved hairpin still means "keep going that way"; a full
            # step of the level scale is the mildest honest reading.
            direction = 0.14 if hairpin.mark == "crescendo" else -0.14
            return max(0.0, min(1.0, current.level + direction))
        span = target.onset_beats - hairpin.onset_beats
        if span <= 0:
            return target.level
        travelled = min(1.0, (onset_beats - hairpin.onset_beats) / span)
        return current.level + (target.level - current.level) * travelled


_STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    result = next((child for child in element if _local_name(child.tag) == name), None)
    return result


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _text(element: ElementTree.Element, name: str) -> str | None:
    child = _child(element, name)
    return child.text.strip() if child is not None and child.text else None


def _required_int(element: ElementTree.Element, name: str) -> int:
    value = _text(element, name)
    if value is None:
        raise MusicXMLParseError(f"MusicXML element {name!r} requires an integer value.")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise MusicXMLParseError(f"MusicXML element {name!r} is not an integer: {value!r}.") from exc
    return parsed


def _optional_int(element: ElementTree.Element, name: str) -> int | None:
    value = _text(element, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise MusicXMLParseError(f"MusicXML element {name!r} is not an integer: {value!r}.") from exc


def _pitch_midi(pitch: ElementTree.Element) -> int:
    step = _text(pitch, "step")
    octave = _text(pitch, "octave")
    if step not in _STEP_SEMITONES or octave is None:
        raise MusicXMLParseError("A pitched note requires a valid step and octave.")
    try:
        octave_number = int(octave)
        alter = float(_text(pitch, "alter") or "0")
    except ValueError as exc:
        raise MusicXMLParseError("MusicXML pitch alteration and octave must be numeric.") from exc
    if not isfinite(alter) or alter != int(alter):
        raise MusicXMLParseError("Only integer MusicXML pitch alterations are supported.")
    midi = 12 * (octave_number + 1) + _STEP_SEMITONES[step] + int(alter)
    if not 0 <= midi <= 127:
        raise MusicXMLParseError(f"MusicXML pitch falls outside MIDI range: {midi}.")
    return midi


def _tempo(root: ElementTree.Element) -> float:
    sounds = [element for element in root.iter() if _local_name(element.tag) == "sound"]
    for sound in sounds:
        raw = sound.attrib.get("tempo")
        if raw is not None:
            try:
                tempo = float(raw)
            except ValueError as exc:
                raise MusicXMLParseError(f"Invalid tempo value: {raw!r}.") from exc
            if isfinite(tempo) and tempo > 0:
                return tempo
            raise MusicXMLParseError("MusicXML tempo must be positive and finite.")

    metronomes = [element for element in root.iter() if _local_name(element.tag) == "metronome"]
    for metronome in metronomes:
        raw = _text(metronome, "per-minute")
        if raw is not None:
            try:
                tempo = float(raw)
            except ValueError as exc:
                raise MusicXMLParseError(f"Invalid metronome tempo: {raw!r}.") from exc
            if isfinite(tempo) and tempo > 0:
                return tempo
            raise MusicXMLParseError("MusicXML metronome tempo must be positive and finite.")

    return 120.0


def _title(root: ElementTree.Element) -> str:
    for parent_name in ("work", "movement-title"):
        if parent_name == "movement-title":
            value = _text(root, parent_name)
        else:
            parent = next((element for element in root if _local_name(element.tag) == parent_name), None)
            value = _text(parent, "work-title") if parent is not None else None
        if value:
            return value
    return "Untitled exercise"


def _attributes(measure: ElementTree.Element) -> tuple[int | None, int | None, int | None]:
    attributes = _child(measure, "attributes")
    if attributes is None:
        return None, None, None
    divisions = _optional_int(attributes, "divisions")
    time = _child(attributes, "time")
    beats = _optional_int(time, "beats") if time is not None else None
    beat_type = _optional_int(time, "beat-type") if time is not None else None
    return divisions, beats, beat_type


def _technical(note: ElementTree.Element) -> tuple[int | None, int | None]:
    technical = next((element for element in note.iter() if _local_name(element.tag) == "technical"), None)
    if technical is None:
        return None, None
    string = _optional_int(technical, "string")
    fret = _optional_int(technical, "fret")
    return string, fret


def _unpitched(note: ElementTree.Element) -> tuple[str | None, int | None]:
    """Extract display-step/display-octave from an unpitched (percussion) note.

    The evaluator never turns a drum into a pitch; it uses these as the drum
    identity the score writer chose, mirroring how guitar tab carries string/
    fret that audio alone cannot hear.
    """
    unpitched = _child(note, "unpitched")
    if unpitched is None:
        return None, None
    step = _text(unpitched, "display-step")
    octave = _optional_int(unpitched, "display-octave")
    return step, octave


def _direction_marks(direction: ElementTree.Element, onset_beats: float) -> list[DynamicMark]:
    """Read dynamics and hairpins out of one `<direction>`.

    Everything unrecognised is ignored rather than rejected. `<direction>` is
    where scores put tempo text, rehearsal marks, pedalling, fingering hints and
    free `<words>`; raising on the first one we do not model would fail nearly
    every real-world score for the crime of being expressive.
    """
    marks: list[DynamicMark] = []
    for direction_type in _children(direction, "direction-type"):
        for child in direction_type:
            name = _local_name(child.tag)
            if name == "dynamics":
                for mark in child:
                    label = _local_name(mark.tag)
                    if label in DYNAMIC_LEVELS:
                        marks.append(
                            DynamicMark(onset_beats=onset_beats, mark=label, kind="level",
                                        level=DYNAMIC_LEVELS[label])
                        )
            elif name == "wedge":
                wedge = child.attrib.get("type", "")
                if wedge in {"crescendo", "diminuendo"}:
                    marks.append(DynamicMark(onset_beats=onset_beats, mark=wedge, kind="hairpin_start"))
                elif wedge == "stop":
                    marks.append(DynamicMark(onset_beats=onset_beats, mark="stop", kind="hairpin_stop"))

    # `<sound dynamics="NN">` is a percentage of forte, and is how exported
    # scores carry a level with no printed marking.
    sound = _child(direction, "sound")
    if sound is not None:
        raw = sound.attrib.get("dynamics")
        if raw is not None:
            try:
                percentage = float(raw)
            except ValueError as exc:
                raise MusicXMLParseError(f"Invalid sound dynamics value: {raw!r}.") from exc
            level = max(0.0, min(1.0, percentage / 100.0 * DYNAMIC_LEVELS["f"]))
            marks.append(DynamicMark(onset_beats=onset_beats, mark="sound", kind="level", level=level))
    return marks


# @spec EVAL-NOTE-001, EVAL-NOTE-002, EVAL-NOTE-003, EVAL-NOTE-004, EVAL-NOTE-006, EVAL-NOTE-007, EVAL-NOTE-008
def parse_musicxml(payload: bytes | str) -> MusicXMLScore:
    """Parse a score-partwise MusicXML payload into canonical events.

    The first evaluator intentionally supports one part and simple measure
    cursor operations (`backup`, `forward`, and chord notes). Multiple voices
    are preserved as metadata; their events share the part's absolute beat
    cursor, which is enough for the initial monophonic piano exercises.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise MusicXMLParseError("MusicXML is not well-formed XML.") from exc

    if _local_name(root.tag) != "score-partwise":
        raise MusicXMLParseError("Only score-partwise MusicXML is supported.")

    parts = [element for element in root if _local_name(element.tag) == "part"]
    if not parts:
        raise MusicXMLParseError("MusicXML score contains no part.")
    if len(parts) > 1:
        raise MusicXMLParseError("The initial piano evaluator supports one MusicXML part.")

    part = parts[0]
    divisions = 1
    beats_per_measure: int | None = None
    beat_type: int | None = None
    absolute_measure_start = 0.0
    notes: list[ScoreNote] = []
    dynamics: list[DynamicMark] = []
    previous_onset: float | None = None

    for measure in _children(part, "measure"):
        measure_cursor = 0.0
        measure_max = 0.0
        local_divisions, local_beats, local_beat_type = _attributes(measure)
        if local_divisions is not None:
            if local_divisions <= 0:
                raise MusicXMLParseError("MusicXML divisions must be positive.")
            divisions = local_divisions
        if local_beats is not None:
            beats_per_measure = local_beats
        if local_beat_type is not None:
            beat_type = local_beat_type

        for child in measure:
            name = _local_name(child.tag)
            if name == "direction":
                dynamics.extend(_direction_marks(child, absolute_measure_start + measure_cursor))
            elif name in {"attributes", "barline", "print", "figured-bass"}:
                pass
            elif name == "backup":
                duration = _required_int(child, "duration")
                measure_cursor -= duration / divisions
                if measure_cursor < 0:
                    raise MusicXMLParseError("MusicXML backup moves before the measure start.")
            elif name == "forward":
                duration = _required_int(child, "duration")
                measure_cursor += duration / divisions
                measure_max = max(measure_max, measure_cursor)
            elif name == "note":
                duration_units = _required_int(child, "duration")
                duration_beats = duration_units / divisions
                if duration_beats <= 0:
                    raise MusicXMLParseError("MusicXML note duration must be positive.")
                is_chord = _child(child, "chord") is not None
                onset = previous_onset if is_chord and previous_onset is not None else measure_cursor
                pitch = _child(child, "pitch")
                pitch_midi = _pitch_midi(pitch) if pitch is not None else None
                string, fret = _technical(child)
                unpitched_step, unpitched_octave = _unpitched(child)
                notes.append(
                    ScoreNote(
                        pitch_midi=pitch_midi,
                        onset_beats=absolute_measure_start + onset,
                        duration_beats=duration_beats,
                        voice=_text(child, "voice") or "1",
                        staff=_optional_int(child, "staff"),
                        string=string,
                        fret=fret,
                        unpitched_step=unpitched_step,
                        unpitched_octave=unpitched_octave,
                    )
                )
                previous_onset = onset
                if not is_chord:
                    measure_cursor += duration_beats
                measure_max = max(measure_max, onset + duration_beats)
            else:
                raise MusicXMLParseError(f"Unsupported MusicXML measure element: {name!r}.")

        measure_length = measure_max
        if beats_per_measure is not None and beat_type is not None:
            measure_length = max(measure_length, beats_per_measure * 4 / beat_type)
        absolute_measure_start += measure_length
        previous_onset = None

    if not notes:
        raise MusicXMLParseError("MusicXML score contains no notes.")

    ordered_notes = tuple(sorted(notes, key=lambda note: (note.onset_beats, note.voice, note.pitch_midi is None)))
    duration_beats = max(note.onset_beats + note.duration_beats for note in ordered_notes)
    return MusicXMLScore(
        title=_title(root),
        tempo_bpm=_tempo(root),
        divisions=divisions,
        beats_per_measure=beats_per_measure,
        beat_type=beat_type,
        notes=ordered_notes,
        duration_beats=duration_beats,
        dynamics=tuple(sorted(dynamics, key=lambda mark: mark.onset_beats)),
    )


PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_to_note_name(pitch_midi: int) -> str:
    """Turn a MIDI number into an octave-qualified pitch name (e.g. 60 -> C4, 69 -> A4)."""
    return f"{PITCH_NAMES[pitch_midi % 12]}{(pitch_midi // 12) - 1}"

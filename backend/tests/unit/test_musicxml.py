"""MusicXML normalization is the contract between score assets and scoring."""

from __future__ import annotations

import pytest

from app.evaluation.musicxml import MusicXMLParseError, parse_musicxml

SCORE = b"""
<score-partwise version="4.0">
  <work><work-title>Quarter Steps</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>2</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice></note>
      <note><rest/><duration>2</duration><voice>1</voice></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice></note>
    </measure>
    <measure number="2">
      <note>
        <pitch><step>G</step><alter>1</alter><octave>3</octave></pitch>
        <duration>2</duration><voice>1</voice>
        <notations><technical><string>1</string><fret>4</fret></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def test_musicxml_normalizes_tempo_notes_rests_and_technical_metadata() -> None:
    score = parse_musicxml(SCORE)

    assert score.title == "Quarter Steps"
    assert score.tempo_bpm == 120
    assert score.beats_per_measure == 4
    assert score.beat_type == 4
    assert score.duration_beats == 5
    assert [note.pitch_midi for note in score.notes] == [60, 62, None, 64, 56]
    assert [note.onset_beats for note in score.notes] == [0, 1, 2, 3, 4]
    assert score.notes[-1].string == 1
    assert score.notes[-1].fret == 4
    assert [note.pitch_midi for note in score.pitched_notes] == [60, 62, 64, 56]


def test_musicxml_rejects_malformed_and_unsupported_scores() -> None:
    with pytest.raises(MusicXMLParseError, match="well-formed"):
        parse_musicxml(b"<score-partwise>")
    with pytest.raises(MusicXMLParseError, match="score-partwise"):
        parse_musicxml(b"<score-timewise />")
    with pytest.raises(MusicXMLParseError, match="no part"):
        parse_musicxml(b"<score-partwise />")

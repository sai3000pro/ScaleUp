"""A small piano tree with the two pathologies a graph writer has to survive.

Owned by the tests rather than by the seed. It carries a transitively implied
edge and a back-edge that would close a cycle, at fixed confidences, because
greedy admission by confidence is exactly what decides which edge loses. A
graph owned elsewhere can have those properties tuned out from under these
assertions by someone improving a curriculum.
"""

from __future__ import annotations

from app.domain.dag import CandidateEdge
from app.services.graph_service import ConceptSpec

CONCEPTS: list[ConceptSpec] = [
    ConceptSpec("note-names", "Note Names", "Name the pitches on the staff and on the keyboard.", 1),
    ConceptSpec("reading-rhythm", "Reading Rhythm", "Read note durations as a pattern in time.", 1),
    ConceptSpec("keyboard-geography", "Keyboard Geography", "Find any note by the black-key groups around it.", 1),
    ConceptSpec("steady-pulse", "Steady Pulse", "Hold an even beat without drifting.", 2),
    ConceptSpec("note-values", "Note Values", "Play halves, quarters and eighths against that beat.", 2),
    ConceptSpec("rests", "Rests", "Count silence as deliberately as sound.", 3),
    ConceptSpec("hand-position", "Hand Position", "Keep a rounded, relaxed hand over five adjacent keys.", 2),
    ConceptSpec("scales", "Scales", "Play a major scale as a pattern of tones and semitones.", 2),
    ConceptSpec("scale-fingering", "Scale Fingering", "Pass the thumb under so a scale crosses octaves evenly.", 3),
    ConceptSpec("arpeggios", "Arpeggios", "Play a chord one note at a time across the keyboard.", 3),
    ConceptSpec("triads", "Triads", "Build and recognise three-note chords from scale degrees.", 3),
    ConceptSpec("broken-chords", "Broken Chords", "Voice a triad as a moving figure rather than a block.", 4),
    ConceptSpec("phrasing", "Phrasing", "Shape a line so it has a direction and an end.", 4),
    ConceptSpec("dynamics", "Dynamics", "Control volume as an expressive choice, not an accident.", 5),
    ConceptSpec("cadences", "Cadences", "Close a phrase with a chord movement that sounds finished.", 5),
]

EDGES: list[CandidateEdge] = [
    CandidateEdge("note-names", "reading-rhythm", 0.95),
    CandidateEdge("note-names", "keyboard-geography", 0.94),
    CandidateEdge("reading-rhythm", "steady-pulse", 0.97),
    CandidateEdge("steady-pulse", "note-values", 0.93),
    CandidateEdge("steady-pulse", "rests", 0.94),
    CandidateEdge("keyboard-geography", "hand-position", 0.96),
    CandidateEdge("hand-position", "scales", 0.90),
    CandidateEdge("hand-position", "phrasing", 0.90),
    CandidateEdge("phrasing", "dynamics", 0.95),
    CandidateEdge("scales", "scale-fingering", 0.96),
    CandidateEdge("steady-pulse", "scale-fingering", 0.92),
    CandidateEdge("scale-fingering", "arpeggios", 0.88),
    CandidateEdge("scale-fingering", "triads", 0.89),
    CandidateEdge("arpeggios", "broken-chords", 0.91),
    CandidateEdge("broken-chords", "cadences", 0.85),
    # Genuinely implied by triads -> broken-chords -> cadences, and asserted as
    # such: an extractor states both, and only one of them should be rendered.
    CandidateEdge("triads", "broken-chords", 0.87),
    CandidateEdge("triads", "cadences", 0.93),
    # Planted shortcut, implied by keyboard-geography -> hand-position -> scales.
    CandidateEdge("keyboard-geography", "scales", 0.70),
    # Would close a cycle: steady-pulse already reaches cadences through
    # scale-fingering and triads. Lowest confidence, so it is the edge greedy
    # admission gives up.
    CandidateEdge("cadences", "steady-pulse", 0.38),
]

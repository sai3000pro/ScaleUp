"""Deterministic performance evaluation primitives."""

from app.evaluation.drums import DrumHit, DrumsPerformanceScore, score_drums_performance
from app.evaluation.dtw import AlignmentStep, DTWAlignment, align
from app.evaluation.guitar import (
    GuitarNote,
    GuitarPerformanceScore,
    score_guitar_chords_performance,
    score_guitar_performance,
)
from app.evaluation.musicxml import MusicXMLParseError, MusicXMLScore, ScoreNote, parse_musicxml
from app.evaluation.piano import PerformedNote, PianoPerformanceScore, score_performance
from app.evaluation.trumpet import score_trumpet_performance
from app.evaluation.violin import ViolinNote, ViolinPerformanceScore, score_violin_performance

__all__ = [
    "AlignmentStep",
    "DTWAlignment",
    "DrumHit",
    "DrumsPerformanceScore",
    "GuitarNote",
    "GuitarPerformanceScore",
    "MusicXMLParseError",
    "MusicXMLScore",
    "PerformedNote",
    "PianoPerformanceScore",
    "ScoreNote",
    "ViolinNote",
    "ViolinPerformanceScore",
    "align",
    "parse_musicxml",
    "score_drums_performance",
    "score_guitar_chords_performance",
    "score_guitar_performance",
    "score_performance",
    "score_trumpet_performance",
    "score_violin_performance",
]

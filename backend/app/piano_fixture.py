"""Compatibility names for the data-defined piano curriculum.

New code should use ``load_curriculum("piano")`` directly. These aliases keep the
existing seed/test seam stable while moving the actual tree out of Python code.
"""

from __future__ import annotations

from app.curricula.loader import CurriculumConcept, load_curriculum
from app.domain.dag import CandidateEdge

PIANO_CURRICULUM = load_curriculum("piano")
PIANO_CONCEPTS: tuple[CurriculumConcept, ...] = PIANO_CURRICULUM.concepts
PIANO_EDGES: tuple[CandidateEdge, ...] = PIANO_CURRICULUM.edges

__all__ = ["PIANO_CONCEPTS", "PIANO_CURRICULUM", "PIANO_EDGES"]

"""Embedding vectors.

Similarity thresholds only mean the same thing for every provider if the
vectors reaching them are unit length, so normalisation lives in one pure
function the gateway applies at the seam.

# @spec LLM-EMBED-004
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["unit_normalise"]


# @spec LLM-EMBED-004
def unit_normalise(vector: Sequence[float]) -> list[float]:
    """Scale `vector` to unit length. A zero vector has no direction and returns zeros."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [x / norm for x in vector]

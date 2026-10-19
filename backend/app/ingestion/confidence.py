"""The one statement of how edge kinds rank against each other.

`build_acyclic_edges` admits edges greedily by descending confidence, so these
numbers decide who wins a cycle contest. Read them as a ladder, lowest first:

    outline (INTRODUCES)  <  inferred floor (MIN)  <  reverse-pass floor
      <  catalogue default  <  backwards floor  <  inferred ceiling (single)
      <  inferred ceiling (agreed)

A structural edge is an inference from where material was printed; a prose
edge is evidence about the material, so prose outranks structure. Agreement
between the two inference passes is worth more than either alone, and an edge
running against the book's order needs more than a passing lexical match.
"""

from __future__ import annotations

INTRODUCES_CONFIDENCE = 0.45
MIN_CONFIDENCE = 0.5
REVERSE_MIN_CONFIDENCE = 0.6
CATALOGUE_DEFAULT_CONFIDENCE = 0.8
BACKWARD_MIN_CONFIDENCE = 0.8
MAX_SINGLE_CONFIDENCE = 0.85
MAX_AGREED_CONFIDENCE = 0.9

# Ascending. Equal neighbours are allowed; a descent is a bug.
# @spec CURR-EDGE-007
CONFIDENCE_LADDER: tuple[tuple[str, float], ...] = (
    ("outline_introduces", INTRODUCES_CONFIDENCE),
    ("inferred_floor", MIN_CONFIDENCE),
    ("reverse_pass_floor", REVERSE_MIN_CONFIDENCE),
    ("catalogue_default", CATALOGUE_DEFAULT_CONFIDENCE),
    ("backwards_floor", BACKWARD_MIN_CONFIDENCE),
    ("inferred_ceiling_single", MAX_SINGLE_CONFIDENCE),
    ("inferred_ceiling_agreed", MAX_AGREED_CONFIDENCE),
)


def ladder_is_ordered(ladder: tuple[tuple[str, float], ...] = CONFIDENCE_LADDER) -> bool:
    values = [value for _, value in ladder]
    return all(earlier <= later for earlier, later in zip(values, values[1:]))


assert ladder_is_ordered(), "edge-confidence ladder is out of order"

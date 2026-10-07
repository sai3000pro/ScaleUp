"""The prompt wire formats, rendered and parsed in one place.

Every prompt that shows the model a machine-readable listing has the same
shape on both ends: a renderer builds it, and the deterministic provider
reads it back so it exercises the real code path rather than a shortcut. The
render function and the parse regex for each format live side by side here,
because they must round-trip -- a pair that drifts apart makes the fake's
answer nonsense silently instead of failing.

# @spec LLM-FAKE-008
"""

from __future__ import annotations

import re

__all__ = [
    "CANDIDATE_HEAD",
    "PASSAGE_BLOCK",
    "RUBRIC_LINE",
    "SEGMENT_FRAGMENT",
    "SEGMENT_LEAD_IN_NAME",
    "SKILL_LINE",
    "candidate_head",
    "fragment_block",
    "passage_block",
    "rubric_line",
    "skill_line",
]

# ── drill rubric ──────────────────────────────────────────────────────────
# `kp1: <point text> (weight 0.5)` -- one line per rubric point. Must round-trip.


# @spec LLM-FAKE-008
def rubric_line(point_id: str, point: str, weight: object) -> str:
    return f"{point_id}: {point} (weight {weight})"


RUBRIC_LINE = re.compile(r"^\s*(kp[0-9]+)\s*:\s*(.*?)\s*(?:\(weight[^)]*\))?\s*$", re.IGNORECASE)

# ── section fragments ─────────────────────────────────────────────────────
# `[fragment 3] lead-in: Definition: Subgradient` followed by the fragment's
# text. The caller supplies the lead-in label and any truncation. Must round-trip.


# @spec LLM-FAKE-008
def fragment_block(ordinal: int, lead_in: str, text: str) -> str:
    return f"[fragment {ordinal}] lead-in: {lead_in}\n{text}"


SEGMENT_FRAGMENT = re.compile(
    r"^\[fragment (\d+)\] lead-in: ([^\n]*)\n(.*?)(?=^\[fragment \d+\] lead-in:|\Z)",
    re.M | re.S,
)
# The part of a lead-in after `:` or a dash -- the name the author already wrote.
SEGMENT_LEAD_IN_NAME = re.compile(r"^[A-Za-z]+\s*\d*(?:\.\d+)*\s*[:–—-]\s*(\S.*)$")

# ── skill listing ─────────────────────────────────────────────────────────
# `- `slug` — **title** — summary`: the title is delimited, not merely
# separated, so a title containing a colon or a dash still parses. Must
# round-trip.


# @spec LLM-FAKE-008
def skill_line(slug: str, title: str, summary: str) -> str:
    return f"- `{slug}` — **{title}** — {summary}"


SKILL_LINE = re.compile(r"^-\s*`([a-z0-9-]+)`\s*—\s*\*\*(.+?)\*\*\s*—\s*(.*)$")

# ── candidate / brief blocks ──────────────────────────────────────────────
# `### `slug` — Title` heads a block of excerpt text. Used by the reverse
# prereq prompt and the node-summary prompt alike. Must round-trip.


# @spec LLM-FAKE-008
def candidate_head(slug: str, title: str) -> str:
    return f"### `{slug}` — {title}"


CANDIDATE_HEAD = re.compile(r"^###\s*`([a-z0-9-]+)`\s*—\s*(.+)$", re.M)

# ── QA passages ───────────────────────────────────────────────────────────
# The candidate head plus the ids the model is asked to cite back, then the
# passage. The ids are printed in full because a citation only counts if it
# resolves. Must round-trip.


# @spec LLM-FAKE-008
def passage_block(slug: str, title: str, node_id: object, chunk_id: object, text: str) -> str:
    return f"{candidate_head(slug, title)}\nnode_id: {node_id}\nchunk_id: {chunk_id}\n{text}"


PASSAGE_BLOCK = re.compile(
    r"^###\s*`([a-z0-9-]+)`\s*—\s*(.+?)\n\s*node_id:\s*(\S+)\n\s*chunk_id:\s*(\S+)\n(.*?)(?=^###\s*`|\Z)",
    re.M | re.S,
)

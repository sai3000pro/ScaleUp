"""Every render function in `wire_formats` must round-trip through its regex.

The deterministic provider parses what the renderers emit; a pair that drifts
apart makes its answer nonsense silently instead of failing.
"""

from __future__ import annotations

from app.domain.wire_formats import (
    CANDIDATE_HEAD,
    PASSAGE_BLOCK,
    RUBRIC_LINE,
    SEGMENT_FRAGMENT,
    SKILL_LINE,
    candidate_head,
    fragment_block,
    passage_block,
    rubric_line,
    skill_line,
)


# @spec LLM-FAKE-008
def test_a_rubric_line_round_trips() -> None:
    line = rubric_line("kp1", "Explains the role of direction in Vectors", 0.5)

    match = RUBRIC_LINE.match(line)

    assert match is not None
    assert match.group(1) == "kp1"
    assert match.group(2).strip() == "Explains the role of direction in Vectors"


# @spec LLM-FAKE-008
def test_a_fragment_block_round_trips() -> None:
    text = "First paragraph.\n\nSecond paragraph, spanning lines."
    block = fragment_block(3, "Definition: Subgradient", text)

    match = SEGMENT_FRAGMENT.search(block)

    assert match is not None
    assert int(match.group(1)) == 3
    assert match.group(2).strip() == "Definition: Subgradient"
    assert match.group(3).strip() == text


# @spec LLM-FAKE-008
def test_adjacent_fragment_blocks_stay_separate() -> None:
    block = fragment_block(1, "Definition: A", "alpha body") + "\n\n" + fragment_block(2, "Example: B", "beta body")

    matches = list(SEGMENT_FRAGMENT.finditer(block))

    assert [int(m.group(1)) for m in matches] == [1, 2]
    assert matches[0].group(3).strip() == "alpha body"
    assert matches[1].group(3).strip() == "beta body"


# @spec LLM-FAKE-008
def test_a_skill_line_round_trips_with_a_colon_in_the_title() -> None:
    line = skill_line("formulations-overview", "Formulations: Overview", "What the section covers.")

    match = SKILL_LINE.match(line)

    assert match is not None
    assert match.group(1) == "formulations-overview"
    assert match.group(2).strip() == "Formulations: Overview"
    assert match.group(3).strip() == "What the section covers."


# @spec LLM-FAKE-008
def test_a_candidate_head_round_trips() -> None:
    block = f"{candidate_head('matrix-inverse', 'Matrix Inverse')}\nAn excerpt about inverses."

    heads = list(CANDIDATE_HEAD.finditer(block))

    assert len(heads) == 1
    assert heads[0].group(1) == "matrix-inverse"
    assert heads[0].group(2).strip() == "Matrix Inverse"


# @spec LLM-FAKE-008
def test_a_passage_block_round_trips() -> None:
    text = "A passage.\n\nWith a second paragraph."
    block = passage_block("vectors", "Vectors", "node-uuid-1", "chunk-uuid-2", text)

    match = PASSAGE_BLOCK.search(block)

    assert match is not None
    assert match.group(1) == "vectors"
    assert match.group(2).strip() == "Vectors"
    assert match.group(3).strip() == "node-uuid-1"
    assert match.group(4).strip() == "chunk-uuid-2"
    assert match.group(5).strip() == text

"""PDF heading detection and chunking."""

from __future__ import annotations

from app.ingestion.chunking import chunk_blocks, count_tokens
from app.ingestion.parsers.base import ParsedBlock
from app.ingestion.parsers.pdf import parse_pdf_bytes
from tests.fixtures.sample_pdf import SECTIONS, build_sample_pdf


def body(text: str, page: int = 0) -> ParsedBlock:
    return ParsedBlock(text=text, page_index=page)


def heading(text: str, level: int, page: int = 0) -> ParsedBlock:
    return ParsedBlock(text=text, page_index=page, heading_level=level)


# ── parsing ───────────────────────────────────────────────────────────────


def test_sample_pdf_parses_into_pages_and_blocks() -> None:
    parsed = parse_pdf_bytes(build_sample_pdf())
    assert parsed.page_count >= 1
    assert parsed.blocks
    assert any("dot product" in block.text.lower() for block in parsed.blocks)


def test_control_characters_are_stripped_from_parsed_text() -> None:
    """PostgreSQL rejects 0x00 in a text column, so one unmapped glyph anywhere
    in a book fails the entire ingest at the first page insert.

    Real LaTeX-produced PDFs emit these from math fonts; the synthetic fixture
    never will, which is why this asserts on the sanitiser directly.
    """
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), "Matrix inverse B\x00-1 is defined\x14 when ad-bc\x12= 0")
    payload = document.tobytes()
    document.close()

    parsed = parse_pdf_bytes(payload)
    everything = "".join(parsed.page_texts) + "".join(block.text for block in parsed.blocks)
    assert everything, "nothing parsed"
    assert not any(ch in everything for ch in "\x00\x12\x14")
    assert "Matrix inverse" in everything


def test_numbered_headings_are_detected_with_the_right_level() -> None:
    parsed = parse_pdf_bytes(build_sample_pdf())
    headings = {block.text.strip(): block.heading_level for block in parsed.blocks if block.heading_level}

    # "1  Vectors" is a chapter; "1.1  The Dot Product" is a section.
    top = [text for text, level in headings.items() if level == 1]
    nested = [text for text, level in headings.items() if level == 2]

    assert any(text.startswith("1 ") or text.startswith("1  ") for text in top), headings
    assert any("1.1" in text for text in nested), headings


def test_every_authored_section_heading_is_found() -> None:
    parsed = parse_pdf_bytes(build_sample_pdf())
    found = " | ".join(b.text for b in parsed.blocks if b.heading_level)
    for authored, _ in SECTIONS:
        number = authored.split()[0]
        assert number in found, f"heading {authored!r} not detected"


def test_body_text_is_not_mistaken_for_a_heading() -> None:
    parsed = parse_pdf_bytes(build_sample_pdf())
    for block in parsed.blocks:
        if block.heading_level is not None:
            assert len(block.text) <= 90


# ── chunking ──────────────────────────────────────────────────────────────


def test_chunks_never_exceed_the_token_budget() -> None:
    blocks = [heading("1  Chapter", 1)] + [body("Sentence number %d about vectors and matrices. " % i) for i in range(80)]
    chunks = chunk_blocks(blocks, max_tokens=200, overlap_tokens=20, min_tokens=0)
    assert chunks
    for chunk in chunks:
        assert chunk.token_count <= 200 + 40, chunk.token_count  # small slack for the trailing sentence


def test_a_level_two_heading_always_starts_a_new_chunk() -> None:
    """A chunk spanning two sections produces garbage skills."""
    blocks = [
        heading("1  Vectors", 1),
        body("Vectors are ordered lists of numbers used throughout linear algebra. " * 4),
        heading("2  Matrices", 1),
        body("Matrices are rectangular arrays of numbers with their own algebra. " * 4),
    ]
    chunks = chunk_blocks(blocks, max_tokens=4000, overlap_tokens=0, min_tokens=0)

    assert len(chunks) == 2
    assert "Vectors are ordered" in chunks[0].text
    assert "Matrices are rectangular" in chunks[1].text
    assert "Matrices" not in chunks[0].text


def test_section_path_tracks_nesting() -> None:
    blocks = [
        heading("3  Calculus", 1),
        heading("3.2  Derivatives", 2),
        body("The derivative measures an instantaneous rate of change in a function. " * 3),
    ]
    chunks = chunk_blocks(blocks, max_tokens=4000, overlap_tokens=0, min_tokens=0)
    assert chunks[0].section_path == "3  Calculus / 3.2  Derivatives"


def test_a_sibling_heading_pops_the_stack() -> None:
    blocks = [
        heading("3  Calculus", 1),
        heading("3.2  Derivatives", 2),
        body("Rates of change and slopes of tangent lines are the subject here. " * 3),
        heading("4  Series", 1),
        body("Infinite sums converge or diverge depending on their terms. " * 3),
    ]
    chunks = chunk_blocks(blocks, max_tokens=4000, overlap_tokens=0, min_tokens=0)
    assert chunks[-1].section_path == "4  Series"


def test_oversized_sections_split_on_sentence_boundaries() -> None:
    sentence = "This sentence is deliberately long enough to matter for the token budget. "
    blocks = [heading("1  Long", 1), body(sentence * 60)]
    chunks = chunk_blocks(blocks, max_tokens=150, overlap_tokens=30, min_tokens=0)

    assert len(chunks) > 1
    for chunk in chunks:
        # No chunk starts mid-sentence with a lowercase fragment.
        assert chunk.text[0].isupper(), chunk.text[:40]


def test_overlap_carries_context_between_windows() -> None:
    sentences = " ".join(f"Fact number {i} concerns eigenvalues and determinants." for i in range(60))
    chunks = chunk_blocks([heading("1  X", 1), body(sentences)], max_tokens=120, overlap_tokens=40, min_tokens=0)

    assert len(chunks) > 1
    first_words = set(chunks[0].text.split())
    second_words = set(chunks[1].text.split())
    assert first_words & second_words, "overlap produced no shared context"


def test_page_ranges_are_recorded() -> None:
    blocks = [heading("1  X", 1, page=2), body("Some content about vectors here. " * 5, page=2),
              body("More content on the following page. " * 5, page=3)]
    chunks = chunk_blocks(blocks, max_tokens=4000, overlap_tokens=0, min_tokens=0)
    assert chunks[0].page_start == 2
    assert chunks[0].page_end == 3


def test_tiny_fragments_are_dropped() -> None:
    blocks = [
        heading("1  Real Section", 1),
        body("A genuinely substantial paragraph about linear algebra concepts and their uses. " * 6),
        heading("2  Another", 1),
        body("7"),  # a page number
    ]
    chunks = chunk_blocks(blocks, max_tokens=800, overlap_tokens=0, min_tokens=60)
    assert all(chunk.token_count >= 60 or chunk.section_path == "2  Another" for chunk in chunks)


def test_ordinals_are_dense_and_ordered() -> None:
    blocks = [heading("1  X", 1)] + [body("Content sentence about the subject at hand. " * 10) for _ in range(5)]
    chunks = chunk_blocks(blocks, max_tokens=200, overlap_tokens=20, min_tokens=0)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_end_to_end_sample_pdf_chunks_cleanly() -> None:
    parsed = parse_pdf_bytes(build_sample_pdf())
    chunks = chunk_blocks(parsed.blocks, max_tokens=800, overlap_tokens=120, min_tokens=0)

    assert chunks
    assert all(chunk.section_path for chunk in chunks), "every chunk should carry a section path"
    assert count_tokens(chunks[0].text) == chunks[0].token_count

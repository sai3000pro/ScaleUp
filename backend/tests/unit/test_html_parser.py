"""HTML parsing, boilerplate removal, and synthetic pagination.

Offline by construction: every input is a byte string built in the test process.
"""

from __future__ import annotations

from app.ingestion.chunking import chunk_blocks
from app.ingestion.parsers.clean import normalise_html_text, sanitise
from app.ingestion.parsers.detect import sniff_source_type
from app.ingestion.parsers.html import PAGE_CHARS, decode_html, document_title, parse_html_bytes
from app.ingestion.parsers.registry import (
    UnsupportedSourceError,
    parse_source_bytes,
    storage_extension,
)
from app.ingestion.toc import build_toc_nodes, is_drillable, owner_of_page
from tests.fixtures.sample_html import (
    BOILERPLATE_MARKERS,
    SECTIONS,
    build_flat_html,
    build_long_section_html,
    build_sample_html,
)
from tests.fixtures.sample_pdf import build_sample_pdf

# ── the two pagination invariants ─────────────────────────────────────────
#
# These are the tests that protect `toc.owner_of_page` and
# `toc.build_toc_nodes.next_boundary`. If either fails, headings share a page
# index, their ranges coincide, the deeper one takes every chunk, and
# `is_drillable` silently turns the shallower one into a structural node.


def _all_fixtures() -> list[bytes]:
    return [
        build_sample_html(),
        build_flat_html(),
        build_flat_html("h2", sections=3),
        build_long_section_html(),
        build_long_section_html(paragraphs=200),
        b"<html><body><h1>A</h1><h2>B</h2><h3>C</h3><p>Only prose at the very end.</p></body></html>",
        b"<html><body><p>No headings at all, just a wall of prose.</p></body></html>",
    ]


def test_invariant_every_heading_starts_a_page() -> None:
    """A heading must be the FIRST block on its page.

    `next_boundary` advances only past an entry with a strictly greater page
    index, so a heading that shares a page with the block before it inherits
    that block's owner's range as well as its own.
    """
    for payload in _all_fixtures():
        parsed = parse_html_bytes(payload)
        first_on_page: dict[int, int] = {}
        for position, block in enumerate(parsed.blocks):
            first_on_page.setdefault(block.page_index, position)

        for position, block in enumerate(parsed.blocks):
            if block.heading_level is not None:
                assert first_on_page[block.page_index] == position, (
                    f"heading {block.text!r} is not first on page {block.page_index}"
                )


def test_invariant_no_page_holds_two_headings() -> None:
    """`owner_of_page` gives a chunk to the DEEPEST node containing it.

    Two headings on one page produce two nodes with identical ranges, the deeper
    takes every chunk, and the shallower becomes un-drillable. Every heading on
    page 0 would do that to the entire graph.
    """
    for payload in _all_fixtures():
        parsed = parse_html_bytes(payload)
        per_page: dict[int, list[str]] = {}
        for block in parsed.blocks:
            if block.heading_level is not None:
                per_page.setdefault(block.page_index, []).append(block.text)

        for page, headings in per_page.items():
            assert len(headings) == 1, f"page {page} holds {headings}"


def test_toc_page_indices_are_strictly_increasing() -> None:
    """The consequence of both invariants, stated the way the TOC builder needs it."""
    for payload in _all_fixtures():
        pages = [entry.page_index for entry in parse_html_bytes(payload).toc]
        assert pages == sorted(pages)
        assert len(pages) == len(set(pages))


def test_every_heading_owns_at_least_one_page_exclusively() -> None:
    """The invariants' payoff: no HTML outline node is structural by accident.

    A container is a legitimate outcome for a PDF chapter whose first section
    starts on its own opening page. In HTML it would be a pagination bug, since
    every heading is given a page that only it can start.
    """
    parsed = parse_html_bytes(build_sample_html())
    nodes = build_toc_nodes(parsed.toc, parsed.page_count)
    assert nodes

    owned = {node.slug: 0 for node in nodes}
    for page in range(parsed.page_count):
        owner = owner_of_page(nodes, page)
        if owner is not None:
            owned[owner.slug] += 1

    for node in nodes:
        assert is_drillable(node, owned[node.slug]), f"{node.title} owns no page"


def test_a_long_section_spills_onto_headless_continuation_pages() -> None:
    parsed = parse_html_bytes(build_long_section_html(paragraphs=60))
    assert parsed.page_count > 1, "a 60-paragraph section should not fit on one page"
    assert len(parsed.toc) == 1
    assert parsed.toc[0].page_index == 0
    for text in parsed.page_texts:
        assert len(text) <= PAGE_CHARS * 2, "a page grew unbounded"


def test_pages_never_split_mid_block() -> None:
    parsed = parse_html_bytes(build_long_section_html(paragraphs=30))
    for block in parsed.blocks:
        assert block.text in parsed.page_texts[block.page_index]


# ── heading levels ────────────────────────────────────────────────────────


def test_heading_levels_are_dense_ranked_over_observed_tags() -> None:
    """h1/h2/h3 in the fixture -> 1/2/3, with no gaps."""
    parsed = parse_html_bytes(build_sample_html())
    levels = {entry.title: entry.level for entry in parsed.toc}

    assert levels["Linear Algebra, Abridged"] == 1
    assert levels["Vectors"] == 2
    assert levels["The Dot Product"] == 3
    assert levels["Matrices"] == 2


def test_an_h3_only_page_still_produces_level_one() -> None:
    """Without dense ranking, `HARD_BOUNDARY_LEVEL = 2` never fires here.

    A blog that reserves h1 and h2 for the site template and writes its sections
    as h3 would otherwise get no hard chunk boundary anywhere in the document,
    and one chunk could span every section it has.
    """
    parsed = parse_html_bytes(build_flat_html("h3", sections=4))
    assert {entry.level for entry in parsed.toc} == {1}

    chunks = chunk_blocks(parsed.blocks, max_tokens=4000, overlap_tokens=0, min_tokens=0)
    assert len(chunks) == 4, "a level-1 heading must hard-split the chunk stream"


def test_h4_and_h6_only_rank_to_one_and_two() -> None:
    payload = (
        b"<html><body><article>"
        b"<h4>Alpha</h4><p>Alpha is discussed at some length right here.</p>"
        b"<h6>Alpha detail</h6><p>The detail under alpha, also at some length.</p>"
        b"<h4>Beta</h4><p>Beta is discussed at some length right here too.</p>"
        b"</article></body></html>"
    )
    levels = {entry.title: entry.level for entry in parse_html_bytes(payload).toc}
    assert levels == {"Alpha": 1, "Alpha detail": 2, "Beta": 1}


# ── boilerplate ───────────────────────────────────────────────────────────


def test_boilerplate_appears_in_no_block_no_page_and_no_chunk() -> None:
    """The three surfaces a learner can actually reach.

    Asserting on blocks alone would pass a parser that strips a nav from the
    block list but leaves it in `page_texts`, which is what `document_pages`
    stores and what the printed-contents fallback reads.
    """
    parsed = parse_html_bytes(build_sample_html())
    chunks = chunk_blocks(parsed.blocks, max_tokens=800, overlap_tokens=120, min_tokens=0)

    haystacks = {
        "blocks": " ".join(block.text for block in parsed.blocks),
        "page_texts": " ".join(parsed.page_texts),
        "chunks": " ".join(chunk.text for chunk in chunks),
        "toc": " ".join(entry.title for entry in parsed.toc),
    }
    for marker in BOILERPLATE_MARKERS:
        for where, haystack in haystacks.items():
            assert marker not in haystack, f"{marker!r} survived into {where}"


def test_the_articles_own_content_survives() -> None:
    """The other half of the boilerplate test, and the one that fails loudly if
    the denylist gets greedy."""
    parsed = parse_html_bytes(build_sample_html())
    everything = " ".join(parsed.page_texts)
    for _, heading, paragraphs in SECTIONS:
        assert heading in everything
        for paragraph in paragraphs:
            assert paragraph.split(".")[0] in everything


def test_whole_token_matching_does_not_eat_content() -> None:
    """"broadcast" contains "ad"; a substring denylist deletes the article."""
    payload = (
        b"<html><body><main>"
        b'<div class="broadcast headline"><h2>Radio</h2>'
        b"<p>Broadcasting sends one signal to many receivers at once.</p></div>"
        b'<div class="ad"><p>BUY NOW</p></div>'
        b"</main></body></html>"
    )
    text = " ".join(parse_html_bytes(payload).page_texts)
    assert "Broadcasting sends one signal" in text
    assert "BUY NOW" not in text


def test_an_article_header_survives_when_body_is_not_the_root() -> None:
    """`<header>` inside `<article>` is the article's title block, not chrome."""
    payload = (
        b"<html><body><header><p>SITE CHROME</p></header><article>"
        b"<header><h1>Real Title</h1><p>By the author, on a date.</p></header>"
        b"<p>The body of the article follows and is long enough to matter.</p>"
        b"</article></body></html>"
    )
    text = " ".join(parse_html_bytes(payload).page_texts)
    assert "Real Title" in text
    assert "SITE CHROME" not in text


def test_a_body_level_header_is_dropped_when_body_is_the_root() -> None:
    payload = (
        b"<html><body><header><h1>SITE CHROME</h1></header>"
        b"<h2>Real Section</h2><p>The body of the page, at some length.</p>"
        b"</body></html>"
    )
    text = " ".join(parse_html_bytes(payload).page_texts)
    assert "Real Section" in text
    assert "SITE CHROME" not in text


def test_main_wins_the_content_root_election() -> None:
    payload = (
        b"<html><body><div><p>OUTSIDE THE MAIN ELEMENT</p></div>"
        b"<main><h1>Inside</h1><p>The real content of this page.</p></main>"
        b"</body></html>"
    )
    text = " ".join(parse_html_bytes(payload).page_texts)
    assert "The real content" in text
    assert "OUTSIDE" not in text


# ── text extraction ───────────────────────────────────────────────────────


def test_inline_markup_does_not_shred_a_paragraph() -> None:
    payload = (
        b"<html><body><main><p>A <em>vector</em> is an <a href=/x>ordered list</a> "
        b"of <strong>numbers</strong>.</p></main></body></html>"
    )
    parsed = parse_html_bytes(payload)
    bodies = [block.text for block in parsed.blocks if block.heading_level is None]
    assert bodies == ["A vector is an ordered list of numbers ."] or bodies == [
        "A vector is an ordered list of numbers."
    ], bodies


def test_a_generated_heading_anchor_is_not_part_of_the_name() -> None:
    """Sphinx, MkDocs, and Docusaurus all append a self-link inside the heading.

    Measured on docs.python.org: all six headings came out as
    "3.1. Numbers ¶" and every node was named that.
    """
    payload = (
        "<html><body><main>"
        '<h2 id="numbers">3.1. Numbers<a class="headerlink" href="#numbers">¶</a></h2>'
        "<p>Integers and floats behave the way you would expect them to.</p>"
        '<h2>Getting started <a class="hash-link" href="#x">#</a></h2>'
        "<p>Install it, then run it, and read the errors it gives you.</p>"
        "<h2>Learning C#</h2><p>A language with a sharp in its actual name.</p>"
        "</main></body></html>"
    ).encode("utf-8")
    titles = [entry.title for entry in parse_html_bytes(payload).toc]
    assert titles == ["3.1. Numbers", "Getting started", "Learning C#"], titles


def test_html_comments_are_not_text() -> None:
    """`Comment` subclasses `NavigableString`, so a plain isinstance check reads
    commented-out markup as prose."""
    payload = (
        b"<html><body><main><p>Real sentence here.</p>"
        b"<!-- SECRET AD MARKER --><div><!-- ANOTHER ONE -->More real text.</div>"
        b"</main></body></html>"
    )
    text = " ".join(parse_html_bytes(payload).page_texts)
    assert "Real sentence here." in text
    assert "More real text." in text
    assert "SECRET AD MARKER" not in text
    assert "ANOTHER ONE" not in text


def test_a_pathologically_nested_page_does_not_blow_the_stack() -> None:
    """A URL's bytes are attacker-supplied and the parse runs inside a worker."""
    payload = (
        b"<html><body><main>"
        + b"<div>" * 3000
        + b"<p>Buried but still present.</p>"
        + b"</div>" * 3000
        + b"</main></body></html>"
    )
    assert "Buried but still present." in " ".join(parse_html_bytes(payload).page_texts)


def test_bare_text_in_a_div_is_not_lost() -> None:
    payload = b"<html><body><main><div>Loose text with no paragraph wrapper at all.</div></main></body></html>"
    assert "Loose text with no paragraph" in " ".join(parse_html_bytes(payload).page_texts)


def test_list_items_become_separate_blocks() -> None:
    payload = (
        b"<html><body><main><ul><li>First item here.</li><li>Second item here.</li></ul></main></body></html>"
    )
    bodies = [block.text for block in parse_html_bytes(payload).blocks]
    assert "First item here." in bodies
    assert "Second item here." in bodies


def test_nul_and_invisible_characters_never_reach_a_block() -> None:
    """PostgreSQL rejects 0x00 in a text column; `&#0;` is legal HTML.

    Zero-width characters are the quieter half: invisible everywhere a human
    looks, but they split a word for the tokeniser and for `"Duality" in text`.
    """
    payload = (
        "<html><body><main><h2>Du&#8203;ality</h2>"
        "<p>Weak&#0; duality​ holds always. Strong duality needs a condition.</p>"
        "</main></body></html>"
    ).encode("utf-8")
    parsed = parse_html_bytes(payload)
    everything = " ".join(parsed.page_texts) + " ".join(block.text for block in parsed.blocks)

    assert everything.strip()
    assert not any(ch in everything for ch in "\x00\x14​﻿")
    assert "Duality" in everything
    assert "Weak duality" in everything
    assert "always. Strong duality" in everything


def test_decoding_is_deterministic_rather_than_guessed() -> None:
    """BeautifulSoup's own detection was measured picking MacRoman for a page
    containing one control character, turning every accented character into
    mojibake with no error anywhere. The order here is fixed instead."""
    declared = "<html><head><meta charset='iso-8859-1'></head><body><main><p>Café Gödel</p></main></body></html>"
    assert "Café Gödel" in decode_html(declared.encode("iso-8859-1"))

    # No declaration: UTF-8 is tried before the legacy fallback.
    assert "Café Gödel" in decode_html("<html><body><p>Café Gödel</p></body></html>".encode("utf-8"))

    # Undeclared CP-1252 is not valid UTF-8, so it falls through to the WHATWG
    # legacy default rather than raising.
    assert "Café" in decode_html("<html><body><p>Café</p></body></html>".encode("cp1252"))

    # A BOM outranks a (wrong) declaration, which is what browsers do.
    with_bom = ("﻿<html><head><meta charset='iso-8859-1'></head><body><p>Gödel</p></body></html>").encode(
        "utf-8-sig"
    )
    assert "Gödel" in decode_html(with_bom)


def test_a_mislabelled_page_still_parses() -> None:
    """The fallback cannot raise, so no ingest ever dies on an encoding."""
    payload = "<html><head><meta charset='utf-8'></head><body><main><p>Café society</p></main></body></html>".encode(
        "cp1252"
    )
    assert "Caf" in " ".join(parse_html_bytes(payload).page_texts)


def test_sanitise_leaves_ordinary_text_alone() -> None:
    assert sanitise("Convex hulls and polyhedra") == "Convex hulls and polyhedra"
    assert normalise_html_text("  spaced out\n\n\n\ntext  ") == "spaced out\n\ntext"


# ── titles, detection, registry ───────────────────────────────────────────


def test_document_title_prefers_the_title_tag_then_the_first_h1() -> None:
    assert document_title(build_sample_html()) == "Linear Algebra, Abridged"
    assert document_title(b"<html><body><h1>Only a Heading</h1></body></html>") == "Only a Heading"
    assert document_title(b"<html><body><p>nothing</p></body></html>") is None


def test_sniff_recognises_both_formats_and_refuses_the_rest() -> None:
    assert sniff_source_type(build_sample_pdf()) == "pdf"
    assert sniff_source_type(build_sample_html()) == "html"
    assert sniff_source_type(b"<html><body>hi</body></html>") == "html"
    assert sniff_source_type(b"<!doctype HTML>\n<p>x") == "html"
    assert sniff_source_type(b"PK\x03\x04rest of a zip file") is None
    assert sniff_source_type(b"plain text mentioning <p> in passing") is None
    assert sniff_source_type(b"") is None


def test_a_pdf_is_never_sniffed_as_html() -> None:
    """A PDF's uncompressed metadata can contain XML-looking bytes."""
    assert sniff_source_type(b"%PDF-1.7\n<?xml-stylesheet ?><html>") == "pdf"


def test_registry_dispatches_and_refuses_unknown_types() -> None:
    assert parse_source_bytes("html", build_sample_html()).toc
    assert parse_source_bytes("pdf", build_sample_pdf()).blocks
    assert storage_extension("html") == ".html"
    assert storage_extension("pdf") == ".pdf"

    for unsupported in ("epub", "text", "docx"):
        try:
            parse_source_bytes(unsupported, b"x")
        except UnsupportedSourceError:
            pass
        else:
            raise AssertionError(f"{unsupported} should not parse")


# ── end to end through the outline builder ────────────────────────────────


def test_node_titles_are_the_pages_own_headings() -> None:
    """The falsifiable version of the whole feature's claim: no LLM involved."""
    parsed = parse_html_bytes(build_sample_html())
    nodes = build_toc_nodes(parsed.toc, parsed.page_count)
    titles = [node.title for node in nodes]

    for _, heading, _ in SECTIONS:
        assert heading in titles, titles


def test_the_outline_nests_the_way_the_tags_do() -> None:
    parsed = parse_html_bytes(build_sample_html())
    nodes = {node.title: node for node in build_toc_nodes(parsed.toc, parsed.page_count)}

    assert nodes["The Dot Product"].parent_slug == nodes["Vectors"].slug
    assert nodes["Matrix Multiplication"].parent_slug == nodes["Matrices"].slug
    assert nodes["Vectors"].parent_slug == nodes["Linear Algebra, Abridged"].slug

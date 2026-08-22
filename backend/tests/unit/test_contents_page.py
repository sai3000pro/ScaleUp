"""Reading the *printed* table of contents.

The embedded PDF outline is preferred, but scans, exported decks and older books
have none -- and for those the printed Contents page is the only curated
structure in the document.

Layout is a token stream, not lines of prose. A LaTeX contents page extracts as
a section number, then a title carrying a dotted leader, then a page number,
each on its own line, with the leader sometimes spilling onto a line by itself.
"""

from __future__ import annotations

from app.ingestion.parsers.contents import parse_printed_contents

# Physical page 0 is a title page, 1 is the contents, body starts at 2.
# Printed page numbers deliberately do NOT equal physical indices.
TITLE_PAGE = "A Gentle Introduction to Optimization\nUniversity of Waterloo"

CONTENTS = "\n".join(
    [
        "Contents",
        "Preface",
        "1",
        "Prerequisite knowledge",
        "2",
        "0.1",
        "Matrix product . . . . . . . . . . . . . . . .",
        "2",
        "0.2",
        "Inverse of a Matrix",  # leader on its own line, as this book does
        ". . . . . . . . . . . . . . .",
        "3",
        "1",
        "Formulations",
        "4",
        "1.1",
        "LP models . . . . . . . . . . . . . . . . . .",
        "4",
        "1.1.1",
        "The formulation of LP . . . . . . . . . .",
        "5",
    ]
)

BODY = [
    "Prerequisite\nMatrix product\nDefinition: Matrix Multiplication ...",
    "Inverse of a Matrix\nIf an n x n matrix A is invertible ...",
    "Formulations\nLP models\nWhat is optimization? ...",
    "The formulation of LP\nA linear program is ...",
]

PAGES = [TITLE_PAGE, CONTENTS, *BODY]


def parsed():
    return {entry.title: entry for entry in parse_printed_contents(PAGES)}


# ── the token-stream layout ───────────────────────────────────────────────


def test_titles_are_read_without_their_dotted_leaders() -> None:
    titles = set(parsed())
    assert "Matrix product" in titles
    assert "The formulation of LP" in titles


def test_a_leader_on_its_own_line_does_not_break_the_entry() -> None:
    """"Inverse of a Matrix" puts its dots on the following line."""
    assert "Inverse of a Matrix" in parsed()


def test_level_comes_from_the_section_number() -> None:
    entries = parsed()
    assert entries["Formulations"].level == 1
    assert entries["LP models"].level == 2
    assert entries["The formulation of LP"].level == 3


def test_a_number_typeset_inline_with_its_title_is_stripped() -> None:
    """Wider numbers like "2.10" are set inline rather than on their own line.

    Left alone, the entry becomes a chapter named "2.10 Standard inequality
    Form" -- both the wrong name and the wrong depth.
    """
    pages = [
        TITLE_PAGE,
        "Contents\n2.10 Standard inequality Form . . . . . .\n2\n"
        "2.11 Extreme Points . . . . . . . . . . . . .\n3\n"
        "3 Duality . . . . . . . . . . . . . . . . . .\n4\n"
        "3.1 Weak Duality . . . . . . . . . . . . . .\n5",
        "Standard inequality Form ...",
        "Extreme Points ...",
        "Duality ...",
        "Weak Duality ...",
    ]
    entries = {e.title: e for e in parse_printed_contents(pages)}
    assert "Standard inequality Form" in entries
    assert entries["Standard inequality Form"].level == 2
    assert entries["Duality"].level == 1


# ── page calibration ──────────────────────────────────────────────────────


def test_printed_page_numbers_are_calibrated_to_physical_indices() -> None:
    """Printed "2" is the third physical page here, not the second.

    Calibrating against the contents page itself is the trap: every title is
    listed there, so a naive search finds all of them on page 1 and collapses
    the whole book onto page 0.
    """
    entries = parsed()
    assert entries["Matrix product"].page_index == 2
    assert entries["Inverse of a Matrix"].page_index == 3
    assert entries["The formulation of LP"].page_index == 5


def test_page_indices_never_fall_outside_the_document() -> None:
    entries = parse_printed_contents(PAGES)
    assert all(0 <= entry.page_index < len(PAGES) for entry in entries)


# ── block detection ───────────────────────────────────────────────────────


def test_a_continuation_page_is_followed_via_its_running_header() -> None:
    """A second contents page is mostly bare numbers, so leader density alone
    reads as 0.21 and silently drops a quarter of the book."""
    pages = [
        TITLE_PAGE,
        CONTENTS,
        "CONTENTS\n2.1\nDuality . . . . . . . . . . . . . .\n6\n2.2\nWeak Duality . . . . . . . .\n7",
        *BODY,
        "Duality ...",
        "Weak Duality ...",
    ]
    titles = {entry.title for entry in parse_printed_contents(pages)}
    assert {"Duality", "Weak Duality"} <= titles
    assert "Matrix product" in titles  # first page still read


def test_parsing_stops_before_body_text() -> None:
    entries = parsed()
    assert "Definition: Matrix Multiplication ..." not in entries
    assert len(entries) <= 7


def test_a_document_with_no_contents_page_yields_nothing() -> None:
    """The caller then falls back to LLM inference."""
    assert parse_printed_contents([TITLE_PAGE, *BODY]) == []


def test_an_empty_document_is_handled() -> None:
    assert parse_printed_contents([]) == []


def test_a_listing_too_short_to_trust_is_rejected() -> None:
    assert parse_printed_contents([TITLE_PAGE, "Contents\nOnly One . . . .\n2", "Only One ..."]) == []


def test_page_numbers_that_run_backwards_are_dropped() -> None:
    """A decreasing page number means something that was not a page number got
    parsed as one."""
    pages = [
        TITLE_PAGE,
        "Contents\nAlpha . . . . .\n2\nBeta . . . . .\n3\nGamma . . . . .\n1\nDelta . . . . .\n4",
        "Alpha ...",
        "Beta ...",
        "Gamma ...",
        "Delta ...",
    ]
    titles = [entry.title for entry in parse_printed_contents(pages)]
    assert "Gamma" not in titles
    assert titles == sorted(titles, key=["Alpha", "Beta", "Delta"].index)

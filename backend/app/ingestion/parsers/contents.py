"""Read the *printed* table of contents — the "Contents" pages themselves.

The embedded PDF outline is preferred when it exists, but plenty of real
sources have none: scans, exported slide decks, older books, anything printed to
PDF. For those the printed Contents page is the only curated structure in the
document, and it is still far better evidence than asking a model to infer a
hierarchy from prose.

Two things make this harder than it looks.

**The layout is a token stream, not lines of text.** A LaTeX contents page
extracts as a section number, then a title carrying a dotted leader, then a page
number — each its own line, and the leader sometimes spilling onto a line of its
own:

    '1.2.1'
    'The formulation of LP . . . . . . . . . .'
    '11'

**Printed page numbers are not physical page indices.** Front matter is usually
numbered separately or not at all, so "page 11" might be the 13th page of the
file. The offset is *measured* here rather than assumed, by finding where a
sample of titles actually appear.

Pure: takes page texts, returns entries. No PDF library, no I/O.
"""

from __future__ import annotations

import re
from statistics import median

from app.ingestion.parsers.base import TocEntry

__all__ = ["parse_printed_contents", "CONTENTS_HEADINGS"]

CONTENTS_HEADINGS = frozenset({"contents", "table of contents", "index of contents"})

# "1", "1.2", "1.2.1" — the section number, whose depth gives the level.
NUMBER_TOKEN = re.compile(r"^\d+(?:\.\d+)*\.?$")
# A leader that landed on its own line.
DOTS_ONLY = re.compile(r"^[.·…\s]+$")
PAGE_TOKEN = re.compile(r"^\d{1,4}$")
# Trailing dotted leader, with or without spaces, plus an optional page number
# already glued onto the end.
TRAILING_LEADER = re.compile(r"[\s.·…]{2,}\d*$")
HAS_LETTER = re.compile(r"[A-Za-z]")
# A section number typeset inline with its title, e.g. "2.10 Standard inequality Form".
LEADING_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(?=\S)")

# How many pages from the front to search for the contents block.
SEARCH_FRONT_PAGES = 15
MIN_ENTRIES = 4
CONTINUATION_LEADER_DENSITY = 0.15
CONTINUATION_MIN_ENTRIES = 3


def _looks_like_contents_page(text: str) -> bool:
    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    return any(line in CONTENTS_HEADINGS for line in lines[:6])


def _leader_density(text: str) -> float:
    """Fraction of non-empty lines carrying a dotted leader.

    A continuation page has no "Contents" heading, so this is what identifies it.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    return sum(1 for line in lines if TRAILING_LEADER.search(line) or DOTS_ONLY.match(line)) / len(lines)


def _clean_title(raw: str) -> str:
    return TRAILING_LEADER.sub("", raw).strip(" .·…")


def _level_from_number(token: str) -> int:
    return token.rstrip(".").count(".") + 1


def _parse_block(text: str) -> list[tuple[int, str, int]]:
    """(level, title, printed_page) triples from one contents page."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    entries: list[tuple[int, str, int]] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        if NUMBER_TOKEN.match(line) or DOTS_ONLY.match(line) or not HAS_LETTER.search(line):
            # A bare number here is either a section number (the title follows)
            # or a stray page number already consumed below. Either way, the
            # title branch is what advances past it.
            index += 1
        else:
            title = _clean_title(line)
            level = 1

            # A wider number ("2.10") is typeset inline with its title rather
            # than on its own line, so check the title itself first -- otherwise
            # the number stays glued to the name and the entry reads as a
            # chapter called "2.10 Standard inequality Form".
            inline = LEADING_NUMBER.match(title)
            if inline is not None:
                level = _level_from_number(inline.group(1))
                title = title[inline.end() :].strip()
            elif index > 0 and NUMBER_TOKEN.match(lines[index - 1]):
                level = _level_from_number(lines[index - 1])

            # The page number follows, possibly after a leader-only line.
            page: int | None = None
            look = index + 1
            while look < len(lines) and look <= index + 2:
                if DOTS_ONLY.match(lines[look]):
                    look += 1
                elif PAGE_TOKEN.match(lines[look]):
                    page = int(lines[look])
                    break
                else:
                    break

            if page is not None and len(title) >= 2 and HAS_LETTER.search(title):
                entries.append((level, title, page))
                index = look + 1
            else:
                index += 1

    return entries


def _calibrate_offset(entries: list[tuple[int, str, int]], page_texts: list[str], body_start: int) -> int:
    """physical_index - printed_page, measured rather than assumed.

    Search begins at `body_start`, past the contents block. Searching from page
    zero finds every title *on the contents page itself* -- which is where they
    are all listed -- producing a delta of roughly minus-the-whole-book and
    collapsing every early entry onto page 0.

    Median rather than mean: a title that also appears in a cross-reference
    produces an outlier, and one outlier must not shift every node in the book.
    """
    haystacks = [text.lower() for text in page_texts]
    deltas: list[int] = []

    for _, title, printed in entries:
        needle = title.lower()
        if len(needle) < 6:
            pass
        else:
            for physical in range(body_start, len(haystacks)):
                if needle in haystacks[physical]:
                    deltas.append(physical - printed)
                    break

    if not deltas:
        return 0
    return int(median(deltas))


def parse_printed_contents(page_texts: list[str]) -> list[TocEntry]:
    """Entries from the document's printed contents pages, page-calibrated.

    Returns [] when there is no recognisable contents block, so the caller can
    fall back to LLM inference.
    """
    if not page_texts:
        return []

    start: int | None = None
    for index, text in enumerate(page_texts[:SEARCH_FRONT_PAGES]):
        if _looks_like_contents_page(text):
            start = index
            break

    if start is None:
        return []

    # The block runs while pages keep looking like a contents listing.
    raw: list[tuple[int, str, int]] = []
    body_start = start + 1

    for index in range(start, len(page_texts)):
        text = page_texts[index]
        parsed = _parse_block(text)
        # Three independent signals that this page is still part of the listing.
        # Leader density alone is too brittle: a continuation page is mostly
        # bare section numbers and page numbers, which drags the ratio down --
        # this book's second contents page scores 0.21 and parses 11 entries
        # perfectly, so a 0.25 density gate silently dropped a quarter of the
        # book.
        continuation = (
            index == start
            or _looks_like_contents_page(text)  # running "CONTENTS" header
            or _leader_density(text) >= CONTINUATION_LEADER_DENSITY
            or len(parsed) >= CONTINUATION_MIN_ENTRIES
        )
        if continuation:
            raw.extend(parsed)
            body_start = index + 1
        else:
            break

    # Drop the "Contents" heading itself if it was parsed as an entry.
    raw = [entry for entry in raw if entry[1].strip().lower() not in CONTENTS_HEADINGS]

    if len(raw) < MIN_ENTRIES:
        return []

    # Page numbers must not run backwards; a decreasing value means we parsed
    # something that was not a page number.
    monotonic: list[tuple[int, str, int]] = []
    highest = -1
    for level, title, page in raw:
        if page >= highest:
            monotonic.append((level, title, page))
            highest = page

    if len(monotonic) < MIN_ENTRIES:
        return []

    offset = _calibrate_offset(monotonic, page_texts, body_start)
    last_index = len(page_texts) - 1

    return [
        TocEntry(level=level, title=title, page_index=max(0, min(last_index, page + offset)))
        for level, title, page in monotonic
    ]

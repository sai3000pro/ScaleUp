"""PDF parsing with structural heading detection.

The heading detection is worth its ~60 lines. `section_path` derived from it is
fed into the extraction prompt, and it is most of what stops the model inventing
a concept called "Introduction" forty times across one book.

Two independent signals, because either alone is unreliable on real books:
  * **typography** -- a line noticeably larger than body text and short;
  * **numbering**  -- a leading "3.2.1", whose depth also gives the level directly.
A line only needs one of them, but numbering wins on level when both are present.
"""

from __future__ import annotations

import re
from collections import Counter

import pymupdf

from app.ingestion.parsers.base import ParsedBlock, ParsedDocument, TocEntry
from app.ingestion.parsers.clean import sanitise
from app.ingestion.parsers.contents import parse_printed_contents

# Below this an embedded outline is too thin to trust, and the printed contents
# page is worth trying instead.
MIN_OUTLINE_ENTRIES = 4

__all__ = ["parse_pdf", "parse_pdf_bytes"]

NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+){0,3})[.)]?\s+\S")

HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 90
MIN_HEADING_CHARS = 2


def _line_text(line: dict) -> str:
    raw = "".join(span.get("text", "") for span in line.get("spans", ()))
    # See `parsers.clean` for why this happens here and not at the DB boundary.
    return sanitise(raw).strip()


def _line_size(line: dict) -> float:
    spans = [s for s in line.get("spans", ()) if s.get("text", "").strip()]
    if not spans:
        return 0.0
    # Max, not mean: a heading followed by a small footnote marker on the same
    # line should still read as a heading.
    return max(float(span.get("size", 0.0)) for span in spans)


def _body_size(all_lines: list[tuple[float, str]]) -> float:
    """Modal rounded font size across the document -- i.e. body text."""
    sizes = Counter(round(size, 1) for size, text in all_lines if text)
    if not sizes:
        return 0.0
    return sizes.most_common(1)[0][0]


def _heading_level(text: str, size: float, body: float, distinct_larger: list[float]) -> int | None:
    """Return 1-3 for a heading, or None for body text."""
    stripped = text.strip()
    if not (MIN_HEADING_CHARS <= len(stripped) <= MAX_HEADING_CHARS):
        return None

    numbered = NUMBERED.match(stripped)
    larger = size >= body * HEADING_SIZE_RATIO

    if not numbered and not larger:
        return None

    if numbered:
        # "3" -> level 1, "3.2" -> 2, "3.2.1" -> 3.
        depth = numbered.group(1).count(".") + 1
        return min(depth, 3)

    # Typography only: rank among the distinct larger-than-body sizes, biggest
    # first, so the largest heading size in the book becomes level 1.
    for rank, candidate in enumerate(distinct_larger, start=1):
        if abs(size - candidate) < 0.05:
            return min(rank, 3)
    return 3


def parse_pdf_bytes(payload: bytes) -> ParsedDocument:
    document = pymupdf.open(stream=payload, filetype="pdf")
    try:
        return _parse(document)
    finally:
        document.close()


def parse_pdf(path: str) -> ParsedDocument:
    document = pymupdf.open(path)
    try:
        return _parse(document)
    finally:
        document.close()


def _read_toc(document) -> list[TocEntry]:
    """The PDF's embedded outline, if it has one.

    LaTeX with hyperref (and Word, and Pandoc) writes a real outline, so this is
    available far more often than it looks. Deliberately not a fallback to
    scraping the printed "Contents" page: those are dotted-leader lines whose
    page numbers refer to *printed* numbering, which rarely matches the PDF's
    physical page index.
    """
    try:
        raw = document.get_toc(simple=True) or []
    except Exception:  # noqa: BLE001 - a malformed outline must not fail an ingest
        return []

    entries: list[TocEntry] = []
    for item in raw:
        if len(item) < 3:
            pass
        else:
            level, title, page = item[0], str(item[1]).strip(), int(item[2])
            # get_toc pages are 1-based; a 0 or -1 means "no destination".
            if title and level >= 1 and page >= 1:
                entries.append(TocEntry(level=int(level), title=sanitise(title), page_index=page - 1))
    return entries


def _parse(document) -> ParsedDocument:
    # Pass one: collect every line with its size, so body size is known before
    # any classification happens.
    per_page: list[list[tuple[float, str]]] = []
    for page in document:
        lines: list[tuple[float, str]] = []
        for block in page.get_text("dict").get("blocks", ()):
            for line in block.get("lines", ()):
                text = _line_text(line)
                if text:
                    lines.append((_line_size(line), text))
        per_page.append(lines)

    flat = [entry for page_lines in per_page for entry in page_lines]
    body = _body_size(flat)
    distinct_larger = sorted({round(size, 1) for size, _ in flat if size >= body * HEADING_SIZE_RATIO}, reverse=True)

    # Pass two: classify, and merge consecutive body lines into paragraphs so a
    # chunk boundary never lands mid-sentence for purely typographic reasons.
    parsed = ParsedDocument(toc=_read_toc(document))
    for page_index, lines in enumerate(per_page):
        parsed.page_texts.append("\n".join(text for _, text in lines))

        pending: list[str] = []
        for size, text in lines:
            level = _heading_level(text, size, body, distinct_larger)
            if level is None:
                pending.append(text)
            else:
                if pending:
                    parsed.blocks.append(ParsedBlock(text=" ".join(pending), page_index=page_index))
                    pending = []
                parsed.blocks.append(ParsedBlock(text=text, page_index=page_index, heading_level=level))

        if pending:
            parsed.blocks.append(ParsedBlock(text=" ".join(pending), page_index=page_index))

    # No usable embedded outline? Read the printed "Contents" pages instead.
    # Runs here rather than beside `_read_toc` because it needs `page_texts`,
    # which only exists once the loop above has run.
    if len(parsed.toc) < MIN_OUTLINE_ENTRIES:
        printed = parse_printed_contents(parsed.page_texts)
        if len(printed) > len(parsed.toc):
            parsed.toc = printed

    return parsed

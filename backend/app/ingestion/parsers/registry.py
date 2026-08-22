"""source_type -> parser. One table, one lookup.

The pipeline calls `parse_source` in three places (`parse_document`,
`chunk_document`, `_toc_graph`). Each used to name `parse_pdf` directly, which
meant adding a format was a three-site edit with no compiler to catch the one
you missed -- and the miss would not fail, it would silently parse an HTML file
as a PDF and raise from inside pymupdf during a Celery task.
"""

from __future__ import annotations

from typing import Callable

from app.ingestion.parsers.base import ParsedDocument
from app.ingestion.parsers.html import parse_html, parse_html_bytes
from app.ingestion.parsers.pdf import parse_pdf, parse_pdf_bytes

__all__ = ["parse_source", "parse_source_bytes", "SUPPORTED_SOURCE_TYPES", "UnsupportedSourceError"]


class UnsupportedSourceError(ValueError):
    """No parser is registered for this `source_type`."""


_BY_PATH: dict[str, Callable[[str], ParsedDocument]] = {
    "pdf": parse_pdf,
    "html": parse_html,
}

_BY_BYTES: dict[str, Callable[[bytes], ParsedDocument]] = {
    "pdf": parse_pdf_bytes,
    "html": parse_html_bytes,
}

# `Document.source_type`'s CHECK constraint also permits 'epub' and 'text'. They
# are absent here on purpose: the constraint records what the column may one day
# hold, this table records what can actually be read today, and the gap between
# them should raise rather than be papered over with a default parser.
SUPPORTED_SOURCE_TYPES = frozenset(_BY_PATH)

# The file extension stored alongside the content hash. Storage is
# content-addressed, so the extension is documentation for a human browsing the
# upload directory -- but it must still match the format, or the next person to
# open one of these files by hand gets a PDF viewer full of markup.
_EXTENSIONS = {"pdf": ".pdf", "html": ".html"}


def storage_extension(source_type: str) -> str:
    return _EXTENSIONS.get(source_type, ".bin")


def parse_source(source_type: str, path: str) -> ParsedDocument:
    parser = _BY_PATH.get(source_type)
    if parser is None:
        raise UnsupportedSourceError(f"no parser for source_type {source_type!r}")
    return parser(path)


def parse_source_bytes(source_type: str, payload: bytes) -> ParsedDocument:
    parser = _BY_BYTES.get(source_type)
    if parser is None:
        raise UnsupportedSourceError(f"no parser for source_type {source_type!r}")
    return parser(payload)

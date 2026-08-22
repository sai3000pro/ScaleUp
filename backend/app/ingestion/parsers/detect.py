"""Decide what a byte string actually is.

**Sniffed, never declared.** The filename and the `Content-Type` header are both
supplied by whoever is uploading, and a URL fetch adds a third untrusted opinion
from a server we do not control. `source_type` is written into the database and
selects the parser, so it has to come from the bytes.
"""

from __future__ import annotations

__all__ = ["sniff_source_type", "PDF_MAGIC"]

PDF_MAGIC = b"%PDF-"

# The PDF spec permits junk before the header and real files produced by
# scanners and mail gateways do carry it, so the magic is searched for in a
# prefix rather than required at offset zero.
_PDF_SEARCH_BYTES = 1024

# Enough to reach past a licence comment, a doctype, and a long <head>.
_HTML_SEARCH_BYTES = 4096

# Any one of these is decisive. Deliberately structural rather than a general
# "contains a tag" test: a PDF's uncompressed metadata and a plain-text file
# quoting `<p>` must not read as a document.
_HTML_MARKERS = (
    "<!doctype html",
    "<html",
    "<head>",
    "<head ",
    "<body>",
    "<body ",
    "<meta charset",
    "<?xml-stylesheet",
)


def sniff_source_type(payload: bytes) -> str | None:
    """Return `"pdf"`, `"html"`, or None when the bytes are neither.

    None means "refuse", not "guess". A caller that turned an unrecognised blob
    into `text` would be handing the parser registry something it cannot read
    and the failure would surface three stages later inside a Celery task.
    """
    if PDF_MAGIC in payload[:_PDF_SEARCH_BYTES]:
        return "pdf"

    prefix = payload[:_HTML_SEARCH_BYTES].decode("utf-8", errors="ignore").lower()
    if any(marker in prefix for marker in _HTML_MARKERS):
        return "html"
    return None

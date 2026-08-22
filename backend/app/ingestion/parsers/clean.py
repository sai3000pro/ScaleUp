"""Text sanitisation shared by every parser.

This lives in its own module because it is not a PDF concern and never was --
it was simply discovered there first. Every parser feeds `ParsedBlock.text` and
`ParsedDocument.page_texts`, and every one of those strings ends up in a
PostgreSQL `text` column, a prompt, and an embedding. The rule has to hold for
all of them identically, so it is stated once here rather than copied into each
new parser and drifting.
"""

from __future__ import annotations

import re

__all__ = ["CONTROL_CHARS", "sanitise", "normalise_html_text"]

# C0 control characters, keeping tab and the newline pair.
#
# Real PDFs -- LaTeX-produced ones especially -- emit these where a glyph has no
# sensible Unicode mapping, typically from math fonts. NUL is the one that
# actually breaks things: PostgreSQL rejects 0x00 in a text column outright, so
# a single unmapped glyph anywhere in a 90-page book fails the whole ingest at
# the very first insert. The others are stripped because they are noise in a
# prompt and in an embedding alike.
#
# HTML arrives at the same failure by a different road: `&#0;` is a legal
# character reference that BeautifulSoup will hand back as a real NUL, and a
# page mislabelled UTF-8 that is really CP-1252 decodes into this same range.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Zero-width and bidirectional formatting characters. Invisible in a browser and
# invisible in a diff, but they split a word for the tokeniser and for every
# substring match, so a heading that reads "Duality" can fail `"Duality" in x`.
# Wikipedia and most CMS output carry these; a PDF text layer does not, which is
# why this is applied on the HTML path only rather than folded into `sanitise`.
#
# U+FFFD is here for the same reason and arrives two ways: the HTML5 parser
# substitutes it for a malformed character reference such as `&#0;`, and
# `decode_html`'s CP-1252 fallback emits it where a byte was unrecoverable.
# Either way it marks data that is already lost, and leaving it in splits the
# surrounding word exactly as a zero-width space does.
_INVISIBLES = re.compile("[​-‏‪-‮⁠﻿�]")

# U+00A0 and friends are genuinely spaces and must become one rather than
# vanish: "Chapter 1" is two words, not "Chapter1".
_UNICODE_SPACES = re.compile("[   -   　]")

# Horizontal whitespace only -- `\n` is load-bearing, because an HTML source
# file's indentation lives inside the text node and paragraph structure does not
# survive collapsing it away.
_HORIZONTAL = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def sanitise(text: str) -> str:
    """Strip what must never reach the database, a prompt, or an embedding.

    Parsers call this at the point text is first materialised rather than at the
    DB boundary: every downstream artefact -- page text, blocks, chunks,
    embeddings, prompts -- derives from that one string, so this is the only
    place it has to be right.
    """
    return CONTROL_CHARS.sub("", text)


def normalise_html_text(text: str) -> str:
    """`sanitise`, plus the things only markup produces.

    Invisible formatting characters are removed, non-breaking and typographic
    spaces become ordinary ones, and runs of horizontal whitespace collapse --
    all of which are artefacts of how the page was authored rather than content.
    """
    cleaned = _UNICODE_SPACES.sub(" ", _INVISIBLES.sub("", sanitise(text)))
    return _BLANK_LINES.sub("\n\n", _HORIZONTAL.sub(" ", cleaned)).strip()

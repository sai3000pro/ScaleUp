"""Parser output types.

Every parser (PDF now; EPUB and HTML later) emits this same shape, so chunking
never learns what a source format is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ParsedBlock", "TocEntry", "ParsedDocument"]


@dataclass(frozen=True, slots=True)
class TocEntry:
    """One entry from the document's own table of contents.

    A textbook's TOC is a concept hierarchy its author already curated, in
    prerequisite order. It beats anything an LLM infers from loose prose: the
    names are the real names ("The KKT Theorem", not "Consider"), the nesting is
    real nesting, and it costs nothing to read.
    """

    level: int  # 1 = chapter, 2 = section, 3+ = subsection
    title: str
    page_index: int  # 0-based, matching ParsedBlock.page_index


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    """A run of text with its position and, if it is a heading, its level."""

    text: str
    page_index: int
    # 1 = chapter, 2 = section, 3 = subsection. None = body text.
    heading_level: int | None = None


@dataclass(slots=True)
class ParsedDocument:
    page_texts: list[str] = field(default_factory=list)
    blocks: list[ParsedBlock] = field(default_factory=list)
    # Empty when the source has no embedded outline; the pipeline then falls
    # back to LLM-inferred structure.
    toc: list[TocEntry] = field(default_factory=list)

    # How deep a heading still ends a chunk. `None` means "use the chunker's own
    # default", which is what a PDF wants.
    #
    # This is a number, not a format flag, precisely so chunking never learns
    # what a source format is. What differs between formats is how much a
    # heading can be TRUSTED. A PDF heading is inferred from font size and a
    # leading "3.2.1", so a large word mid-paragraph can be misread as a level-3
    # heading; splitting on every one of those would shred prose. An HTML `h4`
    # is declared by the author and cannot be a false positive, so every heading
    # is a real boundary and there is no reason to let two sections share a
    # chunk. Measured on the Wikipedia "Linear programming" article: honouring
    # this took the graph from 12 structural nodes out of 34 to 2, and the two
    # that remain are genuine containers with no prose of their own.
    hard_boundary_level: int | None = None

    @property
    def page_count(self) -> int:
        return len(self.page_texts)

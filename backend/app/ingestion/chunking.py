"""Chunking. Pure, no I/O, no database -- unit-tested in milliseconds.

The rule that matters most: **never cross a heading of level <= 2.** A chunk
spanning two chapters produces garbage skills, and no amount of prompt work
downstream recovers from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

import tiktoken

from app.ingestion.parsers.base import ParsedBlock

__all__ = ["Chunk", "chunk_blocks", "count_tokens"]

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
HARD_BOUNDARY_LEVEL = 2  # headings at or above this never sit inside a chunk
MIN_CHUNK_TOKENS = 60  # below this it is a page number or an orphan caption


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    text: str
    token_count: int
    page_start: int
    page_end: int
    section_path: str | None


@lru_cache(maxsize=1)
def _encoding():
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def _section_path(stack: Sequence[str]) -> str | None:
    return " / ".join(stack) if stack else None


def _split_sentences(text: str) -> list[str]:
    return [part for part in SENTENCE_END.split(text) if part.strip()]


def _window(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split oversized text on sentence boundaries with a token overlap.

    Splitting mid-sentence would hand the extractor a fragment whose subject is
    in the previous chunk, which is exactly how you get a concept named "it".
    """
    sentences = _split_sentences(text) or [text]
    windows: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)
        if current and current_tokens + sentence_tokens > max_tokens:
            windows.append(" ".join(current))
            # Carry the tail back as overlap so a concept straddling the seam
            # appears whole in at least one window.
            carried: list[str] = []
            carried_tokens = 0
            for previous in reversed(current):
                previous_tokens = count_tokens(previous)
                if carried_tokens + previous_tokens > overlap_tokens:
                    break
                carried.insert(0, previous)
                carried_tokens += previous_tokens
            current = carried
            current_tokens = carried_tokens

        current.append(sentence)
        current_tokens += sentence_tokens

    if current:
        windows.append(" ".join(current))
    return windows


def chunk_blocks(
    blocks: Sequence[ParsedBlock],
    max_tokens: int = 800,
    overlap_tokens: int = 120,
    min_tokens: int = MIN_CHUNK_TOKENS,
    hard_boundary_level: int = HARD_BOUNDARY_LEVEL,
) -> list[Chunk]:
    """Turn parsed blocks into chunks carrying their section path and pages.

    `hard_boundary_level` is supplied by the parser via
    `ParsedDocument.hard_boundary_level` rather than inferred here, because how
    far a heading can be trusted is a property of the source format and this
    module deliberately does not know what one is. The default is unchanged, so
    every existing caller chunks exactly as before.
    """
    chunks: list[Chunk] = []
    heading_stack: list[str] = []

    pending_text: list[str] = []
    pending_tokens = 0
    pending_pages: list[int] = []
    pending_path: str | None = None

    def flush() -> None:
        nonlocal pending_text, pending_tokens, pending_pages, pending_path
        if pending_text:
            body = " ".join(pending_text).strip()
            if body:
                for window in _window(body, max_tokens, overlap_tokens):
                    tokens = count_tokens(window)
                    # Keep an undersized chunk only when it is a section's whole
                    # content; otherwise it is furniture.
                    keep = tokens >= min_tokens or not chunks or chunks[-1].section_path != pending_path
                    if keep:
                        chunks.append(
                            Chunk(
                                ordinal=len(chunks),
                                text=window,
                                token_count=tokens,
                                page_start=min(pending_pages),
                                page_end=max(pending_pages),
                                section_path=pending_path,
                            )
                        )
        pending_text = []
        pending_tokens = 0
        pending_pages = []

    for block in blocks:
        if block.heading_level is not None:
            # A chapter or section boundary always ends the current chunk.
            if block.heading_level <= hard_boundary_level:
                flush()
            elif pending_tokens >= max_tokens:
                flush()

            del heading_stack[block.heading_level - 1 :]
            heading_stack.append(block.text.strip())
            pending_path = _section_path(heading_stack)
        else:
            block_tokens = count_tokens(block.text)
            if pending_text and pending_tokens + block_tokens > max_tokens:
                flush()
            if pending_path is None:
                pending_path = _section_path(heading_stack)
            pending_text.append(block.text)
            pending_tokens += block_tokens
            pending_pages.append(block.page_index)

    flush()

    # Ordinals must be dense after any filtering.
    return [
        Chunk(
            ordinal=index,
            text=chunk.text,
            token_count=chunk.token_count,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section_path=chunk.section_path,
        )
        for index, chunk in enumerate(chunks)
    ]

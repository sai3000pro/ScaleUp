"""Graph provenance projection stays exact, bounded, and deterministic."""

from __future__ import annotations

import uuid

from app.models import Chunk
from app.services.graph_read import _source_evidence


def _chunk(page: int, ordinal: int, text: str) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        ordinal=ordinal,
        page_start=page,
        page_end=page,
        section_path=f"Section {page}",
        text=text,
        token_count=len(text.split()),
        content_sha256="0" * 64,
    )


def test_source_evidence_is_sorted_and_capped() -> None:
    chunks = [_chunk(page, index, f"Passage {index}") for index, page in enumerate((8, 2, 5, 1, 4))]
    by_id = {chunk.id: chunk for chunk in chunks}

    evidence = _source_evidence([chunk.id for chunk in chunks], by_id)

    assert [item.page_start for item in evidence] == [1, 2, 4, 5]
    assert len(evidence) == 4
    assert all(item.excerpt.startswith("Passage") for item in evidence)


def test_source_evidence_ignores_missing_chunk_ids() -> None:
    chunk = _chunk(3, 0, "The exact supporting passage.")

    evidence = _source_evidence([uuid.uuid4(), chunk.id], {chunk.id: chunk})

    assert len(evidence) == 1
    assert evidence[0].chunk_id == chunk.id

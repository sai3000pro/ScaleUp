"""The vector-store seam.

One Protocol, so retrieval never imports a vendor. Chroma is the stage-1
implementation; the alternative worth keeping in view is pgvector in the same
Postgres, which would make chunk rows and their embeddings a single
transactional write instead of a dual write with no transaction across it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

__all__ = ["VectorHit", "VectorStore"]


@dataclass(frozen=True, slots=True)
class VectorHit:
    chunk_id: str
    score: float
    metadata: dict


class VectorStore(Protocol):
    def upsert(
        self,
        course_id: str,
        chunk_ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict],
        documents: Sequence[str],
    ) -> None:
        """Idempotent by chunk_id -- re-running an embed task must not duplicate."""
        ...

    def query(self, course_id: str, embedding: Sequence[float], k: int = 5) -> list[VectorHit]:
        """Nearest chunks within one course. Retrieval is always filter-then-search."""
        ...

    def drop_document(self, course_id: str, document_id: str) -> None:
        """Remove one document's vectors before re-embedding it."""
        ...

    def drop_course(self, course_id: str) -> None:
        """Remove a course's vectors, so a reindex starts from a clean slate."""
        ...

    def count(self, course_id: str) -> int: ...

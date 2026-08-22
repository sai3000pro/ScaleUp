"""Chroma-backed VectorStore.

Talks to the Chroma server container over HTTP via `chromadb-client`. The full
`chromadb` package is deliberately NOT a dependency: it pulls in chroma-hnswlib,
which has no Windows wheel and needs MSVC Build Tools to compile. We never need
the embedded engine anyway.

One collection per course rather than one shared collection with a metadata
filter: dropping a course on reindex becomes a delete rather than a filtered
scan, and a course's vectors can never leak into another course's retrieval.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.vector.base import VectorHit


@lru_cache(maxsize=1)
def _client() -> chromadb.ClientAPI:
    settings = get_settings()
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        # The server-side ANONYMIZED_TELEMETRY env var does not cover the client;
        # without this the client phones home from the developer's machine.
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _collection_name(course_id: str) -> str:
    # Chroma requires 3-63 chars, starting and ending alphanumeric.
    return f"course-{course_id}"


class ChromaVectorStore:
    """Implements app.vector.base.VectorStore."""

    def _collection(self, course_id: str):
        return _client().get_or_create_collection(
            name=_collection_name(course_id),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        course_id: str,
        chunk_ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict],
        documents: Sequence[str],
    ) -> None:
        if not chunk_ids:
            return
        # `upsert`, not `add`: a Celery task redelivered after acks_late must be
        # a no-op rather than a duplicate-id error.
        self._collection(course_id).upsert(
            ids=list(chunk_ids),
            embeddings=[list(vector) for vector in embeddings],
            metadatas=list(metadatas),
            documents=list(documents),
        )

    def query(self, course_id: str, embedding: Sequence[float], k: int = 5) -> list[VectorHit]:
        result = self._collection(course_id).query(
            query_embeddings=[list(embedding)],
            n_results=k,
            include=["metadatas", "distances"],
        )

        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]

        hits: list[VectorHit] = []
        for index, chunk_id in enumerate(ids):
            distance = distances[index] if index < len(distances) else 1.0
            metadata = metadatas[index] if index < len(metadatas) else {}
            # Cosine distance -> similarity, so callers can threshold on a number
            # that grows with relevance rather than shrinks.
            hits.append(VectorHit(chunk_id=chunk_id, score=1.0 - float(distance), metadata=dict(metadata or {})))
        return hits

    def drop_document(self, course_id: str, document_id: str) -> None:
        """Remove one document's vectors, leaving the rest of the course intact.

        Needed before re-embedding: a re-chunk that yields fewer chunks would
        otherwise strand the tail of the previous run in the index, where it
        would keep turning up in retrieval.
        """
        try:
            self._collection(course_id).delete(where={"document_id": document_id})
        except Exception:  # noqa: BLE001 -- nothing to delete is the desired end state
            pass

    def drop_course(self, course_id: str) -> None:
        try:
            _client().delete_collection(_collection_name(course_id))
        except Exception:  # noqa: BLE001 -- absent collection is the desired end state
            pass

    def count(self, course_id: str) -> int:
        return self._collection(course_id).count()

    def heartbeat(self) -> int:
        return _client().heartbeat()

    def clear_all(self) -> None:
        """Delete every collection. For tests and for a full reindex."""
        client = _client()
        for collection in client.list_collections():
            name = collection if isinstance(collection, str) else collection.name
            try:
                client.delete_collection(name)
            except Exception:  # noqa: BLE001 -- already gone is the desired end state
                pass


@lru_cache(maxsize=1)
def get_vector_store() -> ChromaVectorStore:
    return ChromaVectorStore()

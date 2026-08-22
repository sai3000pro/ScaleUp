"""Embedding, batched, bridged to synchronous callers.

See app/core/sync_bridge.py for why the bridge is not a bare `asyncio.run`.
"""

from __future__ import annotations

from typing import Sequence

from app.core.sync_bridge import run_sync
from app.llm.factory import get_embedding_provider

__all__ = ["embed_texts", "batched"]


def batched(items: Sequence, size: int) -> list[list]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Embed a batch. Blocking -- intended for use inside a Celery task."""
    if not texts:
        return []
    provider = get_embedding_provider()
    return run_sync(provider.embed(list(texts)))


def embedding_input(section_path: str | None, text: str) -> str:
    """What actually gets embedded.

    The section path is prepended deliberately: on textbook prose it measurably
    improves retrieval, because "3 / 3.2 Gradient Descent" disambiguates a
    passage whose own words never name the topic.
    """
    if section_path:
        return f"{section_path}\n\n{text}"
    return text

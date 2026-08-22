"""Search a course by name and by meaning.

Two matchers, unioned, over data that already exists:

* **titles** -- substring and fuzzy, in Python, over the course's own nodes. Free,
  instant, and the only one that can answer `kkt`, which is three letters that
  appear in no sentence of the book and in exactly one node's name.
* **content** -- the chunk embeddings Chroma has held since ingest, mapped back to
  the nodes that own them via `skill_nodes.source_chunk_ids`. This is the one that
  answers "which parts cover duality?", where the word the learner typed is in the
  prose rather than in any heading.

Neither is sufficient. A title matcher cannot find a concept the author gave a
different name to; a semantic matcher over 800-token chunks reliably misses a
three-letter acronym, because the acronym is a rounding error in the chunk's
vector. Unioning them costs one extra pass over a list the request already has.

**A degraded vector store is a degraded answer, not an error.** If Chroma is
unreachable the title matcher still answers, and `SearchResults.semantic` says so
-- `drill_service._retrieve_context` takes the same position for the same reason.
"""

from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import BudgetExceededError
from app.models import Chunk, Course, SkillNode
from app.schemas.drill import SourceRef
from app.schemas.explore import SearchHit, SearchResults
from app.services.llm_gateway import embed_texts_recorded
from app.vector.chroma_store import get_vector_store

# How many nodes come back. A skill tree is browsed, not paged; past twenty
# results the ranking is guessing anyway.
RESULT_LIMIT = 20
# Chunks pulled from the vector index before they are folded onto their nodes.
# Higher than RESULT_LIMIT because several chunks routinely share one node.
SEMANTIC_K = 30
# Below this, `difflib` is matching on shared letters rather than on a word.
FUZZY_FLOOR = 0.62
# A title match is an exact statement about identity; a cosine neighbour is an
# estimate. Weighted so a solid title hit always outranks a strong vector one.
FUZZY_WEIGHT = 0.8
SEMANTIC_WEIGHT = 0.78
# A vector index returns the k NEAREST chunks, never the k relevant ones, so
# without a floor every query matches every node that owns a chunk -- searching
# a course for "zzzz" came back with the whole tree at score 0.0. Set low on
# purpose: this is a "was this even in the neighbourhood" bar, and the ranking
# above it is what expresses relevance.
SEMANTIC_FLOOR = 0.15
SNIPPET_CHARS = 220

_NOISE = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    return _NOISE.sub(" ", text.lower()).strip()


def title_score(query: str, title: str, slug: str) -> float:
    """0..1 for how well a node's NAME answers this query.

    Banded rather than continuous, because the bands mean different things and a
    learner reads them that way: an exact name, a name that starts with what you
    typed, a name that contains it, and finally something that merely looks like
    it.
    """
    wanted = _normalise(query)
    if not wanted:
        return 0.0

    for candidate in (_normalise(title), _normalise(slug)):
        if not candidate:
            pass
        elif candidate == wanted:
            return 1.0
        elif candidate.startswith(wanted):
            return 0.92
        elif wanted in candidate:
            return 0.84

    ratio = SequenceMatcher(None, wanted, _normalise(title)).ratio()
    return round(ratio * FUZZY_WEIGHT, 4) if ratio >= FUZZY_FLOOR else 0.0


def snippet_for(query: str, text: str, limit: int = SNIPPET_CHARS) -> str:
    """A window of the chunk around the query, or its opening.

    Centred on the longest query word that actually occurs, so a hit deep inside
    an 800-token chunk is visible rather than being represented by the chunk's
    first two lines.
    """
    flat = " ".join(text.split())
    words = sorted((word for word in _normalise(query).split() if len(word) > 2), key=len, reverse=True)

    at = -1
    for word in words:
        if at < 0:
            at = flat.lower().find(word)

    if at < 0:
        return flat[:limit].strip()

    start = max(0, at - limit // 3)
    window = flat[start : start + limit].strip()
    return f"…{window}" if start > 0 else window


# @spec CURR-PROJ-006
def _semantic_hits(course_id: uuid.UUID, query: str) -> tuple[dict[uuid.UUID, float], bool]:
    """`(chunk id -> similarity above the floor, was the index reachable)`.

    The two are reported separately because they answer different questions. An
    empty dict from a healthy index means "nothing in this book is close to
    that", which is a real answer; an empty dict from an unreachable one means
    the results the caller is about to render are half a search.
    """
    try:
        [vector] = embed_texts_recorded([query], course_id=course_id)
        hits = get_vector_store().query(str(course_id), vector, k=SEMANTIC_K)
    except BudgetExceededError:
        raise
    except Exception:  # noqa: BLE001 -- a missing index degrades search, it does not fail it
        return {}, False

    scored: dict[uuid.UUID, float] = {}
    for hit in hits:
        try:
            chunk_id = uuid.UUID(hit.chunk_id)
        except ValueError:
            pass  # an id this course did not write; ignore rather than 500
        else:
            similarity = min(max(hit.score, 0.0), 1.0)
            if similarity >= SEMANTIC_FLOOR:
                scored[chunk_id] = max(scored.get(chunk_id, 0.0), similarity)
    return scored, True


async def search(session: AsyncSession, course: Course, query: str, limit: int = RESULT_LIMIT) -> SearchResults:
    query = query.strip()
    nodes = list(await session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)))
    if not query or not nodes:
        return SearchResults(query=query, results=[], semantic=False)

    by_chunk: dict[uuid.UUID, list[SkillNode]] = {}
    for node in nodes:
        for chunk_id in node.source_chunk_ids or ():
            by_chunk.setdefault(chunk_id, []).append(node)

    # Skip the round trip entirely when no node carries provenance: every hit
    # would be discarded on the way back.
    similarity, semantic_ok = _semantic_hits(course.id, query) if by_chunk else ({}, True)

    titles = {node.id: title_score(query, node.title, node.slug) for node in nodes}
    content: dict[uuid.UUID, tuple[float, uuid.UUID]] = {}
    for chunk_id, score in similarity.items():
        for node in by_chunk.get(chunk_id, ()):
            weighted = round(score * SEMANTIC_WEIGHT, 4)
            current = content.get(node.id)
            # Keep the best-scoring chunk per node: it is both the node's rank
            # and the passage the snippet is cut from.
            if current is None or weighted > current[0]:
                content[node.id] = (weighted, chunk_id)

    ranked = [
        (node, max(titles[node.id], content.get(node.id, (0.0, None))[0]))
        for node in nodes
        if titles[node.id] > 0 or node.id in content
    ]
    ranked.sort(key=lambda pair: (-pair[1], pair[0].title))
    ranked = ranked[:limit]

    wanted_chunks = {content[node.id][1] for node, _ in ranked if node.id in content}
    wanted_chunks |= {
        node.source_chunk_ids[0]
        for node, _ in ranked
        if node.id not in content and node.source_chunk_ids
    }
    chunks = (
        {chunk.id: chunk for chunk in await session.scalars(select(Chunk).where(Chunk.id.in_(wanted_chunks)))}
        if wanted_chunks
        else {}
    )

    results: list[SearchHit] = []
    for node, score in ranked:
        matched = content.get(node.id)
        chunk_id = matched[1] if matched else (node.source_chunk_ids[0] if node.source_chunk_ids else None)
        chunk = chunks.get(chunk_id) if chunk_id else None
        results.append(
            SearchHit(
                node_id=node.id,
                slug=node.slug,
                title=node.title,
                summary=node.summary,
                assessable=node.assessable,
                depth=node.depth,
                score=score,
                match=_match_kind(titles[node.id] > 0, matched is not None),
                snippet=snippet_for(query, chunk.text) if (chunk and matched) else node.summary,
                source=(
                    SourceRef(
                        document_id=chunk.document_id,
                        section_path=chunk.section_path,
                        page_start=chunk.page_start,
                    )
                    if chunk
                    else None
                ),
            )
        )

    return SearchResults(query=query, results=results, semantic=semantic_ok)


def _match_kind(by_title: bool, by_content: bool) -> str:
    if by_title and by_content:
        return "both"
    if by_title:
        return "title"
    return "content"

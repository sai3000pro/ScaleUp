"""Ask a course a question, and get an answer that cites its own nodes.

The inverse of `drill_service`, which only ever asks questions *at* the learner.
Same retrieval path, same seam, opposite direction.

Three things make the answer worth trusting, and all three are enforced here
rather than requested in the prompt:

* **Closed passages.** The model is shown a bounded set of retrieved chunks and
  the node each belongs to. A citation naming anything it was not shown is
  discarded -- the same rule `prereqs._absorb` applies to inferred edges.
* **Quotes are verified.** `quote` must be a substring of the chunk it cites,
  compared with whitespace flattened. A citation whose quote is not in the text
  is a paraphrase wearing a citation's clothes, and it is dropped.
* **Retrieval failure is visible.** `AskAnswer.retrieved` is the number of
  passages the model actually saw. Zero there and a confident answer would be a
  contradiction; with zero passages the fake and a real model are both told to
  say the material does not cover it.

The vector index is preferred and a lexical scan is the fallback, so a course
whose Chroma collection has been dropped still answers -- badly, but honestly,
and without a 500 on the one endpoint a learner reaches for when stuck.
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.llm.base import BudgetExceededError, LLMRole, RefusalError, SchemaValidationError
from app.models import Chunk, Course, SkillNode
from app.schemas.drill import SourceRef
from app.schemas.explore import AskAnswer, Citation
from app.services.llm_gateway import embed_texts_recorded, recording_llm_client
from app.vector.chroma_store import get_vector_store

logger = logging.getLogger(__name__)

# Passages the model is shown. Six 800-token chunks is a large prompt already,
# and past that the model starts citing the least relevant one to look thorough.
RETRIEVAL_K = 6
# How much of each chunk is rendered. Whole, unless the chunker was configured
# far larger than it is today.
PASSAGE_CHARS = 2400
# Terms used by the lexical fallback, longest first -- the long words in a
# question are the ones carrying the subject.
LEXICAL_TERMS = 3
_WORD = re.compile(r"[A-Za-z][A-Za-z-]{3,}")

NO_MATERIAL = "There is nothing indexed for this course yet, so there is no material to answer from."


def _flat(text: str) -> str:
    return " ".join(text.split())


def render_passages(passages: list[tuple[SkillNode, Chunk]]) -> str:
    """The passage listing the prompt shows the model.

    Machine-parseable, and read back by `fake_provider._parse_passages`, so the
    deterministic provider sees exactly the rendering a real one does. The ids
    are printed in full because the model is asked to copy them back: a citation
    is only useful if it resolves to a node the UI can select.
    """
    return "\n\n".join(
        f"### `{node.slug}` — {node.title}\n"
        f"node_id: {node.id}\n"
        f"chunk_id: {chunk.id}\n"
        f"{_flat(chunk.text)[:PASSAGE_CHARS]}"
        for node, chunk in passages
    )


def _owner_of(chunk_id: uuid.UUID, nodes: list[SkillNode]) -> SkillNode | None:
    """The node this chunk is provenance for.

    Prefers an assessable one: with segmentation on, a chunk belongs both to the
    section and to the fragment inside it, and a citation should point at
    something the learner can actually drill.
    """
    owners = [node for node in nodes if chunk_id in (node.source_chunk_ids or ())]
    drillable = [node for node in owners if node.assessable]
    chosen = drillable or owners
    return chosen[0] if chosen else None


# @spec CURR-PROJ-005, CURR-PROJ-006
async def _vector_chunk_ids(course_id: uuid.UUID, question: str) -> list[uuid.UUID]:
    try:
        [vector] = await run_in_threadpool(embed_texts_recorded, [question], course_id=course_id)
        hits = get_vector_store().query(str(course_id), vector, k=RETRIEVAL_K)
    except BudgetExceededError:
        raise
    except Exception:  # noqa: BLE001 -- falls back to a lexical scan below
        logger.warning("vector retrieval unavailable for course %s; falling back to a lexical scan", course_id)
        return []

    found: list[uuid.UUID] = []
    for hit in hits:
        try:
            found.append(uuid.UUID(hit.chunk_id))
        except ValueError:
            pass  # not an id this course wrote
    return found


async def _lexical_chunks(session: AsyncSession, course_id: uuid.UUID, question: str) -> list[Chunk]:
    terms = sorted({word.lower() for word in _WORD.findall(question)}, key=len, reverse=True)[:LEXICAL_TERMS]
    if not terms:
        return []
    statement = (
        select(Chunk)
        .where(Chunk.course_id == course_id)
        .where(or_(*[Chunk.text.ilike(f"%{term}%") for term in terms]))
        .order_by(Chunk.ordinal)
        .limit(RETRIEVAL_K)
    )
    return list(await session.scalars(statement))


async def retrieve(session: AsyncSession, course: Course, question: str) -> list[tuple[SkillNode, Chunk]]:
    """Passages, each paired with the node that owns it.

    A chunk with no owning node is dropped rather than cited anonymously: a
    citation the UI cannot resolve to an orb is not a citation, it is a footnote.
    """
    nodes = list(await session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)))
    if not nodes:
        return []

    chunk_ids = await _vector_chunk_ids(course.id, question)
    if chunk_ids:
        found = {chunk.id: chunk for chunk in await session.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))}
        chunks = [found[cid] for cid in chunk_ids if cid in found]
    else:
        chunks = await _lexical_chunks(session, course.id, question)

    passages: list[tuple[SkillNode, Chunk]] = []
    for chunk in chunks:
        owner = _owner_of(chunk.id, nodes)
        if owner is None:
            logger.debug("chunk %s is retrieved but owned by no node; not citable", chunk.id)
        else:
            passages.append((owner, chunk))
    return passages[:RETRIEVAL_K]


def absorb_citations(
    returned: list[dict],
    passages: list[tuple[SkillNode, Chunk]],
) -> list[Citation]:
    """Keep the citations that name a shown passage AND quote it.

    Both halves matter. The first stops the model pointing at a node it was never
    given; the second stops it pointing at one it was, over a sentence that is
    not in there. Only the second catches a fluent, plausible, invented quote,
    which is the failure mode that makes RAG worse than no answer.
    """
    by_pair = {(str(node.id), str(chunk.id)): (node, chunk) for node, chunk in passages}
    kept: list[Citation] = []
    seen: set[tuple[str, str]] = set()

    for item in returned:
        pair = (str(item.get("node_id", "")).strip(), str(item.get("chunk_id", "")).strip())
        quote = _flat(str(item.get("quote", "")))
        found = by_pair.get(pair)

        if found is None:
            logger.debug("dropping a citation naming a passage that was not shown: %s", pair)
        elif pair in seen:
            logger.debug("dropping a duplicate citation for %s", pair)
        elif quote.lower() not in _flat(found[1].text).lower():
            logger.info("dropping a citation whose quote is not in the passage it cites: %s", pair)
        else:
            seen.add(pair)
            node, chunk = found
            kept.append(
                Citation(
                    node_id=node.id,
                    node_title=node.title,
                    slug=node.slug,
                    chunk_id=chunk.id,
                    quote=quote,
                    source=SourceRef(
                        document_id=chunk.document_id,
                        section_path=chunk.section_path,
                        page_start=chunk.page_start,
                    ),
                )
            )

    return kept


async def ask(session: AsyncSession, course: Course, question: str) -> AskAnswer:
    question = question.strip()
    passages = await retrieve(session, course, question)

    if not passages:
        # Never call the model with nothing to ground it. An ungrounded answer is
        # the one thing this endpoint must not produce, and the cheapest place to
        # guarantee that is by not asking.
        return AskAnswer(question=question, answer=NO_MATERIAL, citations=[], retrieved=0)

    client = recording_llm_client(course.id)
    try:
        result = await client.structured(
            LLMRole.COURSE_QA,
            {
                "book_title": course.title,
                "question": question,
                "passages": render_passages(passages),
            },
            course_id=str(course.id),
        )
    except (SchemaValidationError, RefusalError) as exc:
        # One question, one call: unlike an ingest there is nothing to absorb the
        # failure into. Reported as an upstream failure rather than swallowed
        # into an empty answer, which the learner would read as "the book does
        # not cover this" -- the one wrong thing to tell them.
        logger.warning("course QA failed for %s: %s", course.id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The model did not return a usable answer. Try rephrasing."
        ) from exc

    return AskAnswer(
        question=question,
        answer=str(result.data.get("answer", "")).strip(),
        citations=absorb_citations(list(result.data.get("citations", [])), passages),
        retrieved=len(passages),
    )

"""The ingestion stages, as plain synchronous functions.

Celery tasks call these; the tasks themselves stay thin (load session, call
stage, update job). Keeping the stages here means they can be driven directly
from a test without a broker.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.dag import CandidateEdge
from app.ingestion import summarise
from app.ingestion.chunking import chunk_blocks
from app.ingestion.embed import batched, embedding_input
from app.ingestion.extract import RawConcept, WindowInput, extract_window, reduce_concepts
from app.ingestion.parsers.registry import parse_source
from app.ingestion.prereqs import PrereqOutcome, SkillRef, infer_prerequisites
from app.ingestion.segment import SectionInput, segment_sections
from app.ingestion.toc import (
    TocNode,
    build_introduces_edges,
    build_toc_nodes,
    is_drillable,
    owner_of_page,
    section_labels,
)
from app.llm.base import LLMClient, RefusalError, SchemaValidationError
from app.models import Chunk, Course, Document, DocumentPage
from app.services.graph_service import ConceptSpec, persist_graph
from app.services.llm_gateway import embed_texts_recorded, recording_llm_client
from app.services.object_storage import materialize_storage_path
from app.vector.chroma_store import get_vector_store

logger = logging.getLogger(__name__)

# Deterministic chunk ids. Re-chunking a document must produce the SAME ids, or
# the Chroma upsert becomes an insert and a re-ingest silently doubles the index
# while orphaning the previous vectors.
CHUNK_NAMESPACE = uuid.UUID("6f6a1f26-0b1e-4e2f-9d64-2f0a1c3b5d70")

# A document must carry at least this many words before the prose test is
# meaningful -- below it the ratio is noise.
MIN_READABLE_WORDS = 40
# English prose runs roughly a third function words. A navigation bar runs almost
# none: every label is a content word on purpose. 0.15 sits well clear of both,
# so a terse abstract passes and a menu cannot.
MIN_FUNCTION_WORD_RATIO = 0.15
_WORDS = re.compile(r"[a-z][a-z'-]*")
# Deliberately small and closed. This is a grammar test, not a topic test -- a
# longer list would start rejecting documents for their subject matter.
FUNCTION_WORDS = frozenset(
    """a an the and or but if then than that this these those of in on at to for from by with
    without into over under is are was were be been being it its as we you they he she them
    their our not no all any some such which who whom whose when where while because so
    there here can could will would shall should may might must do does did done have has
    had about after before between during through against above below up down out off again
    further once more most other only own same too very just also how what why""".split()
)


class EmptyDocumentError(ValueError):
    """The source parsed successfully and contained no readable text."""


def _require_readable_text(page_texts: list[str], filename: str, source_type: str) -> None:
    """Refuse a document whose extracted text is not prose.

    A character count alone is not enough, and the gap is not theoretical. The
    MIT OpenCourseWare landing page renders its content with JavaScript, so the
    server returns a shell -- but a shell with a navigation bar in it, which
    extracts to 717 characters. That cleared a 200-character floor, the job went
    green, and the course gained six "skills" named `Course Description`,
    `Instructor`, `Departments` and `Topics`. Site furniture rendered as a skill
    tree is worse than an outright failure, because nothing about it looks wrong
    until a learner tries to drill it.

    The signal is FUNCTION WORDS, not word density. `summarise.is_prose` was the
    obvious tool and it does not work here: it asks "are these real words,
    densely enough", and menu labels are real words -- `Course Description
    Instructor Departments Topics` scores as high-quality prose. What actually
    separates a sentence from a list of labels is the connective tissue. English
    prose runs roughly a third function words; a navigation bar has almost none,
    because every label is a content word by design.
    """
    words = [word for text in page_texts for word in _WORDS.findall(text.lower())]
    if len(words) < MIN_READABLE_WORDS:
        raise EmptyDocumentError(_no_text_message(filename, source_type))

    function_ratio = sum(1 for word in words if word in FUNCTION_WORDS) / len(words)
    if function_ratio >= MIN_FUNCTION_WORD_RATIO:
        return

    raise EmptyDocumentError(_no_text_message(filename, source_type))


def _no_text_message(filename: str, source_type: str) -> str:
    """Name the remedy that fits the format. Enabling JavaScript does not help a
    scan, and OCR does not help a single-page app."""
    hint = (
        "the page may render its content with JavaScript, or be a navigation-only shell"
        if source_type == "html"
        else "a scanned PDF needs OCR to gain a text layer"
    )
    return f"{filename}: no readable prose was extracted -- {hint}."


def chunk_id_for(document_id: uuid.UUID, ordinal: int) -> uuid.UUID:
    return uuid.uuid5(CHUNK_NAMESPACE, f"{document_id}:{ordinal}")


@dataclass(frozen=True, slots=True)
class StageResult:
    pages: int = 0
    chunks: int = 0
    embedded: int = 0
    windows: int = 0
    windows_failed: int = 0
    concepts_raw: int = 0
    concepts_merged: int = 0
    edges_accepted: int = 0
    edges_rejected: int = 0


def parse_document(session: Session, document_id: uuid.UUID) -> StageResult:
    """source file -> document_pages. Idempotent: replaces this document's pages."""
    document = session.get(Document, document_id)
    if document is None:
        raise LookupError(f"document {document_id} not found")

    parsed = parse_source(document.source_type, materialize_storage_path(document.storage_path))

    _require_readable_text(parsed.page_texts, document.filename, document.source_type)

    session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
    session.flush()

    for index, text in enumerate(parsed.page_texts):
        session.add(DocumentPage(document_id=document_id, page_index=index, text=text, char_count=len(text)))

    document.page_count = parsed.page_count
    session.flush()

    return StageResult(pages=parsed.page_count)


# @spec CURR-PARSE-003
def chunk_document(session: Session, document_id: uuid.UUID) -> StageResult:
    """document_pages -> chunks.

    Re-parses from the stored file rather than the page rows, because chunking
    needs heading levels and those are a parse-time signal. Storing the pages is
    still worth it: it makes the parse stage's output inspectable, and a future
    re-chunk with different parameters never has to re-read a 1000-page PDF for
    its *text*.
    """
    settings = get_settings()
    document = session.get(Document, document_id)
    if document is None:
        raise LookupError(f"document {document_id} not found")

    parsed = parse_source(document.source_type, materialize_storage_path(document.storage_path))
    chunk_kwargs = {}
    if parsed.hard_boundary_level is not None:
        # The parser, not this function, decides how deep a heading still ends a
        # chunk -- see `ParsedDocument.hard_boundary_level`. Omitted entirely
        # when the parser has no opinion, so the chunker's own default stays the
        # single place that number is written down.
        chunk_kwargs["hard_boundary_level"] = parsed.hard_boundary_level

    chunks = chunk_blocks(
        parsed.blocks,
        max_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        **chunk_kwargs,
    )

    session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    session.flush()

    for chunk in chunks:
        session.add(
            Chunk(
                id=chunk_id_for(document_id, chunk.ordinal),
                document_id=document_id,
                course_id=document.course_id,
                ordinal=chunk.ordinal,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_path=chunk.section_path,
                text=chunk.text,
                token_count=chunk.token_count,
                content_sha256=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
            )
        )
    session.flush()

    return StageResult(chunks=len(chunks))


def _embed_chunks(session: Session, course_id: uuid.UUID, chunks: list[Chunk]) -> int:
    """Embed and upsert `chunks` into the course's collection. Returns the count.

    The batching loop, shared by `embed_document` (one document, incremental) and
    `embed_course` (the whole course, from scratch). The two differ only in which
    vectors they clear first and which chunks they select; the write itself must
    be identical or a reindex would populate the index in a different shape from
    the ingest that first built it.
    """
    settings = get_settings()
    store = get_vector_store()
    collection = str(course_id)
    embedded = 0

    for group in batched(chunks, settings.embed_batch_size):
        vectors = embed_texts_recorded(
            [embedding_input(c.section_path, c.text) for c in group], course_id=course_id
        )
        store.upsert(
            course_id=collection,
            chunk_ids=[str(c.id) for c in group],
            embeddings=vectors,
            metadatas=[
                {
                    "document_id": str(c.document_id),
                    "ordinal": c.ordinal,
                    "page_start": c.page_start,
                    "section_path": c.section_path or "",
                }
                for c in group
            ],
            documents=[c.text for c in group],
        )
        for chunk in group:
            chunk.vector_id = str(chunk.id)
        embedded += len(group)
        session.flush()

    return embedded


def embed_document(session: Session, document_id: uuid.UUID) -> StageResult:
    """chunks -> Chroma. Upserts by chunk id, so redelivery is a no-op."""
    document = session.get(Document, document_id)
    if document is None:
        raise LookupError(f"document {document_id} not found")

    chunks = list(
        session.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal))
    )
    if not chunks:
        return StageResult()

    # Clear this document's existing vectors first. Deterministic chunk ids make
    # the upsert below a true upsert, but a re-chunk that produces FEWER chunks
    # would otherwise leave the tail of the previous run orphaned in the index.
    # Scoped to the document, because the course's OTHER documents are fine.
    get_vector_store().drop_document(str(document.course_id), str(document_id))

    return StageResult(embedded=_embed_chunks(session, document.course_id, chunks))


def embed_course(session: Session, course_id: uuid.UUID) -> StageResult:
    """Every committed chunk in a course -> a freshly created Chroma collection.

    The vector half of a reindex.

    One Postgres write happens here and it is worth naming, because "a reindex
    never writes Postgres" is the rule the whole feature is built on:
    `_embed_chunks` sets `chunks.vector_id`. That column is bookkeeping *about*
    the derived index -- "which id did we store this chunk under?" -- not
    authoritative content, the value is deterministic (`str(chunk.id)`), and so
    the write is an idempotent no-op on a healthy course. It is also the right
    thing to do on an unhealthy one: after a successful re-embed the vectors
    exist, and leaving `vector_id` NULL because a rule was read too literally
    would leave Postgres describing an index state that is not true.

    Nothing else is touched. No node, no edge, no `node_progress` row, and not
    `graph_version`.

    `drop_course` rather than `drop_document` per document: the reason to run a
    reindex at all is that the index is suspected wrong -- half-written, holding
    vectors from a chunking scheme two versions ago, or embedded by a model that
    has since changed. Deleting the collection outright is the only clear that
    cannot leave behind whatever was wrong with it, and it is the call
    `chroma_store.drop_course` was written for and has never had.
    """
    course = session.get(Course, course_id)
    if course is None:
        raise LookupError(f"course {course_id} not found")

    chunks = list(
        session.scalars(select(Chunk).where(Chunk.course_id == course_id).order_by(Chunk.ordinal))
    )

    get_vector_store().drop_course(str(course_id))
    if not chunks:
        # A course with no chunks reindexes to an empty collection, which is the
        # correct end state and not an error -- the graph may still project.
        return StageResult()

    return StageResult(embedded=_embed_chunks(session, course_id, chunks))


def _build_windows(chunks: list[Chunk], per_window: int) -> list[WindowInput]:
    """Group chunks into extraction windows, never crossing a top-level section.

    Crossing a chapter boundary inside one window is how you get a concept whose
    definition came from chapter 3 and whose prerequisites came from chapter 7.
    """
    windows: list[WindowInput] = []
    current: list[Chunk] = []

    def top_section(chunk: Chunk) -> str:
        return (chunk.section_path or "").split(" / ")[0]

    def flush() -> None:
        if current:
            windows.append(
                WindowInput(
                    index=len(windows),
                    section_path=current[0].section_path or "",
                    chunk_ids=tuple(str(c.id) for c in current),
                    text="\n\n".join(f"[{i}] {c.text}" for i, c in enumerate(current)),
                )
            )
            current.clear()

    for chunk in chunks:
        boundary = current and top_section(chunk) != top_section(current[0])
        if boundary or len(current) >= per_window:
            flush()
        current.append(chunk)
    flush()

    return windows


# @spec CURR-PARSE-001, CURR-PARSE-002, CURR-PARSE-004, CURR-PARSE-007, CURR-PARSE-008
def outline_concepts(
    nodes: list[TocNode],
    owned_by: dict[str, list[Chunk]],
    rename: dict[str, str],
    client: LLMClient | None = None,
    book_title: str = "",
    course_id: str | None = None,
    sections: dict[str, str] | None = None,
) -> list[ConceptSpec]:
    """Turn outline entries plus their exclusively-owned chunks into concepts.

    Pure with `client=None`, which is the default and what the tests and the
    offline scoring probe use, so the whole node-construction decision stays
    reachable without a database or a PDF.

    A heading that owns no chunk gets `assessable=False` and NO provenance.
    There used to be a fallback here that handed such a heading the first couple
    of chunks of its own subtree, on the reasoning that a node with no source
    chunks cannot be drilled. It was worse than nothing: on CO 250 it gave
    "Duality" text byte-identical to its child "Weak duality", and the
    content-derived prerequisite pass then read the child's prose and attributed
    the child's own edges to the parent. Three of them came back out of
    `build_acyclic_edges` as duplicates of the structural edges -- the pass had
    re-derived the child's relationships from a copy of the child's text.

    Copying a child's material up into its parent does not make the parent
    drillable. It makes two nodes that claim the same skill.
    """
    concepts: list[ConceptSpec] = []
    own_texts = {node.slug: " ".join(chunk.text for chunk in owned_by.get(node.slug, [])) for node in nodes}

    # The caption a learner reads. It used to be `own_text[:280]` -- the first
    # 280 characters that happened to fall inside the node's page range -- which
    # on CO 250 captioned "The KKT Theorem" with the definition of an epigraph,
    # because section 5.2 opens with the tail of 5.1. See app/ingestion/summarise.py.
    summaries = {node.slug: summarise.section_summary(node.title, own_texts[node.slug]) for node in nodes}
    if client is not None and get_settings().node_summaries_via_llm():
        briefs = [
            summarise.NodeBrief(slug=node.slug, title=node.title, text=own_texts[node.slug])
            for node in nodes
            if own_texts[node.slug].strip()
        ]
        summaries.update(summarise.summarise_nodes(client, book_title, briefs, course_id=course_id))

    for node in nodes:
        owned = owned_by.get(node.slug, [])
        summary = summaries.get(node.slug, "")

        concepts.append(
            ConceptSpec(
                slug=rename[node.slug],
                title=node.title,
                summary=summary or f"{node.title} — see pages {node.page_start + 1}-{node.page_end}.",
                # Deliberately NOT set here. Difficulty comes from the node's
                # position in the finished dependency graph, which is not known
                # until every edge -- structural and content-derived -- has been
                # resolved. `persist_graph` fills it in. See
                # `app.ingestion.toc.difficulty_from_depth`.
                difficulty=None,
                # The honest label. `assessable=True` used to be forced here
                # because an un-drillable prerequisite kept mastery 0.0 for ever
                # and locked its whole subtree. `app.domain.states.gating_
                # masteries` fixed that: a structural node is now transparent,
                # contributing its OWN prerequisites' masteries rather than its
                # non-existent one, so marking it honestly no longer quarantines
                # anything. All three read paths go through it -- graph_read,
                # drill_service, quest_service.
                assessable=is_drillable(node, len(owned)),
                source_chunk_ids=tuple(chunk.id for chunk in owned),
                mention_count=max(1, len(owned)),
                section=(sections or {}).get(node.slug),
            )
        )

    return concepts


# @spec CURR-EDGE-004
def _toc_graph(
    document: Document,
    chunks: list[Chunk],
    page_count: int,
    used_slugs: set[str] | None = None,
    used_titles: set[str] | None = None,
    client: LLMClient | None = None,
    book_title: str = "",
    course_id: str | None = None,
) -> tuple[list[ConceptSpec], list[CandidateEdge]]:
    """Build the graph contribution of ONE document, from its own outline.

    Preferred over LLM inference whenever an outline exists, because the author's
    hierarchy is better evidence than anything a model reconstructs from prose.
    See app/ingestion/toc.py for why.

    `used_slugs` carries slugs already claimed by earlier documents in the same
    course, so two books that both contain "Introduction" become two nodes
    rather than silently collapsing into one.
    """
    parsed = parse_source(document.source_type, materialize_storage_path(document.storage_path))
    nodes = build_toc_nodes(parsed.toc, page_count)
    if len(nodes) < get_settings().min_toc_entries:
        return [], []

    # Rename before anything references a slug, then apply the map to the edges
    # too, so the spine keeps pointing at the right nodes.
    claimed = used_slugs if used_slugs is not None else set()
    rename: dict[str, str] = {}
    for node in nodes:
        slug = node.slug
        suffix = 2
        while slug in claimed:
            slug = f"{node.slug}-{suffix}"
            suffix += 1
        claimed.add(slug)
        rename[node.slug] = slug

    # Each chunk belongs to exactly one entry: the deepest whose range contains
    # it. Ranges nest, so without this a chapter claims everything its sections
    # cover and gets a summary lifted from its first subsection.
    owned_by: dict[str, list[Chunk]] = {node.slug: [] for node in nodes}
    for chunk in chunks:
        owner = owner_of_page(nodes, chunk.page_start)
        if owner is not None:
            owned_by[owner.slug].append(chunk)

    sections = section_labels(nodes)
    concepts = outline_concepts(nodes, owned_by, rename, client, book_title, course_id, sections)

    # A heading that owns no chunk of its own is filing, not a skill: it is
    # dropped rather than rendered as an orb with nothing behind it, and it
    # cannot be anyone's prerequisite. See `app.ingestion.toc.section_labels`.
    concepts = [concept for concept in concepts if concept.assessable]
    drillable = {node.slug for node in nodes if owned_by[node.slug]}

    edges = [
        CandidateEdge(
            prereq=rename[edge.prereq],
            target=rename[edge.target],
            confidence=edge.confidence,
            support=edge.support,
        )
        for edge in build_introduces_edges(nodes, drillable)
    ]

    if not get_settings().segment_sections:
        return concepts, edges

    # An outline entry is a heading, not a skill. "The KKT Theorem" is one TOC
    # line covering seven distinct concepts -- subgradient, supporting
    # half-space, Slater point, the theorem itself -- and a learner cannot drill
    # or fail any one of them separately while they share a node. Split on the
    # boundaries the BOOK already marked (`Definition:`, `Theorem:`), never on
    # boundaries a model invents; see app/ingestion/segment.py.
    fragments = segment_sections(
        [
            SectionInput(
                slug=rename[node.slug],
                title=node.title,
                level=node.level,
                page_start=node.page_start,
                page_end=node.page_end,
                # Ignored downstream -- every fragment's ConceptSpec passes
                # difficulty=None so `persist_graph` derives it from graph depth
                # like any other node. SectionInput requires the field, so this
                # is a placeholder, not a decision.
                difficulty=3,
                chunks=tuple(owned_by[node.slug]),
            )
            for node in nodes
            # Structural headings are no longer nodes, so they cannot parent a
            # fragment. They own no chunks either, so this drops nothing a
            # fragment could have been cut from.
            if owned_by[node.slug]
        ],
        parsed.page_texts,
        client=client,
        book_title=book_title,
        course_id=course_id,
        claimed_slugs=claimed,
        claimed_titles=used_titles,
    )

    # Fragments inherit their section from the heading they were cut out of.
    parent_sections = {rename[node.slug]: sections[node.slug] for node in nodes}

    for fragment in fragments.all_fragments():
        concepts.append(
            ConceptSpec(
                slug=fragment.slug,
                title=fragment.title,
                summary=fragment.summary,
                # Left to the graph, like every other node: a fragment's
                # difficulty is where it lands in the dependency order, not how
                # deep in the outline its parent happened to sit.
                difficulty=None,
                assessable=True,
                key_terms=fragment.key_terms,
                source_chunk_ids=fragment.source_chunk_ids,
                mention_count=max(1, len(fragment.source_chunk_ids)),
                section=parent_sections.get(fragment.parent_slug),
            )
        )
        edges.append(
            CandidateEdge(prereq=fragment.parent_slug, target=fragment.slug, confidence=0.95, support=2)
        )

    logger.info(
        "%s: %s outline nodes, %s split into %s fragments (%s naming failures)",
        document.filename,
        len(nodes),
        fragments.sections_split,
        fragments.fragments_total,
        fragments.sections_naming_failed,
    )
    return concepts, edges


@dataclass(frozen=True, slots=True)
class CourseOutline:
    concepts: list[ConceptSpec]
    edges: list[CandidateEdge]
    # Slugs already spoken for, so a later LLM pass over the documents this
    # outline did not cover cannot collide with one of these.
    claimed_slugs: set[str]
    # Documents that contributed at least one node. The complement is the set
    # `extract_graph` has to cover some other way; before this existed it was
    # not computed at all, which is what made the drop silent.
    covered_document_ids: set[uuid.UUID]


def _course_toc_graph(session: Session, course: Course) -> CourseOutline:
    """The graph for the WHOLE course, merged across all of its documents.

    `persist_graph` replaces a course's graph wholesale, deleting any node absent
    from the concept list -- and the cascade takes that node's edges *and its
    `node_progress` rows* with it. Building the concept list from only the
    document currently being ingested therefore destroyed every other document's
    accumulated EXP and review history on the second upload. Verified: 1325 EXP
    and 9 reviews gone.

    So the unit of a graph is the COURSE, not the document. Re-ingesting one
    document rebuilds the whole course graph; nodes are matched by slug, so
    unchanged documents keep their node ids and all progress attached to them.
    """
    documents = list(
        session.scalars(
            select(Document).where(Document.course_id == course.id).order_by(Document.created_at, Document.id)
        )
    )

    concepts: list[ConceptSpec] = []
    edges: list[CandidateEdge] = []
    used_slugs: set[str] = set()
    # Titles are claimed across the WHOLE course, not per document: two books on
    # one course both defining "Convex set" must not both name a node that.
    used_titles: set[str] = set()
    covered: set[uuid.UUID] = set()
    client = recording_llm_client(course.id)

    for document in documents:
        chunks = list(
            session.scalars(
                select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.ordinal)
            )
        )
        if not chunks:
            # Uploaded but not yet chunked, or a failed parse. Contributing
            # nothing is right; contributing an empty graph is not.
            pass
        else:
            document_concepts, document_edges = _toc_graph(
                document,
                chunks,
                document.page_count or 0,
                used_slugs,
                used_titles,
                client=client,
                book_title=course.title,
                course_id=str(course.id),
            )
            concepts.extend(document_concepts)
            edges.extend(document_edges)
            if document_concepts:
                covered.add(document.id)
            else:
                logger.info(
                    "%s: outline below min_toc_entries; falling back to LLM extraction for it",
                    document.filename,
                )

    return CourseOutline(
        concepts=concepts, edges=edges, claimed_slugs=used_slugs, covered_document_ids=covered
    )


def _infer_prereq_edges(
    session: Session, course: Course, concepts: list[ConceptSpec], chunks: list[Chunk]
) -> PrereqOutcome:
    """Content-derived prerequisites, restricted to the skills we already have.

    A section's text is the chunks it owns, which `_toc_graph` already resolved
    to exactly one node each -- so this reads the same passages a drill on that
    node would draw on.

    **Structural nodes are kept out of the vocabulary entirely.** They are not
    skills, so an edge into or out of one asserts nothing a learner can act on:
    the reader of "Strong duality" cannot be told to go and learn "Duality",
    because there is nothing there to learn. Leaving them in the listing was the
    other half of the container problem -- a chapter heading whose title appears
    in its own sections' prose collects a prerequisite edge from every one of
    them, and those edges then displace the real child-to-child ones.
    """
    text_by_id = {chunk.id: chunk.text for chunk in chunks}
    ordinal_by_id = {chunk.id: chunk.ordinal for chunk in chunks}
    drillable = [c for c in concepts if c.assessable]
    # `order` must come from the chunks, never from position in this list. With
    # segmentation on, `_toc_graph` appends every fragment AFTER every outline
    # section, so list order says a page-9 fragment comes after a page-82
    # section. The reverse pass reads that as "downstream" and the backwards-edge
    # rule reads it as "against the book's order"; both were being lied to.
    skills = [
        SkillRef(
            slug=c.slug,
            title=c.title,
            summary=c.summary,
            order=min(
                (ordinal_by_id[cid] for cid in c.source_chunk_ids if cid in ordinal_by_id),
                default=0,
            ),
        )
        for c in drillable
    ]
    section_texts = {
        c.slug: " ".join(text_by_id[cid] for cid in c.source_chunk_ids if cid in text_by_id)
        for c in drillable
    }

    return infer_prerequisites(
        recording_llm_client(course.id),
        course.title,
        skills,
        section_texts,
        course_id=str(course.id),
    )


@dataclass(frozen=True, slots=True)
class _InferredGraph:
    concepts: list[ConceptSpec]
    edges: list[CandidateEdge]
    windows: int = 0
    windows_failed: int = 0
    raw_concepts: int = 0


def _llm_graph(
    client: LLMClient,
    course: Course,
    chunks: list[Chunk],
    claimed_slugs: set[str],
) -> _InferredGraph:
    """The map/reduce fallback: infer structure from prose.

    `claimed_slugs` is the outline's vocabulary. When this runs for the whole
    course it is empty and nothing is renamed; when it runs only for the
    documents an outline could not cover, a concept the model names
    "introduction" must not silently merge into an outline node of the same
    slug and inherit its chunks.
    """
    windows = _build_windows(chunks, get_settings().extract_chunks_per_window)

    raw_concepts: list[RawConcept] = []
    window_edges: list[CandidateEdge] = []
    failed = 0

    for window in windows:
        try:
            concepts, edges = extract_window(client, course.title, window)
            raw_concepts.extend(concepts)
            window_edges.extend(edges)
        except (SchemaValidationError, RefusalError) as exc:
            # Partial failure is absorbed on purpose. A book that loses 3 of 120
            # windows still yields a usable graph; failing the whole ingest over
            # it is the wrong trade. The count surfaces in stage_detail.
            failed += 1
            logger.warning("extraction window %s failed: %s", window.index, exc)

    # The dedup embeddings the reducer takes are billable too, so they go through
    # the recording seam like everything else that costs money.
    outcome = reduce_concepts(
        client,
        course.title,
        raw_concepts,
        window_edges,
        lambda texts: embed_texts_recorded(texts, course_id=course.id),
    )

    rename: dict[str, str] = {}
    for concept in outcome.concepts:
        slug = concept.slug
        suffix = 2
        while slug in claimed_slugs:
            slug = f"{concept.slug}-{suffix}"
            suffix += 1
        claimed_slugs.add(slug)
        rename[concept.slug] = slug

    return _InferredGraph(
        concepts=[
            ConceptSpec(
                slug=rename[concept.slug],
                title=concept.title,
                summary=concept.summary,
                difficulty=concept.difficulty,
                assessable=concept.assessable,
                key_terms=concept.key_terms,
                source_chunk_ids=concept.source_chunk_ids,
                mention_count=concept.mention_count,
            )
            for concept in outcome.concepts
        ],
        edges=[
            CandidateEdge(
                prereq=rename.get(edge.prereq, edge.prereq),
                target=rename.get(edge.target, edge.target),
                confidence=edge.confidence,
                support=edge.support,
            )
            for edge in outcome.edges
        ],
        windows=len(windows),
        windows_failed=failed,
        raw_concepts=outcome.raw_concept_count or len(raw_concepts),
    )


# @spec CURR-PARSE-005, CURR-EDGE-006
def extract_graph(session: Session, document_id: uuid.UUID) -> StageResult:
    """chunks -> skill graph.

    Prefers each document's table of contents as the structural spine, falling
    back to LLM map/reduce inference for whatever the outlines could not cover.

    **The fallback is per document, not per course**, and that distinction was a
    silent data loss before it was written down. `min_toc_entries` is judged one
    document at a time inside `_toc_graph`, but the branch used to be `if
    toc_concepts:` over the whole course -- so a course holding one outlined
    textbook plus three short articles took the outline path, the fallback never
    ran, and the three articles contributed nothing to the tree while their
    chunks sat in Chroma being retrieved as drill context for nodes that came
    from a different book entirely. The job was green and the course looked
    fine. Latent while most courses were one book; HTML makes it the common case.
    """
    document = session.get(Document, document_id)
    if document is None:
        raise LookupError(f"document {document_id} not found")

    course = session.get(Course, document.course_id)
    chunks = list(
        session.scalars(select(Chunk).where(Chunk.course_id == course.id).order_by(Chunk.ordinal))
    )
    if not chunks:
        return StageResult()

    client = recording_llm_client(course.id)

    # Course-wide, not document-wide: see `_course_toc_graph`. Rebuilding from
    # every document is what stops this upload deleting the previous one's
    # progress.
    outline = _course_toc_graph(session, course)

    uncovered = [chunk for chunk in chunks if chunk.document_id not in outline.covered_document_ids]
    if not uncovered:
        inferred = _InferredGraph(concepts=[], edges=[])
    else:
        if outline.concepts:
            logger.info(
                "%s chunks belong to documents with no usable outline; "
                "running LLM extraction over those alone",
                len(uncovered),
            )
        inferred = _llm_graph(client, course, uncovered, outline.claimed_slugs)

    concepts = outline.concepts + inferred.concepts
    edges = outline.edges + inferred.edges
    if not concepts:
        return StageResult(
            windows=inferred.windows,
            windows_failed=inferred.windows_failed,
            concepts_raw=inferred.raw_concepts,
        )

    # The outline gives the nodes and the nesting the author wrote down. It
    # cannot know that Strong Duality needs Weak Duality -- that is in the
    # prose. Read the sections for the edges the outline is missing, over the
    # closed vocabulary just produced. Skipped when there is no outline at all,
    # because the map/reduce path proposes its own cross-window edges and this
    # pass would be a second, redundant opinion over the same text.
    prereq_edges: list[CandidateEdge] = []
    sections_ok = 0
    sections_failed = 0
    if outline.concepts:
        prereqs = _infer_prereq_edges(session, course, concepts, chunks)
        prereq_edges = prereqs.edges
        sections_ok = prereqs.sections_ok
        sections_failed = prereqs.sections_failed

    written = persist_graph(session, course, concepts, edges + prereq_edges)
    logger.info(
        "graph: %s nodes (%s from outlines, %s inferred), %s structural edges, "
        "%s content-derived, %s windows failed, %s sections failed",
        written.node_count,
        len(outline.concepts),
        len(inferred.concepts),
        len(edges),
        len(prereq_edges),
        inferred.windows_failed,
        sections_failed,
    )
    return StageResult(
        windows=sections_ok + inferred.windows,
        windows_failed=sections_failed + inferred.windows_failed,
        concepts_raw=len(outline.concepts) + inferred.raw_concepts,
        concepts_merged=written.node_count,
        edges_accepted=written.edges_accepted,
        edges_rejected=written.edges_rejected,
    )

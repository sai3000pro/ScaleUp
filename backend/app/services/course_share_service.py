"""Course sharing: token creation/revocation, public preview, and deep copy.

The copy is the whole point of the feature: a share link is an advertisement
for a course the visitor can take home. Everything the learner could *learn*
from the source course -- documents, parsed pages, chunks, the skill graph,
and the question bank -- is copied. Everything that is *about the source
learner* is not: node progress, attempts, ingest jobs, the LLM cost ledger,
and curriculum proposals (the last are planning artifacts tied to the source
course's own ingestion).

Copied chunks keep the content-addressed `storage_path` of their documents
(the bytes are identical), but drop `vector_id`: Chroma collections are
course-scoped, so the source course's vectors are not addressable from the
copy. Semantic search therefore falls back to the lexical path until the new
owner runs the owner-scoped reindex, which rebuilds Chroma and Neo4j from
Postgres -- the documented read-model recovery path.

Copying is idempotent: the partial unique index on
(owner_id, copied_from_id) makes one learner's second copy of the same course
return the first.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Chunk,
    Course,
    CourseShare,
    Document,
    DocumentPage,
    Question,
    SkillEdge,
    SkillEdgeRejection,
    SkillNode,
    User,
)
from app.schemas.course import CourseOut
from app.schemas.share import ShareCreated, SharePreview, ShareStatus
from app.services import course_service

# Only a finished course may be shared: sharing mid-ingest would advertise (and
# copy) a partial graph whose state is about to change under the visitor.
SHAREABLE_STATUS = "ready"

MAX_TOKEN_CHARS = 128


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def share_url(token: str) -> str:
    settings = get_settings()
    return f"{settings.frontend_url.rstrip('/')}/share/{token}"


# @spec ACCESS-SHARE-005
async def get_status(session: AsyncSession, course: Course) -> ShareStatus:
    share = await session.scalar(select(CourseShare).where(CourseShare.course_id == course.id))
    return ShareStatus(course_id=course.id, shared=share is not None, created_at=share.created_at if share else None)


# @spec ACCESS-SHARE-001
async def create_share(session: AsyncSession, course: Course, owner: User) -> ShareCreated:
    """Create (or rotate) a share link for a course the caller owns.

    Rotating is done by replacement: one share per course, so creating a new
    one deletes the old token's hash and the old link stops resolving.
    """
    if course.status != SHAREABLE_STATUS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only courses in status '{SHAREABLE_STATUS}' can be shared; this course is '{course.status}'.",
        )

    existing = await session.scalar(select(CourseShare).where(CourseShare.course_id == course.id))
    if existing is not None:
        await session.delete(existing)
        # The unit of work flushes INSERTs before DELETEs, so without this the
        # new row would collide with the old one on `uq_course_shares_course_id`.
        await session.flush()

    token = secrets.token_urlsafe(32)
    session.add(
        CourseShare(
            course_id=course.id,
            token_hash=_hash_token(token),
            created_by=owner.id,
        )
    )
    await session.commit()
    return ShareCreated(course_id=course.id, url=share_url(token), created_at=course.created_at)


# @spec ACCESS-SHARE-003
async def revoke_share(session: AsyncSession, course: Course) -> None:
    share = await session.scalar(select(CourseShare).where(CourseShare.course_id == course.id))
    if share is not None:
        await session.delete(share)
        await session.commit()


async def _resolve_share(session: AsyncSession, token: str) -> tuple[CourseShare, Course]:
    if not token or len(token) > MAX_TOKEN_CHARS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found.")
    share = await session.scalar(select(CourseShare).where(CourseShare.token_hash == _hash_token(token)))
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found.")
    course = await session.get(Course, share.course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found.")
    return share, course


# @spec ACCESS-SHARE-002
async def preview(session: AsyncSession, token: str) -> SharePreview:
    _, course = await _resolve_share(session, token)
    sharer = await session.get(User, course.owner_id)
    node_count = await session.scalar(select(func.count(SkillNode.id)).where(SkillNode.course_id == course.id)) or 0
    edge_count = (
        await session.scalar(select(func.count()).select_from(SkillEdge).where(SkillEdge.course_id == course.id)) or 0
    )
    return SharePreview(
        course_id=course.id,
        title=course.title,
        description=course.description,
        status=course.status,
        node_count=node_count,
        edge_count=edge_count,
        shared_by=sharer.display_name if sharer else "a learner",
        created_at=course.created_at,
    )


# @spec PROG-META-004, PROG-META-005
async def copy_to_account(session: AsyncSession, token: str, user: User) -> tuple[CourseOut, bool]:
    """Deep-copy a shared course into the caller's account.

    Returns (course, created) -- `created` is False when the caller already
    copied this course, in which case the existing copy is returned unchanged.
    """
    _, source = await _resolve_share(session, token)
    if source.status != SHAREABLE_STATUS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The shared course is not ready to copy (status '{source.status}').",
        )

    source_root_id = source.copied_from_id or source.id
    existing = await session.scalar(
        select(Course).where(
            Course.owner_id == user.id,
            Course.copied_from_id == source_root_id,
        )
    )
    if existing is not None:
        return await course_service.project(session, existing, user.id), False

    copy = Course(
        owner_id=user.id,
        # The prefix makes the provenance obvious in the owner's list while the
        # source course still belongs to someone else; 200 chars is the column
        # limit, so a max-length title is truncated rather than rejected.
        title=f"Copy of {source.title}"[:200],
        description=source.description,
        status=SHAREABLE_STATUS,
        graph_version=0,
        # Keep every descendant in the original course's cohort. A learner can
        # share a copy too, but that must not create a second disconnected
        # leaderboard lineage.
        copied_from_id=source_root_id,
    )
    session.add(copy)
    await session.flush()

    # ── documents, pages, chunks ─────────────────────────────────────────
    document_id_map: dict[uuid.UUID, uuid.UUID] = {}
    chunk_id_map: dict[uuid.UUID, uuid.UUID] = {}
    source_documents = (
        await session.scalars(select(Document).where(Document.course_id == source.id).order_by(Document.created_at))
    ).all()
    for document in source_documents:
        new_document = Document(
            course_id=copy.id,
            source_type=document.source_type,
            filename=document.filename,
            source_uri=document.source_uri,
            content_sha256=document.content_sha256,
            # Content-addressed: identical bytes live at one path in both local
            # storage and GCS, so the copy can point at the same object.
            storage_path=document.storage_path,
            page_count=document.page_count,
            byte_size=document.byte_size,
        )
        session.add(new_document)
        await session.flush()
        document_id_map[document.id] = new_document.id

        for page in await session.scalars(
            select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.page_index)
        ):
            session.add(
                DocumentPage(
                    document_id=new_document.id,
                    page_index=page.page_index,
                    text=page.text,
                    char_count=page.char_count,
                )
            )

        for chunk in await session.scalars(
            select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.ordinal)
        ):
            new_chunk = Chunk(
                document_id=new_document.id,
                course_id=copy.id,
                ordinal=chunk.ordinal,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_path=chunk.section_path,
                text=chunk.text,
                token_count=chunk.token_count,
                content_sha256=chunk.content_sha256,
                # The source course's Chroma collection is not addressable from
                # this course; the copy starts vectorless and a reindex builds
                # its own.
                vector_id=None,
            )
            session.add(new_chunk)
            await session.flush()
            chunk_id_map[chunk.id] = new_chunk.id

    # ── the skill graph ──────────────────────────────────────────────────
    node_id_map: dict[uuid.UUID, uuid.UUID] = {}
    source_nodes = (
        await session.scalars(select(SkillNode).where(SkillNode.course_id == source.id).order_by(SkillNode.depth))
    ).all()
    for node in source_nodes:
        new_node = SkillNode(
            course_id=copy.id,
            slug=node.slug,
            title=node.title,
            summary=node.summary,
            key_terms=list(node.key_terms),
            difficulty=node.difficulty,
            depth=node.depth,
            assessable=node.assessable,
            source_chunk_ids=[chunk_id_map[cid] for cid in node.source_chunk_ids if cid in chunk_id_map],
            mention_count=node.mention_count,
        )
        session.add(new_node)
        await session.flush()
        node_id_map[node.id] = new_node.id

    for edge in await session.scalars(select(SkillEdge).where(SkillEdge.course_id == source.id)):
        session.add(
            SkillEdge(
                prereq_id=node_id_map[edge.prereq_id],
                target_id=node_id_map[edge.target_id],
                course_id=copy.id,
                confidence=edge.confidence,
                support=edge.support,
                is_reduced=edge.is_reduced,
                rationale=edge.rationale,
                source_chunk_ids=[chunk_id_map[cid] for cid in edge.source_chunk_ids if cid in chunk_id_map],
            )
        )

    for rejection in await session.scalars(
        select(SkillEdgeRejection).where(SkillEdgeRejection.course_id == source.id)
    ):
        session.add(
            SkillEdgeRejection(
                course_id=copy.id,
                prereq_slug=rejection.prereq_slug,
                target_slug=rejection.target_slug,
                reason=rejection.reason,
                confidence=rejection.confidence,
                cycle_path=list(rejection.cycle_path),
            )
        )

    # ── the question bank ────────────────────────────────────────────────
    for question in await session.scalars(select(Question).where(Question.course_id == source.id)):
        session.add(
            Question(
                node_id=node_id_map[question.node_id],
                course_id=copy.id,
                question_type=question.question_type,
                question_text=question.question_text,
                options=question.options,
                correct_option_id=question.correct_option_id,
                accepted_answers=question.accepted_answers,
                code_language=question.code_language,
                code_requirements=question.code_requirements,
                rubric=question.rubric,
                difficulty=question.difficulty,
                source_chunk_ids=[chunk_id_map[cid] for cid in question.source_chunk_ids if cid in chunk_id_map],
                prompt_version=question.prompt_version,
            )
        )

    await session.commit()
    await session.refresh(copy)
    return await course_service.project(session, copy, user.id), True

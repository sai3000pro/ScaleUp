"""Course CRUD and the aggregate counts the course list needs."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.shelves import shelf_for
from app.domain.states import MASTERED_LEVEL, MASTERED_MASTERY
from app.models import Chunk, Course, CurriculumVersion, Document, NodeProgress, SkillEdge, SkillNode
from app.schemas.course import CourseCreate, CourseDetail, CourseOut, DocumentSummary


async def create(session: AsyncSession, owner_id: uuid.UUID, payload: CourseCreate) -> CourseOut:
    course = Course(owner_id=owner_id, title=payload.title.strip(), description=payload.description)
    session.add(course)
    await session.commit()
    await session.refresh(course)
    return await project(session, course, owner_id)


async def get_owned(session: AsyncSession, course_id: uuid.UUID, owner_id: uuid.UUID) -> Course:
    """Fetch a course the caller owns, or 404.

    Deliberately 404 rather than 403 for someone else's course -- a 403 confirms
    the id exists, which is an enumeration oracle.
    """
    course = await session.get(Course, course_id)
    if course is None or course.owner_id != owner_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found.")
    return course


async def list_for_owner(session: AsyncSession, owner_id: uuid.UUID) -> list[CourseOut]:
    courses = (
        await session.scalars(
            select(Course).where(Course.owner_id == owner_id).order_by(Course.created_at.desc())
        )
    ).all()
    return [await project(session, course, owner_id) for course in courses]


async def detail(session: AsyncSession, course: Course, owner_id: uuid.UUID) -> CourseDetail:
    rows = await session.execute(
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.course_id == course.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
    )

    documents = [
        DocumentSummary(
            id=document.id,
            filename=document.filename,
            source_type=document.source_type,
            source_uri=document.source_uri,
            page_count=document.page_count,
            chunk_count=chunk_count,
            created_at=document.created_at,
        )
        for document, chunk_count in rows
    ]

    provenance = await session.scalar(
        select(CurriculumVersion.compiler_version)
        .where(CurriculumVersion.course_id == course.id, CurriculumVersion.status == "published")
        .order_by(CurriculumVersion.published_at.desc())
        .limit(1)
    )

    base = await project(session, course, owner_id)
    return CourseDetail(**base.model_dump(), documents=documents, curriculum_provenance=provenance)


# @spec CURR-SHELF-001
async def project(session: AsyncSession, course: Course, owner_id: uuid.UUID) -> CourseOut:
    node_count = await session.scalar(select(func.count(SkillNode.id)).where(SkillNode.course_id == course.id)) or 0
    edge_count = (
        await session.scalar(select(func.count()).select_from(SkillEdge).where(SkillEdge.course_id == course.id)) or 0
    )
    mastered_count = (
        await session.scalar(
            select(func.count())
            .select_from(NodeProgress)
            .join(SkillNode, SkillNode.id == NodeProgress.node_id)
            .where(
                SkillNode.course_id == course.id,
                NodeProgress.user_id == owner_id,
                NodeProgress.level >= MASTERED_LEVEL,
                NodeProgress.mastery >= MASTERED_MASTERY,
            )
        )
        or 0
    )

    return CourseOut(
        id=course.id,
        title=course.title,
        description=course.description,
        status=course.status,
        shelf=shelf_for(course.id),
        graph_version=course.graph_version,
        node_count=node_count,
        edge_count=edge_count,
        mastered_count=mastered_count,
        created_at=course.created_at,
    )

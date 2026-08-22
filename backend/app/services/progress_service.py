"""Course progress analytics derived from review facts.

Attempts are the historical source for the trend, while `node_progress` remains
current state. Nothing here is stored: changing the mastery or decay rules does
not require a backfill job.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.srs import update_mastery
from app.domain.states import MASTERED_LEVEL, MASTERED_MASTERY
from app.models import Attempt, Chunk, Course, Document, NodeProgress, SkillNode
from app.schemas.progress import ProgressAnalytics, ProgressSourceCoverage, ProgressTrendPoint


async def build_analytics(
    session: AsyncSession,
    course: Course,
    user_id: uuid.UUID,
) -> ProgressAnalytics:
    """Return one course's progress without exposing another owner's attempts."""
    node_rows = list(
        await session.execute(
            select(SkillNode, NodeProgress)
            .outerjoin(
                NodeProgress,
                and_(
                    NodeProgress.node_id == SkillNode.id,
                    NodeProgress.user_id == user_id,
                ),
            )
            .where(SkillNode.course_id == course.id, SkillNode.assessable.is_(True))
        )
    )
    nodes = [node for node, _ in node_rows]
    progress_by_node = {node.id: progress for node, progress in node_rows if progress is not None}
    total_skills = len(nodes)
    started_skills = sum(1 for progress in progress_by_node.values() if progress.last_reviewed_at is not None)
    mastered_skills = sum(
        1
        for progress in progress_by_node.values()
        if progress.level >= MASTERED_LEVEL and progress.mastery >= MASTERED_MASTERY
    )

    attempts = list(
        await session.scalars(
            select(Attempt)
            .where(
                Attempt.user_id == user_id,
                Attempt.course_id == course.id,
                Attempt.status == "graded",
            )
            .order_by(Attempt.graded_at, Attempt.created_at, Attempt.id)
        )
    )

    total_attempts = len(attempts)
    scores = [float(attempt.score or 0.0) for attempt in attempts]
    average_score = round(sum(scores) / total_attempts, 4) if total_attempts else None
    exp_earned = sum(attempt.exp_awarded for attempt in attempts)

    mastery_by_node: dict[uuid.UUID, float] = defaultdict(float)
    daily: dict[date, dict[str, float | int]] = {}
    for attempt in attempts:
        attempt_date = _attempt_date(attempt)
        score = float(attempt.score or 0.0)
        mastery_by_node[attempt.node_id] = update_mastery(mastery_by_node[attempt.node_id], score)
        point = daily.setdefault(
            attempt_date,
            {"attempts": 0, "score": 0.0, "exp": 0, "mastery": 0.0},
        )
        point["attempts"] = int(point["attempts"]) + 1
        point["score"] = float(point["score"]) + score
        point["exp"] = int(point["exp"]) + attempt.exp_awarded
        point["mastery"] = (
            sum(mastery_by_node.values()) / total_skills if total_skills else 0.0
        )

    mastery_trend = [
        ProgressTrendPoint(
            date=day,
            attempts=int(point["attempts"]),
            average_score=round(float(point["score"]) / int(point["attempts"]), 4),
            mastery=round(float(point["mastery"]), 4),
            exp_earned=int(point["exp"]),
        )
        for day, point in sorted(daily.items())
    ]
    review_days = len(mastery_trend)
    tracked_days = _tracked_days(mastery_trend)
    consistency = round(review_days / tracked_days, 4) if tracked_days else 0.0

    source_coverage = await _source_coverage(session, course.id, nodes, attempts, progress_by_node)

    return ProgressAnalytics(
        course_id=course.id,
        total_skills=total_skills,
        started_skills=started_skills,
        mastered_skills=mastered_skills,
        total_attempts=total_attempts,
        average_score=average_score,
        exp_earned=exp_earned,
        review_days=review_days,
        tracked_days=tracked_days,
        consistency=consistency,
        mastery_trend=mastery_trend,
        source_coverage=source_coverage,
    )


def _attempt_date(attempt: Attempt) -> date:
    timestamp = attempt.graded_at or attempt.created_at
    return timestamp.date()


def _tracked_days(trend: list[ProgressTrendPoint]) -> int:
    if not trend:
        return 0
    return max(1, (date.today() - trend[0].date).days + 1)


async def _source_coverage(
    session: AsyncSession,
    course_id: uuid.UUID,
    nodes: list[SkillNode],
    attempts: list[Attempt],
    progress_by_node: dict[uuid.UUID, NodeProgress],
) -> list[ProgressSourceCoverage]:
    documents = list(await session.scalars(select(Document).where(Document.course_id == course_id)))
    chunk_rows = await session.execute(
        select(Chunk.id, Chunk.document_id).where(Chunk.course_id == course_id)
    )
    chunk_document = {chunk_id: document_id for chunk_id, document_id in chunk_rows}

    node_documents: dict[uuid.UUID, set[uuid.UUID]] = {}
    document_nodes: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for node in nodes:
        document_ids = {
            chunk_document[chunk_id]
            for chunk_id in (node.source_chunk_ids or [])
            if chunk_id in chunk_document
        }
        node_documents[node.id] = document_ids
        for document_id in document_ids:
            document_nodes[document_id].add(node.id)

    document_attempts: dict[uuid.UUID, int] = defaultdict(int)
    for attempt in attempts:
        for document_id in node_documents.get(attempt.node_id, set()):
            document_attempts[document_id] += 1

    coverage: list[ProgressSourceCoverage] = []
    for document in sorted(documents, key=lambda item: item.created_at):
        node_ids = document_nodes.get(document.id, set())
        coverage.append(
            ProgressSourceCoverage(
                document_id=document.id,
                filename=document.filename,
                skills_total=len(node_ids),
                skills_started=sum(
                    1
                    for node_id in node_ids
                    if node_id in progress_by_node and progress_by_node[node_id].last_reviewed_at is not None
                ),
                attempts=document_attempts.get(document.id, 0),
            )
        )
    return coverage

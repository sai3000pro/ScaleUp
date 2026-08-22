"""Bounded goal-to-curriculum proposals.

Search proposes URLs; it never ingests them. A second explicit approval call
selects the source set, and only a third explicit handoff calls the existing URL
ingestion service.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Course, CurriculumProposal, CurriculumSource
from app.research.policy import assess_source_policy, verify_source_policy
from app.research.providers import ResearchProviderError, ResearchResult, get_research_provider
from app.research.ranking import rank_sources, select_diverse_sources
from app.schemas.curriculum import (
    CurriculumApproval,
    CurriculumIngestAccepted,
    CurriculumIngestItem,
    CurriculumProposalCreate,
    CurriculumProposalOut,
    CurriculumSourceOut,
)
from app.services import ingest_service


async def _project(session: AsyncSession, proposal: CurriculumProposal) -> CurriculumProposalOut:
    sources = list(
        await session.scalars(
            select(CurriculumSource)
            .where(CurriculumSource.proposal_id == proposal.id)
            .order_by(CurriculumSource.rank, CurriculumSource.id)
        )
    )
    return CurriculumProposalOut(
        id=proposal.id,
        course_id=proposal.course_id,
        goal=proposal.goal,
        target_outcome=proposal.target_outcome,
        prior_knowledge=proposal.prior_knowledge,
        application_context=proposal.application_context,
        proposal_version=proposal.proposal_version,
        supersedes_id=proposal.supersedes_id,
        learner_level=proposal.learner_level,
        weekly_minutes=proposal.weekly_minutes,
        format_preference=proposal.format_preference,
        provider=proposal.provider,
        status=proposal.status,
        created_at=proposal.created_at,
        sources=[CurriculumSourceOut.model_validate(source, from_attributes=True) for source in sources],
    )


async def _owned_proposal(
    session: AsyncSession,
    course: Course,
    proposal_id: uuid.UUID,
) -> CurriculumProposal:
    proposal = await session.scalar(
        select(CurriculumProposal).where(
            CurriculumProposal.id == proposal_id,
            CurriculumProposal.course_id == course.id,
            CurriculumProposal.owner_id == course.owner_id,
        )
    )
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Curriculum proposal not found.")
    return proposal


def _search_query(payload: CurriculumProposalCreate) -> str:
    outcome = f"; victory condition: {payload.target_outcome.strip()}" if payload.target_outcome.strip() else ""
    prior = f"; prior knowledge: {payload.prior_knowledge.strip()}" if payload.prior_knowledge.strip() else ""
    application = f"; intended application: {payload.application_context.strip()}" if payload.application_context.strip() else ""
    return (
        f"{payload.goal.strip()} for a {payload.learner_level} learner; "
        f"{payload.weekly_minutes} minutes per week; prefer {payload.format_preference} resources"
        f"{outcome}{prior}{application}"
    )


def _discovery_queries(payload: CurriculumProposalCreate) -> list[str]:
    """Bound one learner goal into a few complementary search angles."""
    base = _search_query(payload)
    goal = payload.goal.strip()
    variants = [
        base,
        f"{goal} fundamentals tutorial explanations",
        f"{goal} practical project implementation examples",
        f"{goal} reference handbook research notes",
    ]
    return list(dict.fromkeys(variants))


async def create_proposal(
    session: AsyncSession,
    course: Course,
    payload: CurriculumProposalCreate,
) -> CurriculumProposalOut:
    settings = get_settings()
    limit = min(payload.max_sources, settings.research_max_results)
    try:
        provider = get_research_provider()
        queries = _discovery_queries(payload)
        per_query = max(1, min(limit, (limit + len(queries) - 1) // len(queries)))
        batches = await asyncio.gather(*(provider.search(query, per_query) for query in queries))
        results = []
        seen_urls: set[str] = set()
        discovery_angles: dict[str, str] = {}
        angle_names = ("general", "fundamentals", "practical", "reference")
        for index, batch in enumerate(batches):
            angle = angle_names[index] if index < len(angle_names) else "general"
            for result in batch:
                if result.url in seen_urls:
                    pass
                else:
                    seen_urls.add(result.url)
                    discovery_angles[result.url] = angle
                    results.append(result)
    except ResearchProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    ranked = select_diverse_sources(
        rank_sources(
        f"{payload.goal} {payload.target_outcome}".strip(),
        payload.learner_level,
        payload.format_preference,
        results,
        prior_knowledge=payload.prior_knowledge,
        application_context=payload.application_context,
        ),
        limit,
    )
    previous = await session.scalar(
        select(CurriculumProposal)
        .where(CurriculumProposal.course_id == course.id)
        .order_by(CurriculumProposal.proposal_version.desc())
        .limit(1)
    )
    proposal = CurriculumProposal(
        course_id=course.id,
        owner_id=course.owner_id,
        goal=payload.goal.strip(),
        target_outcome=payload.target_outcome.strip(),
        prior_knowledge=payload.prior_knowledge.strip(),
        application_context=payload.application_context.strip(),
        proposal_version=(previous.proposal_version + 1) if previous is not None else 1,
        supersedes_id=previous.id if previous is not None else None,
        learner_level=payload.learner_level,
        weekly_minutes=payload.weekly_minutes,
        format_preference=payload.format_preference,
        provider=settings.research_provider,
        status="draft",
    )
    session.add(proposal)
    await session.flush()

    for rank, item in enumerate(ranked, start=1):
        policy = assess_source_policy(item.result)
        session.add(
            CurriculumSource(
                proposal_id=proposal.id,
                rank=rank,
                title=item.result.title,
                url=item.result.url,
                domain=item.result.domain,
                snippet=item.result.snippet,
                discovery_angle=discovery_angles.get(item.result.url, "general"),
                published_at=item.result.published_at,
                quality_score=item.score,
                quality_reasons=item.reasons,
                policy_status=policy.status,
                robots_url=policy.robots_url,
                robots_status=policy.robots_status,
                license_status=policy.license_status,
                policy_reasons=policy.reasons,
            )
        )

    await session.commit()
    await session.refresh(proposal)
    return await _project(session, proposal)


async def check_source_policy(
    session: AsyncSession,
    course: Course,
    proposal_id: uuid.UUID,
    source_id: uuid.UUID,
) -> CurriculumProposalOut:
    """Explicitly check one candidate's robots rules and license declaration."""
    proposal = await _owned_proposal(session, course, proposal_id)
    source = await session.scalar(
        select(CurriculumSource).where(
            CurriculumSource.id == source_id,
            CurriculumSource.proposal_id == proposal.id,
        )
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Curriculum source not found.")

    result = await asyncio.to_thread(
        verify_source_policy,
        ResearchResult(
            title=source.title,
            url=source.url,
            snippet=source.snippet,
            published_at=source.published_at,
            domain=source.domain,
        ),
    )
    source.policy_status = result.status
    source.robots_url = result.robots_url
    source.robots_status = result.robots_status
    source.license_status = result.license_status
    source.policy_reasons = result.reasons
    source.policy_checked_at = datetime.now(timezone.utc) if result.checked else None
    source.policy_acknowledged = False
    if source.policy_status == "blocked":
        source.selected = False
        source.status = "proposed"

    await session.commit()
    await session.refresh(proposal)
    return await _project(session, proposal)


async def get_proposal(
    session: AsyncSession,
    course: Course,
    proposal_id: uuid.UUID,
) -> CurriculumProposalOut:
    return await _project(session, await _owned_proposal(session, course, proposal_id))


async def get_latest_proposal(
    session: AsyncSession,
    course: Course,
) -> CurriculumProposalOut | None:
    proposal = await session.scalar(
        select(CurriculumProposal)
        .where(
            CurriculumProposal.course_id == course.id,
            CurriculumProposal.owner_id == course.owner_id,
        )
        .order_by(CurriculumProposal.proposal_version.desc())
        .limit(1)
    )
    return await _project(session, proposal) if proposal is not None else None


async def approve_sources(
    session: AsyncSession,
    course: Course,
    proposal_id: uuid.UUID,
    payload: CurriculumApproval,
) -> CurriculumProposalOut:
    proposal = await _owned_proposal(session, course, proposal_id)
    if proposal.status not in {"draft", "approved"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal has already been handed off.")

    sources = list(await session.scalars(select(CurriculumSource).where(CurriculumSource.proposal_id == proposal.id)))
    source_by_id = {source.id: source for source in sources}
    unknown = [source_id for source_id in payload.source_ids if source_id not in source_by_id]
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Every approved source must belong to this proposal.")

    selected_ids = set(payload.source_ids)
    selected_sources = [source_by_id[source_id] for source_id in selected_ids]
    if any(source.policy_status == "blocked" for source in selected_sources):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A selected source is disallowed by robots.txt and cannot be approved.",
        )

    requires_acknowledgement = any(source.policy_status != "clear" for source in selected_sources)
    if requires_acknowledgement and not payload.acknowledge_policy:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Review the robots and license notes for the selected sources, then acknowledge the policy warning.",
        )

    await session.execute(
        update(CurriculumSource)
        .where(CurriculumSource.proposal_id == proposal.id)
        .values(selected=False, status="proposed", ingest_error=None, policy_acknowledged=False)
    )
    await session.execute(
        update(CurriculumSource)
        .where(
            CurriculumSource.proposal_id == proposal.id,
            CurriculumSource.id.in_(selected_ids),
        )
        .values(selected=True, status="approved", policy_acknowledged=payload.acknowledge_policy)
    )
    proposal.status = "approved"
    await session.commit()
    await session.refresh(proposal)
    return await _project(session, proposal)


async def handoff_ingestion(
    session: AsyncSession,
    course: Course,
    proposal_id: uuid.UUID,
) -> CurriculumIngestAccepted:
    proposal = await _owned_proposal(session, course, proposal_id)
    if proposal.status != "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Approve a source set before starting ingestion.")

    sources = list(
        await session.scalars(
            select(CurriculumSource)
            .where(CurriculumSource.proposal_id == proposal.id, CurriculumSource.selected.is_(True))
            .order_by(CurriculumSource.rank, CurriculumSource.id)
        )
    )
    if not sources:
        raise HTTPException(status.HTTP_409_CONFLICT, "No sources are approved for ingestion.")

    proposal.status = "ingesting"
    await session.commit()
    accepted: list[CurriculumIngestItem] = []

    for source in sources:
        try:
            result = await ingest_service.ingest_url(session, course, course.owner_id, source.url)
            source.ingest_job_id = result.job_id
            source.status = "ingesting"
            source.ingest_error = None
            accepted.append(
                CurriculumIngestItem(
                    source_id=source.id,
                    job_id=result.job_id,
                    status="accepted",
                    error=None,
                )
            )
        except HTTPException as exc:
            source.status = "failed"
            source.ingest_error = str(exc.detail)
            accepted.append(
                CurriculumIngestItem(
                    source_id=source.id,
                    job_id=None,
                    status="failed",
                    error=str(exc.detail),
                )
            )

    proposal.status = "completed"
    await session.commit()
    return CurriculumIngestAccepted(proposal_id=proposal.id, course_id=course.id, accepted=accepted)

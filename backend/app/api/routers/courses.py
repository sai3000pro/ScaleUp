from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.repositories import llm_calls
from app.schemas.campaign import CampaignBriefingOut, CampaignOutcomeEvaluationOut
from app.schemas.cost import CourseCost
from app.schemas.course import (
    CourseCreate,
    CourseDetail,
    CourseFromGoalIn,
    CourseList,
    CourseOut,
    DocumentUrlIn,
    IngestAccepted,
)
from app.schemas.curriculum import (
    CurriculumApproval,
    CurriculumCandidateOut,
    CurriculumCandidateReviewIn,
    CurriculumIngestAccepted,
    CurriculumProposalCreate,
    CurriculumProposalOut,
    CurriculumPublishOut,
    CurriculumVersionCreate,
    CurriculumVersionOut,
)
from app.schemas.graph import GraphSnapshot
from app.schemas.progress import ProgressAnalytics
from app.schemas.share import ShareCreated, ShareStatus
from app.schemas.social import CourseLeaderboard
from app.services import (
    campaign_service,
    course_service,
    course_share_service,
    curriculum_graph_service,
    curriculum_plan_service,
    curriculum_service,
    graph_read,
    ingest_service,
    progress_service,
    social_service,
)

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(payload: CourseCreate, user: CurrentUser, session: DbSession) -> CourseOut:
    return await course_service.create(session, user.id, payload)


@router.post("/from-goal", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course_from_goal(
    payload: CourseFromGoalIn, user: CurrentUser, session: DbSession
) -> CourseOut:
    """Build a published skill tree from a learner's stated goal, in one request.

    No document, no ingest, no background job: the instrument is read out of the
    sentence and the tree is assembled from the shared catalogue. A goal naming
    nothing playable is refused rather than answered with an arbitrary tree.
    """
    try:
        return await curriculum_plan_service.create_course_from_goal(session, user, payload.goal)
    except curriculum_plan_service.GoalNotUnderstoodError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("", response_model=CourseList)
async def list_courses(user: CurrentUser, session: DbSession) -> CourseList:
    return CourseList(courses=await course_service.list_for_owner(session, user.id))


@router.get("/{course_id}", response_model=CourseDetail)
async def get_course(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> CourseDetail:
    course = await course_service.get_owned(session, course_id, user.id)
    return await course_service.detail(session, course, user.id)


@router.get("/{course_id}/leaderboard", response_model=CourseLeaderboard)
async def get_leaderboard(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> CourseLeaderboard:
    """The cohort scoreboard: the original course plus every copy made from its
    share link, ranked by EXP. Owner-scoped exactly like every other course
    endpoint; only display names and aggregates are revealed."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await social_service.build_leaderboard(session, course)


@router.post("/{course_id}/share", response_model=ShareCreated, status_code=status.HTTP_201_CREATED)
async def create_share(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> ShareCreated:
    """Create (or rotate) the course's share link. Only `ready` courses qualify."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await course_share_service.create_share(session, course, user)


@router.get("/{course_id}/share", response_model=ShareStatus)
async def get_share_status(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> ShareStatus:
    """Whether a share exists. The link itself is only ever shown at creation."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await course_share_service.get_status(session, course)


@router.delete("/{course_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> None:
    """Revoke the share; the old link stops resolving immediately."""
    course = await course_service.get_owned(session, course_id, user.id)
    await course_share_service.revoke_share(session, course)


@router.get("/{course_id}/graph", response_model=GraphSnapshot)
async def get_graph(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> GraphSnapshot:
    """The skill tree for this user.

    Node state and proficiency are computed on read, so decay is continuous
    rather than stepping only when something touches the row.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await graph_read.build_snapshot(session, course, user.id)


@router.get("/{course_id}/campaign/briefing", response_model=CampaignBriefingOut)
async def get_campaign_briefing(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> CampaignBriefingOut:
    course = await course_service.get_owned(session, course_id, user.id)
    return await campaign_service.build_briefing(session, course)


@router.post("/{course_id}/campaign/evaluate", response_model=CampaignOutcomeEvaluationOut)
async def evaluate_campaign_outcome(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> CampaignOutcomeEvaluationOut:
    """Evaluate the campaign's victory condition against its generated skills on demand."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await campaign_service.evaluate_outcome(session, course)


@router.get("/{course_id}/progress", response_model=ProgressAnalytics)
async def get_progress(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> ProgressAnalytics:
    """Historical learning progress for this course and this learner."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await progress_service.build_analytics(session, course, user.id)


@router.get("/{course_id}/cost", response_model=CourseCost)
async def get_cost(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> CourseCost:
    """What this course has cost in LLM spend, attributed to role and prompt version.

    Reads the `llm_calls` ledger, which records failures too -- a schema error
    still burned output tokens.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return CourseCost(**await llm_calls.cost_summary(session, course.id, get_settings().course_llm_budget_usd))


@router.post(
    "/{course_id}/documents",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: UploadFile = File(...),
) -> IngestAccepted:
    """Accept a PDF or HTML file and queue it.

    Returns immediately -- never blocks on parsing. The format is sniffed from
    the bytes; the filename and content type are not consulted.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await ingest_service.upload_document(session, course, user.id, file)


@router.post(
    "/{course_id}/documents/url",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_document_url(
    course_id: uuid.UUID,
    payload: DocumentUrlIn,
    user: CurrentUser,
    session: DbSession,
) -> IngestAccepted:
    """Fetch a web page and queue it.

    Unlike the upload endpoint this one does block, for as long as the fetch
    takes: `content_sha256` is NOT NULL and the `(course_id, content_sha256)`
    unique constraint is the outer layer of the documented idempotency, so the
    bytes have to exist before the Document row can. Bounded by
    `URL_FETCH_TIMEOUT_SECONDS`.

    Refusals -- a private address, a disallowed port or scheme, too many
    redirects, an oversized body -- all return 400 with the reason. See
    `app.ingestion.fetch` for why the SSRF check re-runs on every redirect hop.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await ingest_service.ingest_url(session, course, user.id, payload.url)


@router.post(
    "/{course_id}/curriculum/proposals",
    response_model=CurriculumProposalOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_curriculum_proposal(
    course_id: uuid.UUID,
    payload: CurriculumProposalCreate,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumProposalOut:
    """Search for a small, reviewable source set without ingesting it."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await curriculum_service.create_proposal(session, course, payload)


@router.get(
    "/{course_id}/curriculum/proposals/latest",
    response_model=CurriculumProposalOut,
)
async def get_latest_curriculum_proposal(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumProposalOut:
    course = await course_service.get_owned(session, course_id, user.id)
    proposal = await curriculum_service.get_latest_proposal(session, course)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Curriculum proposal not found.")
    return proposal


@router.get(
    "/{course_id}/curriculum/proposals/{proposal_id}",
    response_model=CurriculumProposalOut,
)
async def get_curriculum_proposal(
    course_id: uuid.UUID,
    proposal_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumProposalOut:
    course = await course_service.get_owned(session, course_id, user.id)
    return await curriculum_service.get_proposal(session, course, proposal_id)


@router.post(
    "/{course_id}/curriculum/proposals/{proposal_id}/sources/{source_id}/policy-check",
    response_model=CurriculumProposalOut,
)
async def check_curriculum_source_policy(
    course_id: uuid.UUID,
    proposal_id: uuid.UUID,
    source_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumProposalOut:
    """Explicitly check one source's robots rules and license declaration."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await curriculum_service.check_source_policy(session, course, proposal_id, source_id)


@router.post(
    "/{course_id}/curriculum/proposals/{proposal_id}/approve",
    response_model=CurriculumProposalOut,
)
async def approve_curriculum_sources(
    course_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: CurriculumApproval,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumProposalOut:
    """Persist the learner's explicit source selection."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await curriculum_service.approve_sources(session, course, proposal_id, payload)


@router.post(
    "/{course_id}/curriculum/proposals/{proposal_id}/ingest",
    response_model=CurriculumIngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_curriculum_sources(
    course_id: uuid.UUID,
    proposal_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumIngestAccepted:
    """Hand only the approved URLs to the existing bounded URL ingest path."""
    course = await course_service.get_owned(session, course_id, user.id)
    return await curriculum_service.handoff_ingestion(session, course, proposal_id)


@router.post(
    "/{course_id}/curriculum/versions",
    response_model=CurriculumVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_curriculum_version(
    course_id: uuid.UUID,
    payload: CurriculumVersionCreate,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumVersionOut:
    """Create a draft graph; it cannot affect learner progression until published."""
    course = await course_service.get_owned(session, course_id, user.id)
    try:
        return await curriculum_graph_service.create_version_api(session, course, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get(
    "/{course_id}/curriculum/versions/{version_id}/candidates",
    response_model=list[CurriculumCandidateOut],
)
async def list_curriculum_candidates(
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[CurriculumCandidateOut]:
    course = await course_service.get_owned(session, course_id, user.id)
    try:
        return await curriculum_graph_service.list_candidates_api(session, course, version_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post(
    "/{course_id}/curriculum/versions/{version_id}/candidates/{candidate_id}/review",
    response_model=CurriculumCandidateOut,
)
async def review_curriculum_candidate(
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    candidate_id: uuid.UUID,
    payload: CurriculumCandidateReviewIn,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumCandidateOut:
    course = await course_service.get_owned(session, course_id, user.id)
    try:
        return await curriculum_graph_service.review_candidate_api(
            session,
            course,
            version_id,
            candidate_id,
            user.id,
            payload.decision,
            payload.reason,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post(
    "/{course_id}/curriculum/versions/{version_id}/publish",
    response_model=CurriculumPublishOut,
)
async def publish_curriculum_version(
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> CurriculumPublishOut:
    """Make a reviewed immutable version the learner-facing graph."""
    course = await course_service.get_owned(session, course_id, user.id)
    try:
        return await curriculum_graph_service.publish_api(session, course, version_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

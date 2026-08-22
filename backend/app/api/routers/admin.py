"""Operational endpoints for a course's derived stores.

**`/api/admin` names the SURFACE, not a privilege level.** There is no
`User.is_admin` and every route here is owner-scoped through
`course_service.get_owned`, exactly like `/api/courses/{id}/graph` -- someone
else's course is a 404 rather than a 403, so the prefix is not an enumeration
oracle either. The name is kept because `CLAUDE.md`, `docs/api_contract.md` and
`docs/archive/graph_extraction_contract.md` all already promise
`POST /api/admin/courses/{id}/reindex` by that path, and honouring three written
contracts beats a tidier prefix.

A real admin flag arrives with the first operation that is not course-scoped --
"reproject every course", "what did all users spend" -- and not before. Adding a
privilege level now would gate operations whose only legitimate user is already
the owner.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.admin import ProjectionStatus, ReindexAccepted, ReindexScope, RejectionsPage
from app.services import admin_service, course_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post(
    "/courses/{course_id}/reindex",
    response_model=ReindexAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_course(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    scope: ReindexScope = ReindexScope.ALL,
) -> ReindexAccepted:
    """Rebuild Chroma and Neo4j for this course from Postgres.

    The escape hatch that makes the derived stores safe to depend on: a wiped
    Neo4j volume or a half-written Chroma collection stops being unrecoverable
    and becomes one call.

    Reads Postgres and writes NOTHING to it. In particular this does not re-run
    extraction, so `graph_version` does not move and no `node_progress` row is
    touched -- see the module docstring of `services/admin_service` for why that
    is the single most important property of the endpoint.

    Returns 202 with a job id; poll `GET /api/jobs/{id}` exactly as for an
    upload.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await admin_service.request_reindex(session, course, scope)


@router.get("/courses/{course_id}/projection", response_model=ProjectionStatus)
async def get_projection(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> ProjectionStatus:
    """Is the projection stale?

    `CLAUDE.md` names this as *the* monitorable scalar of the whole design --
    consistency reduced from a distributed-write problem to one comparison --
    and until now nothing had ever read it.

    Never 500s on an unreachable store; that is reported in the body. Kept off
    `CourseOut` deliberately: that projection runs per course on the list page,
    and this one makes two network calls to two other services.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await admin_service.projection_status(session, course)


@router.get("/courses/{course_id}/rejections", response_model=RejectionsPage)
async def get_rejections(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RejectionsPage:
    """Edges the extractor proposed and the DAG builder refused.

    Paginated, and the pagination is not decorative: a bad prompt version
    produces thousands of rows in a single ingest, which is exactly the run
    someone opens this to understand. `by_reason` is counted over the whole
    course so the summary does not change as you page.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await admin_service.rejections(session, course, limit=limit, offset=offset)

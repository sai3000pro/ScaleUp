"""Public course-share endpoints.

`GET /api/shares/{token}` is deliberately unauthenticated: the token IS the
credential, and a share link must resolve for someone who has not created an
account yet -- that is the whole funnel. `POST /api/shares/{token}/copy`
requires authentication, because the copy lands in the caller's account.

Everything else about a course stays owner-scoped; the only leak this surface
allows is the small `SharePreview` advertised by the link itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.course import CourseOut
from app.schemas.share import SharePreview
from app.services import course_share_service

router = APIRouter(prefix="/api/shares", tags=["shares"])


@router.get("/{token}", response_model=SharePreview)
async def preview_share(token: str, session: DbSession) -> SharePreview:
    """What a visitor sees before deciding to copy. 404 for unknown/revoked tokens."""
    return await course_share_service.preview(session, token)


@router.post("/{token}/copy", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
# @spec ACCESS-SHARE-004
async def copy_shared_course(
    token: str,
    user: CurrentUser,
    session: DbSession,
    response: Response,
) -> CourseOut:
    """Deep-copy the shared course into the caller's account.

    201 when a new copy was made; 200 (same body) when the caller already
    copied this course -- copying twice must not duplicate the tree.
    """
    course, created = await course_share_service.copy_to_account(session, token, user)
    if not created:
        response.status_code = status.HTTP_200_OK
    return course

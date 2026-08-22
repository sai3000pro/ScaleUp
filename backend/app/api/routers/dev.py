"""Development-only routes.

This router is registered by `create_app` ONLY when `dev_auth_enabled` is true.
The guard is registration-time rather than a check inside the handler, so in a
deployment with the flag off the endpoint does not exist at all -- it cannot be
reached by a misconfigured proxy, and it does not appear in the OpenAPI schema.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import DbSession
from app.api.routers.auth import _set_refresh_cookie
from app.schemas.auth import TokenResponse
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["dev"])


@router.post("/dev-login", response_model=TokenResponse)
async def dev_login(session: DbSession, response: Response) -> TokenResponse:
    """Hand out a token for the dev user, no password required.

    Provisions the user if it is missing rather than 404ing, because the row is
    destroyed by every `pytest` run -- see `auth_service.ensure_dev_user`. When
    this route exists at all, it works.
    """
    user = await auth_service.ensure_dev_user(session)
    result = await auth_service.issue_auth_result(session, user)
    _set_refresh_cookie(response, result.refresh_token)
    return result.response

"""Shared FastAPI dependencies.

`get_current_user` is the single auth seam. Every protected route takes a `User`
object rather than reading a header itself, so swapping the auth mechanism later
touches exactly one function.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


# @spec ACCESS-AUTH-003, ACCESS-OWN-004
async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    unauthorised = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorised

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise unauthorised

    user = await session.get(User, user_id)
    if user is None:
        # Token is well-formed but the account is gone.
        raise unauthorised

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.schemas.auth import (
    LoginRequest,
    OAuthExchangeRequest,
    PasswordResetConsume,
    PasswordResetRequest,
    PasswordResetRequested,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_refresh_token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.deployed,
        samesite="lax",
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=get_settings().refresh_cookie_name, path="/api/auth")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: DbSession, response: Response) -> TokenResponse:
    result = await auth_service.register(session, payload)
    _set_refresh_cookie(response, result.refresh_token)
    return result.response


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: DbSession, response: Response) -> TokenResponse:
    result = await auth_service.login(session, payload.email, payload.password)
    _set_refresh_cookie(response, result.refresh_token)
    return result.response


@router.post("/password-reset/request", response_model=PasswordResetRequested, status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(payload: PasswordResetRequest, session: DbSession) -> PasswordResetRequested:
    await auth_service.request_password_reset(session, payload)
    return PasswordResetRequested(message="If that email is registered, a reset link is on its way.")


@router.post("/password-reset/consume", response_model=TokenResponse)
async def consume_password_reset(payload: PasswordResetConsume, session: DbSession, response: Response) -> TokenResponse:
    result = await auth_service.consume_password_reset(session, payload)
    _set_refresh_cookie(response, result.refresh_token)
    return result.response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, session: DbSession) -> TokenResponse:
    raw_refresh_token = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw_refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is missing.")
    result = await auth_service.refresh_auth(session, raw_refresh_token)
    _set_refresh_cookie(response, result.refresh_token)
    return result.response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: DbSession) -> Response:
    await auth_service.revoke_refresh_token(session, request.cookies.get(get_settings().refresh_cookie_name))
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/google/start")
async def google_start(session: DbSession) -> RedirectResponse:
    url = await auth_service.create_google_authorization_url(session)
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/google/callback")
async def google_callback(
    session: DbSession,
    code: str = Query(min_length=1, max_length=4096),
    state: str = Query(min_length=20, max_length=200),
) -> RedirectResponse:
    settings = get_settings()
    frontend = settings.frontend_url.rstrip("/")
    try:
        exchange_code = await auth_service.complete_google_callback(session, code, state)
    except HTTPException:
        logger.warning("Google OAuth callback was rejected", exc_info=True)
        return RedirectResponse(url=f"{frontend}/login?error=google_sign_in_failed", status_code=status.HTTP_303_SEE_OTHER)
    except Exception:  # noqa: BLE001
        logger.exception("Google OAuth callback failed")
        return RedirectResponse(url=f"{frontend}/login?error=google_sign_in_failed", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(
        url=f"{frontend}/auth/callback?code={exchange_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/google/exchange", response_model=TokenResponse)
async def google_exchange(payload: OAuthExchangeRequest, session: DbSession, response: Response) -> TokenResponse:
    result = await auth_service.exchange_google_code(session, payload.code)
    _set_refresh_cookie(response, result.refresh_token)
    return result.response


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser, session: DbSession) -> UserOut:
    return await auth_service.project_user(session, user)

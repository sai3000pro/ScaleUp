"""Registration, login, recovery, and OAuth account projection.

Transaction boundaries live in services (see CLAUDE.md § layering). OAuth uses a
short-lived server-side exchange code so an access JWT never travels in a URL.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dev_user import DEV_DISPLAY_NAME, DEV_EMAIL, DEV_PASSWORD, DEV_USER_ID
from app.core.security import (
    create_access_token,
    create_opaque_token,
    hash_opaque_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.domain.exp import level_progress
from app.models import Attempt, OAuthAccount, OAuthExchangeCode, OAuthState, PasswordResetToken, RefreshSession, User
from app.schemas.auth import PasswordResetConsume, PasswordResetRequest, RegisterRequest, TokenResponse, UserOut
from app.services import email_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthResult:
    response: TokenResponse
    refresh_token: str


# @spec ACCESS-AUTH-002, ACCESS-SESSION-001, ACCESS-SESSION-002
async def issue_auth_result(session: AsyncSession, user: User) -> AuthResult:
    """Issue an access token and persist only a hash of the refresh cookie."""
    raw_refresh_token = create_opaque_token()
    settings = get_settings()
    session.add(
        RefreshSession(
            user_id=user.id,
            token_hash=hash_opaque_token(raw_refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await session.commit()
    return AuthResult(
        response=TokenResponse(access_token=create_access_token(user.id), user=await project_user(session, user)),
        refresh_token=raw_refresh_token,
    )


async def ensure_dev_user(session: AsyncSession) -> User:
    """Return the seeded dev user, creating it if it is not there.

    `POST /api/auth/dev-login` used to 404 whenever this row was missing, with a
    message telling the developer to run `python -m app.seed`. That is a real
    instruction, and it is also a footgun that fires constantly: **pytest
    truncates every table**, including this one, so the ordinary act of running
    the test suite logs you out of your own dev environment and the login page
    then reports the feature as unavailable.

    Nothing about handing out a token for a fixed-id local user needs the rest of
    the seeded data to exist, so the row is created on demand. `python -m app.seed`
    is still what builds the seeded COURSES -- this only guarantees you can get
    in.

    The password hash is written even though dev-login does not check it, so
    that signing in with dev@example.com / devpassword123 through the normal
    form works too. A developer who types the credentials the login page shows
    them should not be told they are wrong.

    This does NOT widen who can reach the endpoint: the route is registered only
    when `dev_auth_enabled` is true, and `Settings` refuses to start with that
    flag on when `deployed` is true.
    """
    user = await session.get(User, DEV_USER_ID)
    if user is not None:
        return user

    # Someone may have registered the address by hand, in which case that row is
    # the dev account regardless of its id -- reusing it keeps a single identity
    # instead of colliding on the unique email constraint for ever.
    existing = await session.scalar(select(User).where(User.email == DEV_EMAIL))
    if existing is not None:
        return existing

    user = User(
        id=DEV_USER_ID,
        email=DEV_EMAIL,
        password_hash=hash_password(DEV_PASSWORD),
        display_name=DEV_DISPLAY_NAME,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Two dev-logins raced. The constraint held, so the row exists; whoever
        # lost the race just reads it.
        await session.rollback()
        user = await session.get(User, DEV_USER_ID) or await session.scalar(
            select(User).where(User.email == DEV_EMAIL)
        )
        if user is None:
            raise
    else:
        await session.refresh(user)

    logger.info("dev user provisioned on demand: %s", DEV_EMAIL)
    return user


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def register(session: AsyncSession, payload: RegisterRequest) -> AuthResult:
    user = User(
        email=normalise_email(payload.email),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already registered.") from None

    await session.refresh(user)
    return await issue_auth_result(session, user)


# @spec ACCESS-AUTH-005
async def login(session: AsyncSession, email: str, password: str) -> AuthResult:
    user = await session.scalar(select(User).where(User.email == normalise_email(email)))

    # Verify against a dummy hash when the user is absent so the response time
    # does not reveal whether the address exists.
    stored = user.password_hash if user else hash_password("not-a-real-password")
    ok = verify_password(password, stored)

    if not user or not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        await session.commit()

    return await issue_auth_result(session, user)


# @spec ACCESS-RECOVER-001, ACCESS-RECOVER-002, ACCESS-RECOVER-004
async def request_password_reset(session: AsyncSession, payload: PasswordResetRequest) -> None:
    """Create and email a single-use reset link without revealing account state."""
    user = await session.scalar(select(User).where(User.email == normalise_email(payload.email)))
    if user is not None:
        now = datetime.now(timezone.utc)
        await session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
        )
        raw_token = create_opaque_token()
        token = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_opaque_token(raw_token),
            expires_at=now + timedelta(minutes=get_settings().password_reset_ttl_minutes),
        )
        session.add(token)
        await session.commit()
        reset_url = f"{get_settings().frontend_url.rstrip('/')}/reset-password?token={raw_token}"
        try:
            await email_service.send_password_reset_email(user.email, user.display_name, reset_url)
        except Exception:  # noqa: BLE001
            # Do not turn this into an account-enumeration oracle. The provider
            # error is operationally visible in logs while the public response
            # remains identical for known and unknown addresses.
            logger.exception("password reset email delivery failed")


# @spec ACCESS-RECOVER-003, ACCESS-RECOVER-005
async def consume_password_reset(session: AsyncSession, payload: PasswordResetConsume) -> AuthResult:
    now = datetime.now(timezone.utc)
    token = await session.scalar(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == hash_opaque_token(payload.token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .with_for_update()
    )
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That password reset link is invalid or expired.")

    user = await session.get(User, token.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That password reset link is invalid or expired.")

    token.used_at = now
    user.password_hash = hash_password(payload.password)
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.id != token.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    await session.commit()
    return await issue_auth_result(session, user)


# @spec ACCESS-OAUTH-001, ACCESS-OAUTH-003
async def create_google_authorization_url(session: AsyncSession) -> str:
    settings = get_settings()
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in is not configured.")

    state = create_opaque_token()
    session.add(
        OAuthState(
            state_hash=hash_opaque_token(state),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.oauth_state_ttl_minutes),
        )
    )
    await session.commit()
    query = urlencode(
        {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


async def _google_identity(code: str) -> tuple[str, str, str]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.is_error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google sign-in could not be completed.")
        token_body = token_response.json()
        access_token = token_body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google did not return an access token.")
        profile_response = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_response.is_error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google profile lookup failed.")

    profile = profile_response.json()
    subject = profile.get("sub")
    email = profile.get("email")
    verified = profile.get("email_verified")
    if not isinstance(subject, str) or not isinstance(email, str) or verified is not True:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google did not provide a verified email.")
    display_name = profile.get("name")
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = normalise_email(email).split("@", 1)[0]
    return subject, normalise_email(email), display_name.strip()[:80]


# @spec ACCESS-OAUTH-004
async def complete_google_callback(session: AsyncSession, code: str, state: str) -> str:
    now = datetime.now(timezone.utc)
    oauth_state = await session.scalar(
        select(OAuthState)
        .where(
            OAuthState.state_hash == hash_opaque_token(state),
            OAuthState.used_at.is_(None),
            OAuthState.expires_at > now,
        )
        .with_for_update()
    )
    if oauth_state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The Google sign-in session is invalid or expired.")
    oauth_state.used_at = now
    await session.commit()

    subject, email, display_name = await _google_identity(code)
    account = await session.scalar(
        select(OAuthAccount).where(OAuthAccount.provider == "google", OAuthAccount.provider_account_id == subject)
    )
    if account is not None:
        user = await session.get(User, account.user_id)
    else:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(create_opaque_token()), display_name=display_name)
            session.add(user)
            await session.flush()
        session.add(OAuthAccount(user_id=user.id, provider="google", provider_account_id=subject))

    if user is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google account could not be linked.")
    exchange_code = create_opaque_token()
    session.add(
        OAuthExchangeCode(
            user_id=user.id,
            code_hash=hash_opaque_token(exchange_code),
            expires_at=now + timedelta(minutes=get_settings().oauth_exchange_code_ttl_minutes),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That Google account is already linked.") from None
    return exchange_code


# @spec ACCESS-OAUTH-004, ACCESS-OAUTH-005
async def exchange_google_code(session: AsyncSession, code: str) -> AuthResult:
    now = datetime.now(timezone.utc)
    exchange = await session.scalar(
        select(OAuthExchangeCode)
        .where(
            OAuthExchangeCode.code_hash == hash_opaque_token(code),
            OAuthExchangeCode.used_at.is_(None),
            OAuthExchangeCode.expires_at > now,
        )
        .with_for_update()
    )
    if exchange is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That Google sign-in code is invalid or expired.")
    user = await session.get(User, exchange.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That Google sign-in code is invalid or expired.")
    exchange.used_at = now
    await session.commit()
    return await issue_auth_result(session, user)


# @spec ACCESS-SESSION-003, ACCESS-SESSION-005
async def refresh_auth(session: AsyncSession, raw_refresh_token: str) -> AuthResult:
    """Rotate a refresh token; reuse of an old token revokes its active family."""
    now = datetime.now(timezone.utc)
    refresh_session = await session.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_hash == hash_opaque_token(raw_refresh_token))
        .with_for_update()
    )
    invalid = refresh_session is None or refresh_session.expires_at <= now or refresh_session.revoked_at is not None
    if invalid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is invalid or expired.")

    if refresh_session.used_at is not None:
        await session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == refresh_session.user_id,
                RefreshSession.used_at.is_(None),
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token reuse detected; sign in again.")

    user = await session.get(User, refresh_session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is invalid or expired.")

    refresh_session.used_at = now
    return await issue_auth_result(session, user)


# @spec ACCESS-SESSION-004
async def revoke_refresh_token(session: AsyncSession, raw_refresh_token: str | None) -> None:
    """Revoke the presented refresh cookie without revealing whether it existed."""
    if not raw_refresh_token:
        return
    refresh_session = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_opaque_token(raw_refresh_token)).with_for_update()
    )
    if refresh_session is not None and refresh_session.revoked_at is None:
        refresh_session.revoked_at = datetime.now(timezone.utc)
        await session.commit()


# @spec PROG-META-006, PROG-META-007
async def streak_days(session: AsyncSession, user_id: uuid.UUID, today: date | None = None) -> int:
    """Consecutive days, walking back from today, with at least one attempt."""
    anchor = today or datetime.now(timezone.utc).date()

    rows = await session.execute(
        select(func.date(Attempt.created_at))
        .where(Attempt.user_id == user_id)
        .group_by(func.date(Attempt.created_at))
        .order_by(func.date(Attempt.created_at).desc())
        .limit(400)
    )
    active = {row[0] for row in rows}
    if not active:
        return 0

    # A streak may legitimately end yesterday -- today's drilling has not
    # happened yet, and zeroing the counter at midnight would be punishing.
    cursor = anchor if anchor in active else anchor - timedelta(days=1)
    count = 0
    while cursor in active:
        count += 1
        cursor -= timedelta(days=1)
    return count


async def project_user(session: AsyncSession, user: User) -> UserOut:
    level, into_level, for_next = level_progress(user.total_exp)
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        total_exp=user.total_exp,
        level=level,
        exp_into_level=into_level,
        exp_for_next_level=for_next,
        streak_days=await streak_days(session, user.id),
        created_at=user.created_at,
    )

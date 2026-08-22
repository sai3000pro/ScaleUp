"""Dev login must survive the thing that breaks it most often: pytest.

`pytest` truncates every table, so the seeded dev user is gone after any test
run. The endpoint used to 404 in that state and the login page reported the
feature as unavailable, which made "run the suite, then log in" fail by design.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.dev_user import DEV_EMAIL, DEV_PASSWORD, DEV_USER_ID
from app.db.session import sync_session
from app.models import User

pytestmark = pytest.mark.asyncio


def _wipe_dev_user() -> None:
    with sync_session() as session:
        session.execute(delete(User).where(User.id == DEV_USER_ID))
        session.commit()


async def test_dev_login_works_with_no_seeded_user(client: AsyncClient) -> None:
    _wipe_dev_user()

    response = await client.post("/api/auth/dev-login", json={})

    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


async def test_dev_login_is_idempotent(client: AsyncClient) -> None:
    """A second call must reuse the row, not collide on the unique email."""
    _wipe_dev_user()

    first = await client.post("/api/auth/dev-login", json={})
    second = await client.post("/api/auth/dev-login", json={})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    with sync_session() as session:
        count = session.scalar(select(func.count()).select_from(User).where(User.email == DEV_EMAIL))
    assert count == 1, count


async def test_the_password_on_the_login_page_actually_works(client: AsyncClient) -> None:
    """The form shows dev@example.com / devpassword123, so it must sign in."""
    _wipe_dev_user()
    await client.post("/api/auth/dev-login", json={})

    response = await client.post("/api/auth/login", json={"email": DEV_EMAIL, "password": DEV_PASSWORD})

    assert response.status_code == 200, response.text

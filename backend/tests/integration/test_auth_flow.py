"""Register -> login -> /me, against the real database."""

from __future__ import annotations

from httpx import AsyncClient

CREDENTIALS = {"email": "Dev@Example.com", "password": "hunter22-long-enough", "display_name": "Dev"}


async def test_register_returns_a_usable_token(client: AsyncClient) -> None:
    response = await client.post("/api/auth/register", json=CREDENTIALS)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "dev@example.com"  # normalised to lowercase
    assert body["user"]["total_exp"] == 0
    assert body["user"]["level"] == 0
    assert body["user"]["streak_days"] == 0

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


async def test_duplicate_email_is_rejected_case_insensitively(client: AsyncClient) -> None:
    assert (await client.post("/api/auth/register", json=CREDENTIALS)).status_code == 201

    shouty = {**CREDENTIALS, "email": "DEV@EXAMPLE.COM"}
    response = await client.post("/api/auth/register", json=shouty)
    assert response.status_code == 409


async def test_login_accepts_correct_credentials(client: AsyncClient) -> None:
    await client.post("/api/auth/register", json=CREDENTIALS)

    response = await client.post(
        "/api/auth/login",
        json={"email": "dev@example.com", "password": CREDENTIALS["password"]},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_refresh_rotates_and_rejects_reuse(client: AsyncClient) -> None:
    await client.post("/api/auth/register", json=CREDENTIALS)
    first_refresh = client.cookies.get("learn_anything_refresh")
    assert first_refresh

    rotated = await client.post("/api/auth/refresh")
    assert rotated.status_code == 200, rotated.text
    second_refresh = rotated.cookies.get("learn_anything_refresh")
    assert second_refresh and second_refresh != first_refresh
    assert rotated.json()["access_token"]

    reused = await client.post(
        "/api/auth/refresh",
        headers={"Cookie": f"learn_anything_refresh={first_refresh}"},
    )
    assert reused.status_code == 401


async def test_logout_revokes_the_refresh_session(client: AsyncClient) -> None:
    await client.post("/api/auth/register", json=CREDENTIALS)

    logged_out = await client.post("/api/auth/logout")
    assert logged_out.status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_login_rejects_a_wrong_password(client: AsyncClient) -> None:
    await client.post("/api/auth/register", json=CREDENTIALS)

    response = await client.post(
        "/api/auth/login",
        json={"email": "dev@example.com", "password": "definitely-not-it"},
    )
    assert response.status_code == 401


async def test_login_does_not_reveal_whether_an_account_exists(client: AsyncClient) -> None:
    """Same status and body for an unknown address as for a wrong password."""
    await client.post("/api/auth/register", json=CREDENTIALS)

    unknown = await client.post("/api/auth/login", json={"email": "nobody@nowhere.example.com", "password": "whatever123"})
    wrong = await client.post("/api/auth/login", json={"email": "dev@example.com", "password": "whatever123"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


async def test_me_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_me_rejects_a_garbage_token(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_short_passwords_are_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/auth/register", json={**CREDENTIALS, "password": "short"})
    assert response.status_code == 422

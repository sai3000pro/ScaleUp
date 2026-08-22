"""Integration-test fixtures.

These hit the real Postgres from docker-compose. Unit tests under tests/unit/
deliberately need none of this and run with nothing else on the machine.

They never hit a real language model. That is pinned here rather than assumed,
because `.env` is a developer's own file: the moment someone sets
`LLM_PROVIDER=gemini` to try a feature, the suite starts spending their money,
answering differently every run, and failing on a rate limit that has nothing to
do with the code. The deterministic providers are the contract the whole suite is
written against.
"""

from __future__ import annotations

import os

# Before any import that reads settings. `app.config.get_settings` is cached, and
# `app.main` below builds it, so a later override would arrive after the fact.
os.environ["LLM_PROVIDER"] = "fake"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["VOICE_PROVIDER"] = "fake"
os.environ["RESEARCH_PROVIDER"] = "fake"

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.db.session import _async_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.repositories import neo4j_repo  # noqa: E402
from app.tasks.celery_app import celery_app  # noqa: E402
from app.vector.chroma_store import get_vector_store  # noqa: E402

# Run tasks inline instead of shipping them to Redis. Without this the suite
# needs a live worker to be meaningful, and the tasks it queues outlive the test
# that made them -- they then fire against rows the next test already truncated.
celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

_TABLES = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)


@pytest.fixture
async def clean_db() -> AsyncGenerator[None, None]:
    """Reset ALL THREE stores before the test.

    Truncating only Postgres leaves the derived stores accumulating across the
    whole session, which makes tests order-dependent and progressively slower --
    a Neo4j traversal that is instant against one course crawls against thirty.

    TRUNCATE ... CASCADE rather than dropping and recreating the schema: it is
    far faster, and it keeps the migration as the single definition of the
    schema rather than letting create_all quietly drift from it.
    """
    async with _async_session_factory()() as session:
        # TRUNCATE needs ACCESS EXCLUSIVE on every table, so any connection left
        # idle-in-transaction by a previous test blocks it *forever*. The timeout
        # turns that into an immediate, legible failure naming the real problem
        # rather than a suite that appears to hang.
        await session.execute(text("SET LOCAL lock_timeout = '10s'"))
        try:
            await session.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
        except OperationalError as exc:
            raise RuntimeError(
                "TRUNCATE timed out waiting for a lock. A previous test almost certainly "
                "left a session open (idle in transaction) -- look for a sync_session() or "
                "AsyncSession that is created but never closed."
            ) from exc
        await session.commit()

    # Derived stores. Failures are tolerated: a test that does not touch them
    # should not be blocked by one being unavailable.
    try:
        neo4j_repo.clear_all()
    except Exception:  # noqa: BLE001
        pass
    try:
        get_vector_store().clear_all()
    except Exception:  # noqa: BLE001
        pass

    yield


@pytest.fixture
async def client(clean_db: None) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


TEST_USER = {"email": "tester@example.com", "password": "hunter22-long-enough", "display_name": "Tester"}


@pytest.fixture
async def authed_client(client: AsyncClient) -> AsyncGenerator[AsyncClient, None]:
    """A client with a registered user's bearer token already attached.

    Most integration tests only register a user in order to get a token; doing
    it once here keeps that plumbing out of the test bodies.
    """
    response = await client.post("/api/auth/register", json=TEST_USER)
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    yield client

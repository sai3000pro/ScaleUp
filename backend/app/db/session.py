"""Engines and session factories.

Two engines, deliberately:

* async (asyncpg) for FastAPI request handling
* sync  (psycopg) for Celery tasks and Alembic

Celery's prefork/solo model and an asyncio event loop do not mix comfortably.
Tasks that reach for `asyncio.run` inside a worker are a recurring source of
"attached to a different loop" failures, so the worker gets a plain synchronous
session and the API keeps the async one.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache(maxsize=1)
def _async_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def _async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_async_engine(), expire_on_commit=False, class_=AsyncSession)


@lru_cache(maxsize=1)
def _sync_engine():
    settings = get_settings()
    return create_engine(settings.sync_database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def _sync_session_factory() -> sessionmaker[Session]:
    return sessionmaker(_sync_engine(), expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. One session per request, rolled back on error."""
    async with _async_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@contextmanager
def sync_session() -> Generator[Session, None, None]:
    """Session for Celery tasks. Commits on clean exit, rolls back on error."""
    session = _sync_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

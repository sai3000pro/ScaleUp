"""Readiness probing and the provider report.

`/live` answers "is the process up". Readiness actually touches every datastore,
because a probe that only reports on itself tells you nothing you could not learn
from the TCP connection.

Three of the four clients are synchronous and each waits up to two seconds on a
socket. Called inline they block the event loop, so probing a downed datastore
stalls every other request on the worker -- the probe becomes the outage it is
meant to report. All four checks run concurrently, with the synchronous clients
in a threadpool, so a full readiness check costs one timeout rather than four.

This lives in the service layer rather than in the router because the layering
rule is one-directional and has no infrastructure carve-out: routers translate
HTTP to a service call and never construct a query, not even `SELECT 1`.
`backend/tests/test_layering.py` enforces it.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.integrations import BROWSER_DEPENDENCIES, integration_statuses, missing_for_deployment
from app.llm.factory import get_llm_client

DATASTORE_PROBE_TIMEOUT_SECONDS = 2.0


def _check_redis() -> None:
    import redis

    client = redis.Redis.from_url(get_settings().celery_broker_url, socket_connect_timeout=2)
    client.ping()


def _check_neo4j() -> None:
    from neo4j import GraphDatabase

    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        connection_timeout=2,
    )
    try:
        driver.verify_connectivity()
    finally:
        driver.close()


def _check_chroma() -> None:
    from app.vector.chroma_store import get_vector_store

    get_vector_store().heartbeat()


async def _probe(name: str, check: Callable[[], None]) -> tuple[str, str]:
    """Run one blocking check off the loop. Reports, never raises."""
    try:
        await asyncio.wait_for(run_in_threadpool(check), timeout=DATASTORE_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- a readiness probe reports, never raises
        return name, f"error: {type(exc).__name__}"
    return name, "ok"


async def _probe_postgres(session: AsyncSession) -> tuple[str, str]:
    """Bound the async database check and report it like the threadpool probes."""
    try:
        # asyncpg's connection timeout can exceed the probe's useful lifetime
        # when Postgres is completely down. Bound the database check itself so
        # readiness reports a diagnosis instead of hanging until the caller's
        # HTTP timeout expires.
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=DATASTORE_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- a readiness probe reports, never raises
        return "postgres", f"error: {type(exc).__name__}"
    return "postgres", "ok"


# @spec OPS-HEALTH-002, OPS-HEALTH-003
async def readiness(session: AsyncSession) -> dict[str, object]:
    results = await asyncio.gather(
        _probe_postgres(session),
        _probe("redis", _check_redis),
        _probe("neo4j", _check_neo4j),
        _probe("chroma", _check_chroma),
    )
    checks = dict(results)
    return {"ok": all(value == "ok" for value in checks.values()), "checks": checks}


# @spec OPS-INTEG-002, OPS-INTEG-003, OPS-INTEG-004, OPS-INTEG-005, OPS-HEALTH-004
def _llm_lanes() -> dict[str, str]:
    """Which provider actually serves each workload lane.

    `selected.llm` names what was asked for; this names what each lane got. They
    differ whenever a lane has no credential and falls back to the deterministic
    provider, and that difference is the thing worth seeing before a demo -- a
    curriculum built on a real model and a coach running on canned sentences look
    identical from the outside.
    """
    from app.llm.registry import LANES

    try:
        client = get_llm_client()
    except RuntimeError:
        # Misconfigured hard enough that no client exists. The integration table
        # above already says so; this must not turn the whole report into a 500.
        return {}
    lanes = getattr(client, "lanes", None)
    return lanes() if lanes is not None else {lane: client.provider for lane in LANES}


#: Environment variables that name the commit being served, in the order they are
#: trusted. Render sets the first for every deploy; the others are what the common
#: alternatives set, so this does not need changing to move host.
BUILD_REVISION_VARS: tuple[str, ...] = (
    "RENDER_GIT_COMMIT",
    "VERCEL_GIT_COMMIT_SHA",
    "GIT_COMMIT",
    "SOURCE_VERSION",
)


# @spec OPS-HEALTH-005
def build_revision() -> str | None:
    """The commit this process is serving, where the host says so.

    Without this, "did my fix deploy?" is answered by watching behaviour change,
    which is exactly the question you cannot answer when the behaviour you are
    watching is the one that is broken. A commit sha is not a credential and not a
    dependency, so it belongs on the liveness response where anything can read it.

    `None` rather than "unknown" when nothing set it: a local run genuinely has no
    build, and inventing a placeholder would put a string in the field that a
    caller might reasonably compare against a real sha.
    """
    import os

    for variable in BUILD_REVISION_VARS:
        value = os.environ.get(variable, "").strip()
        if value:
            return value[:40]
    return None


def provider_report() -> dict[str, object]:
    """What is wired up, what is running on a fallback, and what is misconfigured.

    Rendered from `app.integrations`, which is the one table describing every
    external service. Reports the PRESENCE of credentials and never their
    values, so this is safe on a demo screen and safe in a screenshot.

    `misconfigured` is the state worth having: a provider that was asked for but
    whose key is missing would otherwise fail at the first call, in a Celery
    task, hours later.
    """
    settings = get_settings()
    statuses = integration_statuses(settings)
    return {
        # Reached by the page rather than by this process, and controlled by no
        # credential -- so reported beside the integrations rather than as one.
        # See `app.integrations.BrowserDependency`.
        "browser_dependencies": [
            {
                "key": dependency.key,
                "title": dependency.title,
                "purpose": dependency.purpose,
                "fallback": dependency.fallback,
                "hosts": list(dependency.hosts),
                "options": list(dependency.options),
                "provider_url": dependency.provider_url,
                "reached_when": dependency.reached_when,
            }
            for dependency in BROWSER_DEPENDENCIES
        ],
        "selected": {
            "llm": settings.llm_provider,
            "embedding": settings.embedding_provider,
            "research": settings.research_provider,
            "voice": settings.voice_provider,
            "email": settings.email_provider,
            "storage": settings.storage_backend,
        },
        "llm_lanes": _llm_lanes(),
        "deployed": settings.deployed,
        "all_ready": all(status.ready for status in statuses),
        "integrations": [
            {
                "key": status.key,
                "title": status.title,
                "mode": status.mode,
                "purpose": status.purpose,
                "fallback": status.fallback,
                "requires": list(status.requires),
                "missing": list(status.missing),
                "enable_hint": status.enable_hint,
                "provider_url": status.provider_url,
                "required_when_deployed": status.required_when_deployed,
            }
            for status in statuses
        ],
        "missing_for_deployment": list(missing_for_deployment(settings)),
    }

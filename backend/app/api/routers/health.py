"""Liveness, readiness, and the provider report.

`/live` answers "is the process up" and deliberately touches nothing else: a
liveness probe that fails when a datastore is down gets the container restarted
for someone else's outage.

The probing itself lives in `app.services.health_service`, which is where the
layering rule puts it.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.services import health_service

router = APIRouter(prefix="/api/health", tags=["health"])


# @spec OPS-HEALTH-001
@router.get("/live")
async def live() -> dict[str, bool]:
    return {"ok": True}


# @spec OPS-INTEG-002
@router.get("/providers")
async def providers() -> dict[str, object]:
    return health_service.provider_report()


# @spec OPS-HEALTH-002
@router.get("/ready")
async def ready(session: DbSession) -> dict[str, object]:
    return await health_service.readiness(session)

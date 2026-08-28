from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import (
    admin,
    auth,
    character,
    coach,
    courses,
    drill,
    explore,
    health,
    jobs,
    practice,
    quests,
    recordings,
    shares,
    webhooks,
)
from app.config import get_settings
from app.llm.base import BudgetExceededError, ProviderError


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="ScaleUp API",
        version="0.1.0",
        summary="Scores instrument practice against digital scores, coaches it, and decays it.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(BudgetExceededError)
    async def budget_exceeded_handler(_request: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    # @spec LLM-PROV-014
    @app.exception_handler(ProviderError)
    async def provider_error_handler(_request: Request, exc: ProviderError) -> JSONResponse:
        """An upstream model failure, answered as one.

        Almost nothing should reach here: a role with a fallback model re-attempts
        on it, and a credentialed provider sits on the deterministic floor, so the
        paths a learner touches degrade rather than raise. What is left is worth
        answering deliberately anyway, because an unhandled exception escapes
        *outside* CORSMiddleware -- the response carries no CORS headers, and the
        browser reports the generic "Failed to fetch" that says nothing about a
        provider. A 502 through the middleware is a diagnosable answer.
        """
        logging.getLogger(__name__).warning("provider failure reached the request boundary: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"detail": "The language-model provider is unavailable. Try again shortly."},
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(character.router)
    app.include_router(courses.router)
    app.include_router(explore.router)
    app.include_router(jobs.router)
    app.include_router(drill.router)
    app.include_router(practice.router)
    # The live coaching socket. Authenticates in its first frame, because a
    # browser cannot set headers on a WebSocket handshake.
    app.include_router(coach.router)
    app.include_router(quests.router)
    # Owner-scoped original takes; see the router module docstring.
    app.include_router(recordings.router)
    # n8n seam: signed, idempotent; see the router module docstring. These do
    # not depend on n8n running -- the demo works with n8n stopped.
    app.include_router(webhooks.router)
    # Owner-scoped, despite the prefix -- see the router's module docstring.
    app.include_router(admin.router)
    # `{token}` IS the credential for preview; copying still requires auth.
    app.include_router(shares.router)

    # @spec ACCESS-AUTH-007
    if settings.dev_auth_enabled:
        # Registered only when explicitly enabled, so with the flag off the
        # route does not exist rather than merely refusing.
        from app.api.routers import dev

        logging.getLogger(__name__).warning("dev auth is ENABLED -- POST /api/auth/dev-login is live")
        app.include_router(dev.router)

    return app


app = create_app()

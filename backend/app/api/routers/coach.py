"""The live coaching socket.

Thin, like every other router here: it accepts, authenticates, and hands the
socket to the service. No SQLAlchemy, no state machine.

Authentication is the one thing that cannot follow the usual pattern. Browsers
cannot set an `Authorization` header on a WebSocket handshake, and putting a
token in the query string writes a credential into every access log between the
learner and the server. So the token arrives in the first frame instead, and it
is the same access token `decode_access_token` already validates -- one auth
seam, not two.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket

from app.api.deps import DbSession
from app.core.security import decode_access_token
from app.models import User
from app.schemas.coach import CLOSE_UNAUTHENTICATED, PROTOCOL_VERSION
from app.services import coach_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["coach"])


@router.websocket("/practice/coach")
async def practice_coach(websocket: WebSocket, session: DbSession) -> None:
    await websocket.accept()
    try:
        hello = await websocket.receive_json()
    except Exception:  # noqa: BLE001 - a client that opens and vanishes is not an incident
        return

    if str(hello.get("protocol_version", PROTOCOL_VERSION)) != PROTOCOL_VERSION:
        await websocket.close(code=4426, reason="Unsupported coach protocol version.")
        return

    user_id = decode_access_token(str(hello.get("token", "")))
    user = None if user_id is None else await session.get(User, user_id)
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="Not authenticated.")
        return

    await coach_service.run_coach_session(session, websocket, user)

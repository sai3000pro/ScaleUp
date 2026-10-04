"""Bound request bodies for synchronous practice scoring."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.evaluation.scoring_limits import MAX_SCORING_PAYLOAD_BYTES

_ASGIMessage = dict[str, Any]
_ASGIReceive = Callable[[], Awaitable[_ASGIMessage]]
_ASGISend = Callable[[_ASGIMessage], Awaitable[None]]
_SCORING_PATH = re.compile(r"^/api/practice/sessions/[^/]+/attempts$")


class ScoringRequestLimitMiddleware:
    """Buffer only the bounded scoring request and reject excess bytes with 413."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: _ASGIReceive, send: _ASGISend) -> None:
        scope_path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or _SCORING_PATH.fullmatch(scope_path) is None
        ):
            await self.app(scope, receive, send)
            return

        content_length = next(
            (value for key, value in scope.get("headers", []) if key.lower() == b"content-length"),
            None,
        )
        try:
            declared_size = int(content_length) if content_length is not None else None
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > MAX_SCORING_PAYLOAD_BYTES:
            await _send_too_large(send)
            return

        body = bytearray()
        finished = False
        while not finished:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_SCORING_PAYLOAD_BYTES:
                await _send_too_large(send)
                return
            finished = not message.get("more_body", False)

        sent_body = False

        async def replay_receive() -> _ASGIMessage:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


async def _send_too_large(send: _ASGISend) -> None:
    body = json.dumps(
        {"detail": f"Scoring payload exceeds the {MAX_SCORING_PAYLOAD_BYTES // 1024} KiB demo limit."}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})

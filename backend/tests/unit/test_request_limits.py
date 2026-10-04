from __future__ import annotations

from typing import Any

from app.core.request_limits import ScoringRequestLimitMiddleware
from app.evaluation.scoring_limits import MAX_SCORING_PAYLOAD_BYTES


def _scope(*, content_length: bytes | None = None, path: str = "/api/practice/sessions/abc/attempts") -> dict[str, Any]:
    headers = [] if content_length is None else [(b"content-length", content_length)]
    return {"type": "http", "method": "POST", "path": path, "headers": headers}


async def test_exact_limit_body_is_replayed_to_the_application() -> None:
    body = b"x" * MAX_SCORING_PAYLOAD_BYTES
    messages = [
        {"type": "http.request", "body": body[:100], "more_body": True},
        {"type": "http.request", "body": body[100:], "more_body": False},
    ]
    received: list[bytes] = []
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def app(scope, request_receive, response_send) -> None:
        request = await request_receive()
        received.append(request["body"])
        await response_send({"type": "http.response.start", "status": 200, "headers": []})
        await response_send({"type": "http.response.body", "body": b"ok"})

    await ScoringRequestLimitMiddleware(app)(_scope(), receive, send)

    assert received == [body]
    assert sent[0]["status"] == 200


async def test_chunked_oversized_body_is_rejected_without_calling_application() -> None:
    messages = [
        {"type": "http.request", "body": b"x" * MAX_SCORING_PAYLOAD_BYTES, "more_body": True},
        {"type": "http.request", "body": b"x", "more_body": False},
    ]
    sent: list[dict[str, Any]] = []
    app_called = False

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def app(scope, request_receive, response_send) -> None:
        nonlocal app_called
        app_called = True

    await ScoringRequestLimitMiddleware(app)(_scope(), receive, send)

    assert app_called is False
    assert sent[0]["status"] == 413
    assert b"256 KiB" in sent[1]["body"]


async def test_declared_oversize_is_rejected_without_reading_body() -> None:
    sent: list[dict[str, Any]] = []
    app_called = False
    body_read = False

    async def receive() -> dict[str, Any]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def app(scope, request_receive, response_send) -> None:
        nonlocal app_called
        app_called = True

    await ScoringRequestLimitMiddleware(app)(
        _scope(content_length=str(MAX_SCORING_PAYLOAD_BYTES + 1).encode()), receive, send
    )

    assert app_called is False
    assert body_read is False
    assert sent[0]["status"] == 413


async def test_unrelated_endpoints_are_not_buffered_or_restricted() -> None:
    sent: list[dict[str, Any]] = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        received = True
        return {"type": "http.request", "body": b"large", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def app(scope, request_receive, response_send) -> None:
        request = await request_receive()
        assert request["body"] == b"large"
        await response_send({"type": "http.response.start", "status": 200, "headers": []})

    await ScoringRequestLimitMiddleware(app)(_scope(path="/api/courses"), receive, send)

    assert received is True
    assert sent[0]["status"] == 200

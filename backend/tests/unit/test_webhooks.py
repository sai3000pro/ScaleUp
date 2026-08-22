"""The webhook seam is offline-testable: signing, payloads, and routes.

No database, no n8n, no providers -- the signature math and the OpenAPI route
inventory are pure contract checks that catch drift before an integration test
has to discover it.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from app.main import app
from app.schemas.webhook import (
    DailyQuestsRefreshPayload,
    FeedbackRequestedPayload,
    SessionCompletedPayload,
    WebhookResult,
)
from app.services import webhook_service

OPENAPI = app.openapi()

_EVENT_ID = "11111111-1111-1111-1111-111111111111"
_ATTEMPT_ID = "22222222-2222-2222-2222-222222222222"
_USER_ID = "33333333-3333-3333-3333-333333333333"
_DT = "2026-08-20T12:00:00Z"


def test_signature_is_hmac_sha256_over_the_exact_bytes() -> None:
    body = b'{"event_id": "11111111-1111-1111-1111-111111111111"}'

    signature = webhook_service.sign_payload("secret", body)
    assert signature.startswith("sha256=")
    assert len(signature) == len("sha256=") + 64

    assert webhook_service.verify_signature("secret", body, signature)
    # Wrong secret, tampered body, trailing byte, or a missing header all fail.
    assert not webhook_service.verify_signature("other-secret", body, signature)
    assert not webhook_service.verify_signature("secret", b"tampered", signature)
    assert not webhook_service.verify_signature("secret", body + b" ", signature)
    assert not webhook_service.verify_signature("secret", body, None)
    assert not webhook_service.verify_signature("secret", body, "0" * 70)


def test_signature_is_deterministic_and_content_addressed() -> None:
    body = b"same bytes"
    assert webhook_service.sign_payload("k", body) == webhook_service.sign_payload("k", body)
    assert webhook_service.sign_payload("k", body) != webhook_service.sign_payload("k", b"different bytes")


def test_payload_sha256_is_hex_of_fixed_length() -> None:
    assert len(webhook_service.payload_sha256(b"abc")) == 64
    assert webhook_service.payload_sha256(b"abc") == webhook_service.payload_sha256(b"abc")


def test_event_payloads_validate_and_require_their_key_field() -> None:
    base = {"event_id": _EVENT_ID, "occurred_at": _DT}
    assert TypeAdapter(SessionCompletedPayload).validate_python({**base, "attempt_id": _ATTEMPT_ID})
    assert TypeAdapter(FeedbackRequestedPayload).validate_python({**base, "attempt_id": _ATTEMPT_ID, "voice": True})
    assert TypeAdapter(FeedbackRequestedPayload).validate_python({**base, "attempt_id": _ATTEMPT_ID})
    assert TypeAdapter(DailyQuestsRefreshPayload).validate_python({**base, "user_id": _USER_ID})

    with pytest.raises(ValueError, match="event_id"):
        TypeAdapter(SessionCompletedPayload).validate_python({"occurred_at": _DT, "attempt_id": _ATTEMPT_ID})
    with pytest.raises(ValueError, match="attempt_id"):
        TypeAdapter(SessionCompletedPayload).validate_python(base)
    with pytest.raises(ValueError, match="user_id"):
        TypeAdapter(DailyQuestsRefreshPayload).validate_python(base)


def test_correlation_id_is_length_bounded() -> None:
    with pytest.raises(ValueError):
        TypeAdapter(SessionCompletedPayload).validate_python(
            {"event_id": _EVENT_ID, "occurred_at": _DT, "attempt_id": _ATTEMPT_ID, "correlation_id": "x" * 81}
        )


@pytest.mark.parametrize(
    "event_type",
    ["session.completed", "feedback.requested", "daily-quests.refresh"],
)
def test_webhook_routes_are_registered_with_the_result_contract(event_type: str) -> None:
    operation = OPENAPI["paths"][f"/api/webhooks/v1/{event_type}"]["post"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/WebhookResult"


def test_unknown_event_types_are_not_registered() -> None:
    assert "/api/webhooks/v1/unknown.event" not in OPENAPI["paths"]


def test_webhook_result_status_is_binary() -> None:
    for status_value in ("processed", "duplicate"):
        assert TypeAdapter(WebhookResult).validate_python(
            {
                "event_id": _EVENT_ID,
                "event_type": "session.completed",
                "status": status_value,
                "correlation_id": None,
                "result": {},
            }
        )
    with pytest.raises(ValueError, match="status"):
        TypeAdapter(WebhookResult).validate_python(
            {
                "event_id": _EVENT_ID,
                "event_type": "session.completed",
                "status": "retried",
                "correlation_id": None,
                "result": {},
            }
        )

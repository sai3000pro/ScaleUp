"""n8n webhook lifecycle against Postgres: sign, process, dedupe, replay.

The webhook surface must be safe to trigger repeatedly: a replayed event id is
a ledger lookup, never a second side effect; a tampered or unsigned request is
rejected; and a missing target is a clean 404 that records nothing.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db.session import sync_session
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.reference_scores import PIANO_STEPWISE_SCORE_XML
from app.models import Course, Exercise, ScoreAsset, SkillNode, User, WebhookEvent
from app.services import webhook_service

NOTES = [
    {"pitch_midi": 60, "onset_seconds": 0.0},
    {"pitch_midi": 62, "onset_seconds": 0.5},
    {"pitch_midi": 64, "onset_seconds": 1.0},
    {"pitch_midi": 65, "onset_seconds": 1.5},
]

_EVENT_AT = "2026-08-20T12:00:00Z"


@pytest.fixture
def webhook_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "test-webhook-secret"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    yield secret
    get_settings.cache_clear()


@pytest.fixture
def no_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _signed_headers(secret: str, payload: dict, correlation_id: str | None = None) -> tuple[dict[str, str], bytes]:
    """Sign the exact bytes we are about to send, so the server verifies them."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": webhook_service.sign_payload(secret, body),
    }
    if correlation_id is not None:
        headers["X-Correlation-ID"] = correlation_id
    return headers, body


async def _seed_attempt(authed_client: AsyncClient) -> tuple[uuid.UUID, uuid.UUID]:
    """Create course/node/asset/exercise and submit one perfect attempt.

    Returns (user_id, attempt_id).
    """
    with sync_session() as session:
        user = session.scalar(select(User).where(User.email == "tester@example.com"))
        user_id = user.id
        course = Course(owner_id=user.id, title="Piano Practice")
        session.add(course)
        session.flush()
        node = SkillNode(
            course_id=course.id,
            slug="stepwise-melody",
            title="Stepwise Melody",
            summary="Play adjacent notes evenly.",
            difficulty=2,
        )
        session.add(node)
        session.flush()
        score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
        asset = ScoreAsset(
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=PIANO_STEPWISE_SCORE_XML,
            content_sha256="a" * 64,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
        )
        session.add(asset)
        session.flush()
        exercise = Exercise(
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="stepwise-c-major",
            title="Stepwise C Major",
            instructions="Play the notes evenly.",
            difficulty=2,
        )
        session.add(exercise)
        session.flush()
        exercise_id = exercise.id

    practice = await authed_client.post("/api/practice/sessions", json={"exercise_id": str(exercise_id)})
    assert practice.status_code == 201, practice.text
    attempt = await authed_client.post(
        f"/api/practice/sessions/{practice.json()['id']}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": NOTES},
    )
    assert attempt.status_code == 201, attempt.text
    return user_id, uuid.UUID(attempt.json()["id"])


async def test_session_completed_processes_and_a_replay_answers_from_the_ledger(
    authed_client: AsyncClient, webhook_secret: str
) -> None:
    _user_id, attempt_id = await _seed_attempt(authed_client)
    event_id = str(uuid.uuid4())
    payload = {"event_id": event_id, "occurred_at": _EVENT_AT, "attempt_id": str(attempt_id)}

    headers, body = _signed_headers(webhook_secret, payload, correlation_id="trace-1")
    first = await authed_client.post("/api/webhooks/v1/session.completed", headers=headers, content=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "processed"
    assert first.json()["correlation_id"] == "trace-1"
    assert first.json()["result"]["attempt_id"] == str(attempt_id)
    assert first.json()["result"]["status"] == "completed"
    assert first.json()["result"]["has_feedback"] is True

    # Replay the SAME event id -- even with a different body -- answers from
    # the ledger instead of re-executing.
    replay_payload = dict(payload)
    replay_payload["occurred_at"] = "2026-08-20T13:00:00Z"
    replay_headers, replay_body = _signed_headers(webhook_secret, replay_payload)
    second = await authed_client.post("/api/webhooks/v1/session.completed", headers=replay_headers, content=replay_body)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "duplicate"
    assert second.json()["result"] == first.json()["result"]

    with sync_session() as session:
        rows = list(session.scalars(select(WebhookEvent).where(WebhookEvent.event_id == event_id)))
        assert len(rows) == 1
        assert rows[0].status == "processed"
        assert rows[0].correlation_id == "trace-1"
        assert len(rows[0].payload_sha256) == 64


async def test_feedback_requested_returns_feedback_and_optional_voice(
    authed_client: AsyncClient, webhook_secret: str
) -> None:
    _user_id, attempt_id = await _seed_attempt(authed_client)
    payload = {
        "event_id": str(uuid.uuid4()),
        "occurred_at": _EVENT_AT,
        "attempt_id": str(attempt_id),
        "voice": True,
    }
    headers, body = _signed_headers(webhook_secret, payload)
    response = await authed_client.post("/api/webhooks/v1/feedback.requested", headers=headers, content=body)
    assert response.status_code == 200, response.text

    result = response.json()["result"]
    assert result["attempt_id"] == str(attempt_id)
    assert result["feedback_persona"] == "Professor Cadenza"
    assert result["feedback_summary"]
    assert result["voice"]["provider"] == "fake"
    assert result["voice"]["audio_base64"] is not None


async def test_daily_quests_refresh_returns_the_computed_board(
    authed_client: AsyncClient, webhook_secret: str
) -> None:
    user_id, attempt_id = await _seed_attempt(authed_client)
    payload = {"event_id": str(uuid.uuid4()), "occurred_at": _EVENT_AT, "user_id": str(user_id)}
    headers, body = _signed_headers(webhook_secret, payload)
    response = await authed_client.post("/api/webhooks/v1/daily-quests.refresh", headers=headers, content=body)
    assert response.status_code == 200, response.text

    result = response.json()["result"]
    assert result["user_id"] == str(user_id)
    assert "date" in result
    assert result["quest_count"] >= 0
    assert isinstance(result["quests"], list)

    # Safe to rerun with a fresh event id: the board is a query, so a second
    # pass does not double-write anything.
    second_id = str(uuid.uuid4())
    headers2, body2 = _signed_headers(webhook_secret, {**payload, "event_id": second_id})
    second = await authed_client.post("/api/webhooks/v1/daily-quests.refresh", headers=headers2, content=body2)
    assert second.status_code == 200, second.text
    assert second.json()["result"]["quest_count"] == result["quest_count"]


async def test_invalid_signature_and_missing_header_are_rejected(
    authed_client: AsyncClient, webhook_secret: str
) -> None:
    payload = {"event_id": str(uuid.uuid4()), "occurred_at": _EVENT_AT, "attempt_id": str(uuid.uuid4())}

    wrong_headers, body = _signed_headers("wrong-secret", payload)
    wrong = await authed_client.post("/api/webhooks/v1/session.completed", headers=wrong_headers, content=body)
    assert wrong.status_code == 401

    unsigned = await authed_client.post(
        "/api/webhooks/v1/session.completed",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert unsigned.status_code == 401


async def test_missing_attempt_is_a_404_and_records_nothing(
    authed_client: AsyncClient, webhook_secret: str
) -> None:
    event_id = str(uuid.uuid4())
    payload = {"event_id": event_id, "occurred_at": _EVENT_AT, "attempt_id": str(uuid.uuid4())}
    headers, body = _signed_headers(webhook_secret, payload)
    response = await authed_client.post("/api/webhooks/v1/session.completed", headers=headers, content=body)
    assert response.status_code == 404

    with sync_session() as session:
        assert session.get(WebhookEvent, uuid.UUID(event_id)) is None


async def test_unknown_event_type_and_malformed_payload_are_rejected(
    authed_client: AsyncClient, webhook_secret: str
) -> None:
    payload = {"event_id": str(uuid.uuid4()), "occurred_at": _EVENT_AT}
    headers, body = _signed_headers(webhook_secret, payload)

    malformed = await authed_client.post("/api/webhooks/v1/session.completed", headers=headers, content=body)
    assert malformed.status_code == 422

    unknown = await authed_client.post("/api/webhooks/v1/unknown.event", headers=headers, content=body)
    assert unknown.status_code == 404


async def test_webhooks_refuse_to_run_unauthenticated_without_config(
    authed_client: AsyncClient, no_webhook_secret: None
) -> None:
    payload = {"event_id": str(uuid.uuid4()), "occurred_at": _EVENT_AT, "user_id": str(uuid.uuid4())}
    response = await authed_client.post(
        "/api/webhooks/v1/daily-quests.refresh",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 503


async def test_dev_webhook_mode_accepts_unsigned_requests(
    authed_client: AsyncClient, no_webhook_secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEV_WEBHOOKS_ENABLED", "true")
    get_settings.cache_clear()
    try:
        _user_id, attempt_id = await _seed_attempt(authed_client)
        payload = {"event_id": str(uuid.uuid4()), "occurred_at": _EVENT_AT, "attempt_id": str(attempt_id)}
        response = await authed_client.post(
            "/api/webhooks/v1/session.completed",
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "processed"
    finally:
        get_settings.cache_clear()

"""Preserved-take lifecycle: upload, dedupe, ownership, deletion, attempt-link.

The raw audio a take was scored from is evidence; these tests prove the
content-addressed store dedupes per user, serves bytes back only to the owner,
links a take to the attempt that cited it, and refuses a take from another
course as an attempt's evidence.
"""

from __future__ import annotations

import base64
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.evaluation.reference_scores import TRUMPET_C_ARPEGGIO_XML
from app.models import Course, Recording, User
from tests.integration.test_instrument_flows import TRUMPET_NOTES, _seed_instrument_exercise

# A plausible short WebM/opus clip: the container magic plus a payload.
DEMO_TAKE = b"\x1aE\xdf\xa3\x93B\x82\x88webmDEMO-TAKE-BYTES"


def _payload(course_id: uuid.UUID, content: bytes, *, format: str = "webm") -> dict:
    return {
        "course_id": str(course_id),
        "format": format,
        "duration_seconds": 3.2,
        "content_base64": base64.b64encode(content).decode(),
    }


async def _seed_course() -> uuid.UUID:
    with sync_session() as session:
        user = session.scalar(select(User).where(User.email == "tester@example.com"))
        course = Course(owner_id=user.id, title="Recording Course")
        session.add(course)
        session.flush()
        course_id = course.id
    return course_id


async def test_upload_dedupes_and_serves_content(authed_client: AsyncClient) -> None:
    course_id = await _seed_course()

    created = await authed_client.post("/api/recordings", json=_payload(course_id, DEMO_TAKE))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["deduplicated"] is False
    assert body["format"] == "webm"
    assert body["byte_size"] == len(DEMO_TAKE)
    assert body["duration_seconds"] == 3.2
    assert body["attempt_id"] is None
    recording_id = body["id"]

    fetched = await authed_client.get(f"/api/recordings/{recording_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == recording_id

    content = await authed_client.get(f"/api/recordings/{recording_id}/content")
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("audio/webm")
    assert content.content == DEMO_TAKE

    # Same bytes, same user -> content-addressed dedupe: no second copy.
    duplicate = await authed_client.post("/api/recordings", json=_payload(course_id, DEMO_TAKE))
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == recording_id
    assert duplicate.json()["deduplicated"] is True

    with sync_session() as session:
        assert len(session.scalars(select(Recording)).all()) == 1


async def test_invalid_and_empty_content_are_rejected(authed_client: AsyncClient) -> None:
    course_id = await _seed_course()

    bad = dict(_payload(course_id, b"x"), content_base64="not base64!!!")
    rejected = await authed_client.post("/api/recordings", json=bad)
    assert rejected.status_code == 400
    assert "not valid base64" in rejected.json()["detail"]

    # Empty base64 never reaches the service gate: the wire schema's
    # min_length=1 rejects it first.
    empty = dict(_payload(course_id, b""))
    rejected_empty = await authed_client.post("/api/recordings", json=empty)
    assert rejected_empty.status_code == 422


async def test_ownership_is_enforced_and_delete_removes_the_take(authed_client: AsyncClient) -> None:
    course_id = await _seed_course()
    created = await authed_client.post("/api/recordings", json=_payload(course_id, DEMO_TAKE))
    recording_id = created.json()["id"]

    stranger = await authed_client.post(
        "/api/auth/register",
        json={"email": "stranger@example.com", "password": "hunter22-long-enough", "display_name": "Stranger"},
    )
    assert stranger.status_code == 201, stranger.text
    authed_client.headers["Authorization"] = f"Bearer {stranger.json()['access_token']}"

    hidden = await authed_client.get(f"/api/recordings/{recording_id}")
    assert hidden.status_code == 404
    hidden_content = await authed_client.get(f"/api/recordings/{recording_id}/content")
    assert hidden_content.status_code == 404

    # Back to the owner for the delete.
    owner_login = await authed_client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "hunter22-long-enough"},
    )
    authed_client.headers["Authorization"] = f"Bearer {owner_login.json()['access_token']}"
    deleted = await authed_client.delete(f"/api/recordings/{recording_id}")
    assert deleted.status_code == 204
    gone = await authed_client.get(f"/api/recordings/{recording_id}")
    assert gone.status_code == 404


async def test_attempt_submission_links_the_recording_and_rejects_foreign_courses(
    authed_client: AsyncClient,
) -> None:
    course_id, session_id = await _seed_instrument_exercise(
        authed_client, "trumpet", TRUMPET_C_ARPEGGIO_XML, "major-arpeggios"
    )
    recording = await authed_client.post("/api/recordings", json=_payload(course_id, DEMO_TAKE))
    assert recording.status_code == 201, recording.text
    recording_id = recording.json()["id"]

    attempt = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": TRUMPET_NOTES, "recording_id": recording_id},
    )
    assert attempt.status_code == 201, attempt.text
    attempt_id = attempt.json()["id"]

    linked = await authed_client.get(f"/api/recordings/{recording_id}")
    assert linked.status_code == 200
    assert linked.json()["attempt_id"] == attempt_id

    # A take preserved for a different course cannot vouch for this one. The
    # original session was completed by the first submission, so open a fresh
    # session for the rejection to reach the recording check.
    exercise_id = attempt.json()["exercise_id"]
    fresh = await authed_client.post("/api/practice/sessions", json={"exercise_id": exercise_id})
    assert fresh.status_code == 201, fresh.text
    fresh_session_id = fresh.json()["id"]

    other_course_id = await _seed_course()
    foreign = await authed_client.post("/api/recordings", json=_payload(other_course_id, b"OTHER-COURSE-TAKE"))
    foreign_id = foreign.json()["id"]
    rejected = await authed_client.post(
        f"/api/practice/sessions/{fresh_session_id}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": TRUMPET_NOTES, "recording_id": foreign_id},
    )
    assert rejected.status_code == 400
    assert "different course" in rejected.json()["detail"]

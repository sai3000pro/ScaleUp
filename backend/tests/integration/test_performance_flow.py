"""The score evaluator crosses the persistence boundary exactly once."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.reference_scores import PIANO_STEPWISE_SCORE_XML
from app.models import Course, Exercise, ScoreAsset, SkillNode, User


async def test_piano_performance_submission_is_idempotent(
    authed_client: AsyncClient,
) -> None:
    with sync_session() as session:
        user = session.scalar(select(User).where(User.email == "tester@example.com"))
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

    listed = await authed_client.get(f"/api/courses/{course.id}/practice/exercises")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == str(exercise_id)

    practice = await authed_client.post("/api/practice/sessions", json={"exercise_id": str(exercise_id)})
    assert practice.status_code == 201, practice.text
    session_id = practice.json()["id"]
    seconds_per_beat = 60.0 / score.tempo_bpm
    notes = [
        {"pitch_midi": 60, "onset_seconds": 0.0},
        {"pitch_midi": 62, "onset_seconds": round(1 * seconds_per_beat, 3)},
        {"pitch_midi": 64, "onset_seconds": round(2 * seconds_per_beat, 3)},
        {"pitch_midi": 65, "onset_seconds": round(3 * seconds_per_beat, 3)},
    ]
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    first = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers=headers,
        json={"observed_notes": notes},
    )
    second = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers=headers,
        json={"observed_notes": notes},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["metrics"]["overall_score"] == 1.0
    assert first.json()["metrics"]["low_confidence"] is False
    assert second.json()["exp_awarded"] == first.json()["exp_awarded"]

    attempt_id = first.json()["id"]
    speech_first = await authed_client.post(f"/api/practice/attempts/{attempt_id}/speech")
    speech_second = await authed_client.post(f"/api/practice/attempts/{attempt_id}/speech")
    assert speech_first.status_code == 200, speech_first.text
    assert speech_second.status_code == 200, speech_second.text
    assert speech_first.json()["spoken_text"]
    assert speech_first.json()["audio_base64"] is not None
    assert speech_first.json()["cached"] is False
    assert speech_second.json()["cached"] is True
    assert speech_second.json()["audio_base64"] == speech_first.json()["audio_base64"]

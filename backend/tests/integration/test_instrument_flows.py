"""Violin, trumpet, and drums practice flows route to their own evaluators.

Each instrument's score asset declares its instrument in metadata; the service
must route observations to the right evaluator, persist the right metric
fields, and never reinterpret a field another instrument owns (drums store
pitch_accuracy NULL, never a fake pitch score).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.reference_scores import (
    DRUMS_ROCK_GROOVE_XML,
    TRUMPET_C_ARPEGGIO_XML,
    VIOLIN_OPEN_STRINGS_XML,
)
from app.models import Course, Exercise, PerformanceMetricBundle, ScoreAsset, SkillNode, User


async def _seed_instrument_exercise(
    authed_client: AsyncClient,
    instrument: str,
    score_xml: str,
    node_slug: str,
    evaluator_version: str | None = None,
) -> tuple[uuid.UUID, str]:
    with sync_session() as session:
        user = session.scalar(select(User).where(User.email == "tester@example.com"))
        course = Course(owner_id=user.id, title=f"{instrument.title()} Practice")
        session.add(course)
        session.flush()
        node = SkillNode(
            course_id=course.id,
            slug=node_slug,
            title=f"{instrument.title()} Exercise Node",
            summary="Practice the exercise.",
            difficulty=2,
        )
        session.add(node)
        session.flush()
        score = parse_musicxml(score_xml)
        asset = ScoreAsset(
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=score_xml,
            content_sha256=f"{instrument}{'a' * (64 - len(instrument))}",
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": instrument},
        )
        session.add(asset)
        session.flush()
        exercise = Exercise(
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug=f"{instrument}-exercise",
            title=score.title,
            instructions="Play the exercise.",
            evaluator_version=evaluator_version
            or (f"{instrument}-dtw-v1" if instrument != "drums" else "drums-rhythm-v1"),
            difficulty=2,
        )
        session.add(exercise)
        session.flush()
        course_id = course.id
        exercise_id = exercise.id

    practice = await authed_client.post("/api/practice/sessions", json={"exercise_id": str(exercise_id)})
    assert practice.status_code == 201, practice.text
    return course_id, practice.json()["id"]


VIOLIN_NOTES = [
    {"pitch_midi": 55, "onset_seconds": 0.0, "cents_deviation": 6.0},
    {"pitch_midi": 62, "onset_seconds": 1.0, "cents_deviation": -4.0},
    {"pitch_midi": 69, "onset_seconds": 2.0, "cents_deviation": 2.0},
    {"pitch_midi": 76, "onset_seconds": 3.0, "cents_deviation": 9.0},
]

TRUMPET_NOTES = [
    {"pitch_midi": 60, "onset_seconds": 0.0},
    {"pitch_midi": 64, "onset_seconds": 1.0},
    {"pitch_midi": 67, "onset_seconds": 2.0},
    {"pitch_midi": 72, "onset_seconds": 3.0},
]

_DRUMS_EIGHTH = (60.0 / 70.0) * 0.5
DRUMS_HITS = [
    {"onset_seconds": 0 * _DRUMS_EIGHTH, "drum": "kick"},
    {"onset_seconds": 1 * _DRUMS_EIGHTH, "drum": "hihat"},
    {"onset_seconds": 2 * _DRUMS_EIGHTH, "drum": "snare"},
    {"onset_seconds": 3 * _DRUMS_EIGHTH, "drum": "hihat"},
    {"onset_seconds": 4 * _DRUMS_EIGHTH, "drum": "kick"},
    {"onset_seconds": 5 * _DRUMS_EIGHTH, "drum": "hihat"},
    {"onset_seconds": 6 * _DRUMS_EIGHTH, "drum": "snare"},
    {"onset_seconds": 7 * _DRUMS_EIGHTH, "drum": "hihat"},
]


async def test_violin_attempt_persists_intonation_metrics(authed_client: AsyncClient) -> None:
    _course_id, session_id = await _seed_instrument_exercise(
        authed_client, "violin", VIOLIN_OPEN_STRINGS_XML, "open-string-bow"
    )
    attempt = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": VIOLIN_NOTES},
    )
    assert attempt.status_code == 201, attempt.text

    metrics = attempt.json()["metrics"]
    assert metrics["evaluator_version"] == "violin-dtw-v1"
    assert metrics["pitch_accuracy"] is not None
    assert metrics["intonation_accuracy"] is not None
    # |6|, |4|, |2|, |9| cents -> qualities 0.8, 0.867, 0.933, 0.7 -> mean 0.825
    assert metrics["intonation_accuracy"] == pytest.approx(0.825, abs=0.01)
    assert metrics["intonation_deviation_cents"] is not None
    assert metrics["intonation_deviation_cents"] == pytest.approx(5.25, abs=0.01)
    assert metrics["low_confidence"] is False
    strengths = attempt.json()["feedback"]["strengths"]
    assert any("intonation" in strength.lower() for strength in strengths)


async def test_trumpet_attempt_uses_the_shared_monophonic_core(authed_client: AsyncClient) -> None:
    _course_id, session_id = await _seed_instrument_exercise(
        authed_client, "trumpet", TRUMPET_C_ARPEGGIO_XML, "major-arpeggios"
    )
    attempt = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": TRUMPET_NOTES},
    )
    assert attempt.status_code == 201, attempt.text

    metrics = attempt.json()["metrics"]
    assert metrics["evaluator_version"] == "trumpet-dtw-v1"
    assert metrics["overall_score"] == 1.0
    assert metrics["pitch_accuracy"] == 1.0
    assert metrics["intonation_accuracy"] is None


async def test_drums_attempt_stores_pitch_as_inapplicable(authed_client: AsyncClient) -> None:
    _course_id, session_id = await _seed_instrument_exercise(
        authed_client, "drums", DRUMS_ROCK_GROOVE_XML, "eighth-note-groove"
    )
    attempt = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": DRUMS_HITS},
    )
    assert attempt.status_code == 201, attempt.text

    metrics = attempt.json()["metrics"]
    assert metrics["evaluator_version"] == "drums-rhythm-v1"
    assert metrics["pitch_accuracy"] is None
    assert metrics["rhythm_accuracy"] == pytest.approx(1.0, abs=0.01)
    assert metrics["overall_score"] == pytest.approx(1.0, abs=0.01)
    assert metrics["technique_accuracy"] is None
    assert metrics["low_confidence"] is False

    with sync_session() as session:
        row = session.scalar(select(PerformanceMetricBundle))
        assert row is not None
        assert row.pitch_accuracy is None
        assert row.evaluator_version == "drums-rhythm-v1"


async def test_guitar_chord_exercise_routes_to_the_chord_evaluator(
    authed_client: AsyncClient,
) -> None:
    from app.evaluation.guitar import open_string_midi
    from app.evaluation.reference_scores import GUITAR_GCD_STRUM_XML

    _course_id, session_id = await _seed_instrument_exercise(
        authed_client, "guitar", GUITAR_GCD_STRUM_XML, "open-chords", evaluator_version="guitar-chords-v1"
    )
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    beat = 60.0 / score.tempo_bpm
    strum = {
        0: [(6, 3), (5, 2), (4, 0), (3, 0), (2, 0), (1, 3)],
        1: [(5, 3), (4, 2), (3, 0), (2, 1), (1, 0)],
        2: [(4, 0), (3, 2), (2, 3), (1, 2)],
        3: [(6, 3), (5, 2), (4, 0), (3, 0), (2, 0), (1, 3)],
    }
    notes = []
    for chord_beat, positions in strum.items():
        for index, (string, fret) in enumerate(positions):
            notes.append(
                {
                    "pitch_midi": open_string_midi(string) + fret,
                    "onset_seconds": chord_beat * beat + index * 0.02,
                    "string": string,
                    "fret": fret,
                }
            )
    attempt = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": notes},
    )
    assert attempt.status_code == 201, attempt.text

    metrics = attempt.json()["metrics"]
    assert metrics["evaluator_version"] == "guitar-chords-v1"
    assert metrics["overall_score"] == 1.0
    assert metrics["technique_accuracy"] == 1.0
    assert metrics["position_error_count"] == 0


async def test_pitched_instrument_rejects_notes_without_pitch(authed_client: AsyncClient) -> None:
    _course_id, session_id = await _seed_instrument_exercise(
        authed_client, "trumpet", TRUMPET_C_ARPEGGIO_XML, "major-arpeggios"
    )
    attempt = await authed_client.post(
        f"/api/practice/sessions/{session_id}/attempts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"observed_notes": [{"onset_seconds": 0.0, "drum": "kick"}]},
    )
    assert attempt.status_code == 400, attempt.text
    assert "require a pitch" in attempt.json()["detail"]

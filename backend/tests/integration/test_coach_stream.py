"""The streaming coach, end to end, against the fake providers.

These tests are synchronous and use Starlette's `TestClient`, unlike the rest of
the integration suite: httpx's `ASGITransport` cannot open a WebSocket, and a
protocol test that cannot speak the protocol is not worth writing.

The test that matters most is `test_the_socket_and_the_clip_path_agree`. It runs
a take over the socket, submits the identical notes over HTTP, and asserts the
two metric bundles match field for field -- which is what proves the streaming
layer never quietly became a second grading system.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import select, text
from starlette.testclient import TestClient

from app.db.session import _async_engine, _async_session_factory, sync_session
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.online import expected_events
from app.evaluation.reference_scores import PIANO_STEPWISE_SCORE_XML
from app.main import app
from app.models import Base, CoachSession, CoachUtterance, Course, Exercise, ScoreAsset, SkillNode, User
from app.repositories.llm_calls import LlmCall
from app.schemas.coach import PROTOCOL_VERSION

_TABLES = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)

USER = {"email": "coachee@example.com", "password": "hunter22-long-enough", "display_name": "Coachee"}


@pytest.fixture()
def coach_client():
    """A registered client on a clean database, able to open WebSockets.

    The engine is disposed on the way out. `TestClient` runs each test in its
    own event loop, and asyncpg connections pooled on a closed loop raise
    "Event loop is closed" during the *next* test's teardown -- a failure that
    points at the wrong test entirely.
    """
    _reset_database()
    _dispose_async_engine()

    with TestClient(app) as client:
        response = client.post("/api/auth/register", json=USER)
        assert response.status_code == 201, response.text
        token = response.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        client.token = token  # type: ignore[attr-defined]
        yield client

    _dispose_async_engine()


def _reset_database() -> None:
    with sync_session() as session:
        session.execute(text("SET LOCAL lock_timeout = '10s'"))
        session.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
        session.commit()


def _dispose_async_engine() -> None:
    engine = _async_engine()
    with contextlib.suppress(Exception):
        engine.sync_engine.dispose()
    _async_engine.cache_clear()
    _async_session_factory.cache_clear()


@pytest.fixture()
def practice_session(coach_client):
    """A course, node, score asset, exercise, and an open practice session."""
    with sync_session() as session:
        user = session.scalar(select(User).where(User.email == USER["email"]))
        course = Course(owner_id=user.id, title="Coached Piano")
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
            content_sha256="c" * 64,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": "piano"},
        )
        session.add(asset)
        session.flush()
        exercise = Exercise(
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="stepwise",
            title="Stepwise C Major",
            instructions="Play four adjacent notes.",
            evaluator_version="piano-dtw-v1",
            difficulty=2,
        )
        session.add(exercise)
        session.commit()
        exercise_id = str(exercise.id)

    created = coach_client.post("/api/practice/sessions", json={"exercise_id": exercise_id})
    assert created.status_code == 201, created.text
    return {"exercise_id": exercise_id, "session_id": created.json()["id"]}


def _expected_event_count() -> int:
    """How many events a take expects, derived rather than written down.

    A live take loops the drill, so this is the score's playable notes times the
    loop -- not the note count of the score. Asserting the literal 4 was correct
    until the coach started looping and then quietly wrong, which is the failure
    a hard-coded number is for.
    """
    from app.services.coach_service import TAKE_REPEATS

    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    return len(expected_events(score, "piano", repeats=TAKE_REPEATS))


def _perfect_notes() -> list[dict]:
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    seconds_per_beat = 60.0 / score.tempo_bpm
    return [
        {
            "pitch_midi": note.pitch_midi,
            "onset_seconds": round(note.onset_beats * seconds_per_beat, 3),
            "duration_seconds": round(note.duration_beats * seconds_per_beat, 3),
            "confidence": 1.0,
        }
        for note in score.notes
        if note.pitch_midi is not None
    ]


def _await_frame(socket, wanted: str, limit: int = 300) -> dict:
    for _ in range(limit):
        frame = socket.receive_json()
        if frame.get("type") == wanted:
            return frame
    raise AssertionError(f"never received a {wanted!r} frame")


def _open_take(socket, client, practice_session, take_id: str) -> dict:
    socket.send_json(
        {"v": 1, "type": "hello", "seq": 0, "token": client.token, "protocol_version": PROTOCOL_VERSION}
    )
    socket.send_json(
        {
            "v": 1,
            "type": "take.start",
            "seq": 1,
            "take_id": take_id,
            "practice_session_id": practice_session["session_id"],
            "protocol_version": PROTOCOL_VERSION,
        }
    )
    return _await_frame(socket, "session.ready")


class TestHandshake:
    def test_a_bad_token_is_refused(self, coach_client) -> None:
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            socket.send_json(
                {"v": 1, "type": "hello", "seq": 0, "token": "nonsense", "protocol_version": PROTOCOL_VERSION}
            )
            with pytest.raises(Exception):
                socket.receive_json()

    def test_a_protocol_mismatch_is_refused(self, coach_client) -> None:
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            socket.send_json(
                {"v": 1, "type": "hello", "seq": 0, "token": coach_client.token, "protocol_version": "coach.v99"}
            )
            with pytest.raises(Exception):
                socket.receive_json()

    def test_a_good_token_opens_a_take(self, coach_client, practice_session) -> None:
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            ready = _open_take(socket, coach_client, practice_session, str(uuid.uuid4()))
        assert ready["protocol_version"] == PROTOCOL_VERSION
        assert ready["exercise"]["expected_note_count"] == _expected_event_count()
        assert ready["exercise"]["instrument"] == "piano"
        assert ready["resumed"] is False

    # @spec COACH-SESSION-003, COACH-SESSION-012
    def test_take_is_resumable_after_reconnect(self, coach_client, practice_session) -> None:
        take_id = str(uuid.uuid4())
        # First connection opens the take
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            ready1 = _open_take(socket, coach_client, practice_session, take_id)
            assert ready1["resumed"] is False

        # Second connection resumes the active take
        with coach_client.websocket_connect("/api/practice/coach") as socket2:
            ready2 = _open_take(socket2, coach_client, practice_session, take_id)
            assert ready2["resumed"] is True


class TestLiveCues:
    def test_notes_produce_live_cues(self, coach_client, practice_session) -> None:
        notes = _perfect_notes()
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            _open_take(socket, coach_client, practice_session, str(uuid.uuid4()))
            socket.send_json(
                {"v": 1, "type": "notes", "seq": 2, "take_id": str(uuid.uuid4()),
                 "take_clock_seconds": 2.0, "notes": notes}
            )
            cue = _await_frame(socket, "cue")
        assert cue["expected_note_count"] == _expected_event_count()
        # Every note was played correctly, so the cursor should have advanced.
        assert cue["cursor"] > 0

    def test_the_coach_speaks_at_a_rest(self, coach_client, practice_session) -> None:
        """A silence frame after a rough passage is what earns an utterance."""
        rough = [
            {"pitch_midi": 60, "onset_seconds": 0.0, "duration_seconds": 0.5, "confidence": 1.0},
            {"pitch_midi": 61, "onset_seconds": 0.2, "duration_seconds": 0.5, "confidence": 1.0},
            {"pitch_midi": 63, "onset_seconds": 0.4, "duration_seconds": 0.5, "confidence": 1.0},
            {"pitch_midi": 66, "onset_seconds": 0.6, "duration_seconds": 0.5, "confidence": 1.0},
        ]
        take_id = str(uuid.uuid4())
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            _open_take(socket, coach_client, practice_session, take_id)
            socket.send_json(
                {"v": 1, "type": "notes", "seq": 2, "take_id": take_id, "take_clock_seconds": 1.0, "notes": rough}
            )
            socket.send_json(
                {"v": 1, "type": "frame", "seq": 3, "take_id": take_id,
                 "take_clock_seconds": 9.0, "rms_db": -90.0, "silence_seconds": 2.0}
            )
            begin = _await_frame(socket, "coach.begin")
            delta = _await_frame(socket, "coach.delta")
            end = _await_frame(socket, "coach.end")

        assert begin["cue"]
        assert delta["text"]
        assert end["spoken_text"]
        # Zero keys, zero network, and the learner still hears a real sentence.
        assert end["voice_provider"] == "fake"

        with sync_session() as session:
            utterances = list(session.scalars(select(CoachUtterance)))
            assert len(utterances) == 1
            assert utterances[0].spoken_text == end["spoken_text"]
            ledger = list(session.scalars(select(LlmCall).where(LlmCall.role == "live_coach_cue")))
            assert len(ledger) == 1, "a streamed call must write exactly one ledger row"
            assert ledger[0].status in {"ok", "cancelled"}


class TestFinalize:
    def test_a_take_finalizes_to_one_attempt(self, coach_client, practice_session) -> None:
        take_id = str(uuid.uuid4())
        notes = _perfect_notes()
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            _open_take(socket, coach_client, practice_session, take_id)
            socket.send_json(
                {"v": 1, "type": "notes", "seq": 2, "take_id": take_id, "take_clock_seconds": 2.0, "notes": notes}
            )
            socket.send_json(
                {"v": 1, "type": "take.finalize", "seq": 3, "take_id": take_id,
                 "notes": notes, "duration_seconds": 2.0}
            )
            result = _await_frame(socket, "take.result")

        attempt = result["attempt"]
        assert attempt["status"] == "completed"
        assert attempt["overall_score"] >= 0.99
        assert attempt["exp_awarded"] > 0

        with sync_session() as session:
            coach_session = session.get(CoachSession, uuid.UUID(take_id))
            assert coach_session is not None
            assert coach_session.status == "finalized"
            assert coach_session.attempt_id is not None
            # Divergence telemetry: what the live matcher believed, recorded
            # next to what the batch scorer decided.
            assert coach_session.live_matched_note_count == 4

    def test_the_http_fallback_shares_the_idempotency_key(self, coach_client, practice_session) -> None:
        """A dropped socket must not cost the learner a second EXP award."""
        take_id = str(uuid.uuid4())
        notes = _perfect_notes()
        with coach_client.websocket_connect("/api/practice/coach") as socket:
            _open_take(socket, coach_client, practice_session, take_id)
            socket.send_json(
                {"v": 1, "type": "take.finalize", "seq": 2, "take_id": take_id,
                 "notes": notes, "duration_seconds": 2.0}
            )
            first = _await_frame(socket, "take.result")["attempt"]

        replay = coach_client.post(
            f"/api/practice/sessions/{practice_session['session_id']}/attempts",
            json={"observed_notes": notes},
            headers={"Idempotency-Key": f"coach:{take_id}"},
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == first["id"]
        assert replay.json()["exp_awarded"] == first["exp_awarded"]


def test_the_socket_and_the_clip_path_agree(coach_client, practice_session) -> None:
    """The regression this whole feature has to survive.

    Same notes, two delivery paths, one grade. If these ever diverge, the
    streaming layer has become a second scoring system and the numbers a learner
    sees depend on how they happened to submit.
    """
    notes = _perfect_notes()
    take_id = str(uuid.uuid4())
    with coach_client.websocket_connect("/api/practice/coach") as socket:
        _open_take(socket, coach_client, practice_session, take_id)
        socket.send_json(
            {"v": 1, "type": "take.finalize", "seq": 2, "take_id": take_id,
             "notes": notes, "duration_seconds": 2.0}
        )
        streamed = _await_frame(socket, "take.result")["attempt"]

    second = coach_client.post("/api/practice/sessions", json={"exercise_id": practice_session["exercise_id"]})
    assert second.status_code == 201
    clip = coach_client.post(
        f"/api/practice/sessions/{second.json()['id']}/attempts",
        json={"observed_notes": notes},
        headers={"Idempotency-Key": f"clip:{uuid.uuid4()}"},
    )
    assert clip.status_code == 201

    assert streamed["metrics"] == clip.json()["metrics"]

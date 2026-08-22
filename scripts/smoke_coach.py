r"""Drive a full coached take over the live WebSocket, with no keys and no n8n.

Proves the headline loop end to end the way the browser does it: open the
socket, stream notes, fall silent, hear the coach, finalize, and get a graded
attempt with EXP -- then replay the finalize to show the idempotency key holds.

Needs `docker compose up -d`, `python -m app.seed`, and `DEV_AUTH_ENABLED=true`.
No live server: it speaks to the ASGI app in-process, exactly like the other
smoke runners here.

    cd backend
    .\.venv\Scripts\python.exe ..\scripts\smoke_coach.py
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

logging.disable(logging.INFO)

from sqlalchemy import select  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.db.session import sync_session  # noqa: E402
from app.evaluation.musicxml import parse_musicxml  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CoachSession, Exercise, ScoreAsset  # noqa: E402
from app.schemas.coach import PROTOCOL_VERSION  # noqa: E402
from app.seed import PIANO_COURSE_ID  # noqa: E402


def _fail(message: str) -> None:
    print(f"  FAIL  {message}")
    raise SystemExit(1)


def _perfect_notes(exercise_id: uuid.UUID) -> list[dict]:
    with sync_session() as session:
        exercise = session.get(Exercise, exercise_id)
        asset = session.get(ScoreAsset, exercise.score_asset_id)
        score = parse_musicxml(asset.content)
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


def _await(socket, wanted: str, limit: int = 400) -> dict:
    for _ in range(limit):
        frame = socket.receive_json()
        if frame.get("type") == wanted:
            return frame
    _fail(f"never received a {wanted!r} frame")
    raise AssertionError


def main() -> None:
    with sync_session() as session:
        exercise = session.scalar(select(Exercise).where(Exercise.course_id == PIANO_COURSE_ID).limit(1))
        if exercise is None:
            _fail("no piano exercise found -- run `python -m app.seed` first")
        exercise_id = exercise.id
        exercise_title = exercise.title

    notes = _perfect_notes(exercise_id)
    take_id = str(uuid.uuid4())

    with TestClient(app) as client:
        login = client.post("/api/auth/dev-login")
        if login.status_code != 200:
            _fail(f"dev login returned {login.status_code} -- is DEV_AUTH_ENABLED=true?")
        token = login.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        print("  ok    signed in as the seeded dev user")

        created = client.post("/api/practice/sessions", json={"exercise_id": str(exercise_id)})
        if created.status_code != 201:
            _fail(f"could not open a practice session: {created.text}")
        session_id = created.json()["id"]
        print(f"  ok    practice session for {exercise_title!r}")

        with client.websocket_connect("/api/practice/coach") as socket:
            socket.send_json({"v": 1, "type": "hello", "seq": 0, "token": token,
                              "protocol_version": PROTOCOL_VERSION})
            socket.send_json({"v": 1, "type": "take.start", "seq": 1, "take_id": take_id,
                              "practice_session_id": session_id, "protocol_version": PROTOCOL_VERSION})
            ready = _await(socket, "session.ready")
            print(f"  ok    take open -- {ready['exercise']['expected_note_count']} notes expected, "
                  f"audio as {ready['audio_format']}")

            # Play it badly on purpose, so the coach has something to say.
            wrong = [dict(note, pitch_midi=note["pitch_midi"] + 3) for note in notes]
            socket.send_json({"v": 1, "type": "notes", "seq": 2, "take_id": take_id,
                              "take_clock_seconds": 1.5, "notes": wrong})
            cue = _await(socket, "cue")
            print(f"  ok    live cue at note {cue['cursor']}/{cue['expected_note_count']} "
                  f"-- {cue['cue'] or 'listening'}")

            # Fall silent. A phrase boundary is the only moment the coach speaks.
            socket.send_json({"v": 1, "type": "frame", "seq": 3, "take_id": take_id,
                              "take_clock_seconds": 12.0, "rms_db": -95.0, "silence_seconds": 2.0})
            begin = _await(socket, "coach.begin")
            end = _await(socket, "coach.end")
            print(f"  ok    coach spoke [{begin['cue']}] via {end['provider']}/{end['voice_provider']}")
            print(f"        \"{end['spoken_text']}\"")

            # Now play it correctly and finalize.
            socket.send_json({"v": 1, "type": "take.finalize", "seq": 4, "take_id": take_id,
                              "notes": notes, "duration_seconds": 12.0})
            attempt = _await(socket, "take.result")["attempt"]
            print(f"  ok    scored {attempt['overall_score']:.2f} -- {attempt['exp_awarded']} EXP "
                  f"({attempt['status']})")
            print(f"        {attempt['feedback']['summary']}")

        # The same key the socket used. A dropped connection must not cost a
        # second attempt or a second award.
        replay = client.post(
            f"/api/practice/sessions/{session_id}/attempts",
            json={"observed_notes": notes},
            headers={"Idempotency-Key": f"coach:{take_id}"},
        )
        if replay.status_code != 201 or replay.json()["id"] != attempt["id"]:
            _fail("the HTTP fallback did not return the original attempt")
        if replay.json()["exp_awarded"] != attempt["exp_awarded"]:
            _fail("the replay awarded EXP a second time")
        print("  ok    HTTP replay returned the same attempt, awarded nothing twice")

        board = client.get("/api/quests/daily")
        print(f"  ok    quest board: {len(board.json()['quests'])} quests")

    with sync_session() as session:
        record = session.get(CoachSession, uuid.UUID(take_id))
        print(f"  ok    take recorded: {record.status}, "
              f"live matched/missed/extra = {record.live_matched_note_count}/"
              f"{record.live_missed_note_count}/{record.live_extra_note_count}, "
              f"{record.utterance_count} utterance(s), {record.suppressed_turn_count} suppressed")

    print("\nThe live coaching loop works end to end with no API keys.")


if __name__ == "__main__":
    main()

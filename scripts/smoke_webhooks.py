r"""Fake n8n runner: exercise all three webhook contracts against the seeded data.

Needs `docker compose up -d`, `python -m app.seed`, and `DEV_AUTH_ENABLED=true`
(plus `DEV_WEBHOOKS_ENABLED=true` unless WEBHOOK_SECRET is set). No n8n, no
worker, no providers -- this proves the orchestration seam end to end the way
n8n would call it, including the replay guard.

    cd backend
    .\.venv\Scripts\python.exe ..\scripts\smoke_webhooks.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

logging.disable(logging.INFO)

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import sync_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Exercise  # noqa: E402
from app.seed import PIANO_COURSE_ID  # noqa: E402
from app.services import webhook_service  # noqa: E402

NOTES = [
    {"pitch_midi": 60, "onset_seconds": 0.0},
    {"pitch_midi": 62, "onset_seconds": 0.5},
    {"pitch_midi": 64, "onset_seconds": 1.0},
    {"pitch_midi": 65, "onset_seconds": 1.5},
]


def _exercise_id() -> str:
    with sync_session() as session:
        exercise = session.scalar(
            select(Exercise).where(Exercise.course_id == PIANO_COURSE_ID, Exercise.slug == "stepwise-c-major")
        )
        if exercise is None:
            raise SystemExit("FAILED: piano exercise missing. Run `python -m app.seed`.")
        return str(exercise.id)


async def main() -> int:
    settings = get_settings()
    secret = settings.webhook_secret

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://smoke") as client:
        login = await client.post("/api/auth/dev-login")
        if login.status_code != 200:
            print("FAILED: dev-login unavailable. Run `python -m app.seed` and set DEV_AUTH_ENABLED=true.")
            return 1
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        user_id = login.json()["user"]["id"]
        print(f"signed in as   {login.json()['user']['email']}")

        if not secret and not settings.dev_webhooks_enabled:
            print("FAILED: webhooks need WEBHOOK_SECRET or DEV_WEBHOOKS_ENABLED=true.")
            return 1

        # 1. Complete a real piano attempt so the webhooks have something to see.
        exercise_id = _exercise_id()
        practice = await client.post("/api/practice/sessions", headers=headers, json={"exercise_id": exercise_id})
        practice.raise_for_status()
        attempt = await client.post(
            f"/api/practice/sessions/{practice.json()['id']}/attempts",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"observed_notes": NOTES},
        )
        attempt.raise_for_status()
        attempt_id = attempt.json()["id"]
        print(f"attempt        {attempt.json()['metrics']['overall_score']:.0%} "
              f"({attempt.json()['metrics']['evaluator_version']})")

        # 2. Fire each webhook the way n8n would: signed when a secret is set.
        def send(event_type: str, payload: dict):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request_headers = {"Content-Type": "application/json"}
            if secret:
                request_headers["X-Webhook-Signature"] = webhook_service.sign_payload(secret, body)
            return client.post(f"/api/webhooks/v1/{event_type}", headers=request_headers, content=body)

        now = datetime.now(timezone.utc).isoformat()

        session_event = {"event_id": str(uuid.uuid4()), "occurred_at": now, "attempt_id": attempt_id}
        response = await send("session.completed", session_event)
        response.raise_for_status()
        result = response.json()
        session_result = result["result"]
        print(f"session.done   {result['status']}  score {result['result']['overall_score']:.0%} "
              f"feedback={result['result']['has_feedback']}")

        feedback_event = {
            "event_id": str(uuid.uuid4()),
            "occurred_at": now,
            "attempt_id": attempt_id,
            "voice": True,
        }
        response = await send("feedback.requested", feedback_event)
        response.raise_for_status()
        result = response.json()
        print(f"feedback       {result['status']}  {result['result']['feedback_persona']}  "
              f"voice={result['result']['voice']['provider']}")

        quest_event = {"event_id": str(uuid.uuid4()), "occurred_at": now, "user_id": user_id}
        response = await send("daily-quests.refresh", quest_event)
        response.raise_for_status()
        result = response.json()
        print(f"quests         {result['status']}  {result['result']['quest_count']} quest(s)  "
              f"{result['result']['total_reward_exp']} EXP")

        # 3. Replay the session event: the ledger must answer `duplicate` with
        # the same stored result, proving no second side effect ran.
        replay = await send("session.completed", session_event)
        replay.raise_for_status()
        if replay.json()["status"] != "duplicate":
            print(f"FAILED: replay answered {replay.json()['status']}, expected duplicate.")
            return 1
        if replay.json()["result"] != session_result:
            print("FAILED: replay returned a different result than the first delivery.")
            return 1
        print(f"replay         {replay.json()['status']}  (no re-execution)")

        print("\nSMOKE PASSED: signed webhooks -> process -> replay guard all work.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

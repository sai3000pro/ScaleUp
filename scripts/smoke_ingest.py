r"""End-to-end smoke test: register -> course -> upload -> poll until the worker finishes.

Requires `docker compose up -d` and a running Celery worker. This is the check
that the API, Redis, and the worker are genuinely connected -- a unit test cannot
tell you that.

    cd backend
    .\.venv\Scripts\python.exe ..\scripts\smoke_ingest.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

logging.disable(logging.INFO)

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.fixtures.sample_pdf import build_sample_pdf  # noqa: E402

POLL_TIMEOUT_SECONDS = 60
TERMINAL = {"succeeded", "failed", "cancelled"}


async def main() -> int:
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://smoke") as client:
        registered = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "hunter22-long-enough", "display_name": "Smoke"},
        )
        registered.raise_for_status()
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        print(f"registered {email}")

        course = await client.post("/api/courses", json={"title": "Smoke Course"}, headers=headers)
        course.raise_for_status()
        course_id = course.json()["id"]
        print(f"course     {course_id}")

        upload = await client.post(
            f"/api/courses/{course_id}/documents",
            headers=headers,
            files={"file": ("sample.pdf", build_sample_pdf(), "application/pdf")},
        )
        upload.raise_for_status()
        job_id = upload.json()["job_id"]
        print(f"queued     job {job_id} (HTTP {upload.status_code})")

        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        state = "queued"
        while time.monotonic() < deadline and state not in TERMINAL:
            await asyncio.sleep(0.5)
            job = (await client.get(f"/api/jobs/{job_id}", headers=headers)).json()
            if job["state"] != state:
                state = job["state"]
                print(f"           -> {state} ({job['percent']}%)")

        if state != "succeeded":
            print(f"\nSMOKE FAILED: job ended in state {state!r}. Is the Celery worker running?")
            return 1

        job = (await client.get(f"/api/jobs/{job_id}", headers=headers)).json()
        detail = job["stage_detail"]
        print(
            f"\nstages     pages={detail.get('pages')} chunks={detail.get('chunks')} "
            f"windows={detail.get('windows')} (failed {detail.get('failed_windows')})"
        )
        print(
            f"           concepts {detail.get('concepts_raw')} raw -> {detail.get('concepts_merged')} merged; "
            f"edges {detail.get('edges_accepted')} accepted / {detail.get('edges_rejected')} rejected; "
            f"neo4j {detail.get('neo4j_edges')}"
        )

        graph = (await client.get(f"/api/courses/{course_id}/graph", headers=headers)).json()
        stats = graph["stats"]
        print(f"\ngraph      {len(graph['nodes'])} nodes, {len(graph['edges'])} rendered edges")
        print(f"           {stats}")
        for node in graph["nodes"][:6]:
            print(f"           d{node['depth']}  {node['progress']['state']:<10} {node['title']}")

        if not graph["nodes"]:
            print("\nSMOKE FAILED: pipeline succeeded but produced no skill nodes.")
            return 1

        print("\nSMOKE PASSED: upload -> parse -> chunk -> embed -> extract -> project -> graph.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

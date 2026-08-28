"""The deployed loop, exercised end to end against a live URL.

The unit suite proves the logic and the other smoke scripts prove the loop on a
developer's machine. Neither one can tell you that the thing on the internet
works, and that gap is where this project's worst bug lived: every `POST /drill`
in production answered 500 for as long as Gemini's shared free tier was busy,
while every test on every laptop stayed green, because the tests run on the
deterministic provider and the deterministic provider is never busy.

So this talks to a real deployment over HTTPS, with real credentials configured,
and asserts the four things a visitor actually does:

    sign in  ->  see courses  ->  be asked a question  ->  be graded on it

It is deliberately read-mostly and idempotent. It creates one drill attempt and
grades it, which is what a learner does, and awards EXP exactly once because the
endpoint is idempotent on the key it sends.

    python scripts/smoke_production.py
    python scripts/smoke_production.py --api https://scaleup-uflg.onrender.com

Exit status is 0 when the deployment serves the loop and 1 when it does not, so
this is usable as a post-deploy gate rather than only by eye.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API = "https://scaleup-uflg.onrender.com"

#: A free Render instance spins down after inactivity and takes tens of seconds
#: to answer the first request. That is a cold start, not a failure, and a smoke
#: script that reported it as one would cry wolf on every first run of the day.
COLD_START_TIMEOUT = 180


class Failure(Exception):
    """A deployment that did not serve the loop. Carries what to look at."""


def _call(
    api: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, object]:
    request = urllib.request.Request(
        f"{api}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
    )
    request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:400]
        return error.code, detail
    except urllib.error.URLError as error:
        raise Failure(f"could not reach {api}: {error.reason}") from error


def _step(label: str) -> None:
    print(f"  {label} ... ", end="", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API, help="base URL of the deployed API")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    print(f"\nScaleUp production smoke -- {api}\n")

    # 1. Liveness, generously, because a cold start is not a failure.
    _step("waking the service")
    started = time.monotonic()
    status, _ = _call(api, "/api/health/live", timeout=COLD_START_TIMEOUT)
    if status != 200:
        raise Failure(f"/api/health/live answered {status}")
    print(f"up in {time.monotonic() - started:.0f}s")

    # 2. What is actually configured out there. Printed rather than asserted:
    #    the loop is required to work on the deterministic floor too, so a
    #    provider being off is information, not a failure.
    _step("providers")
    status, report = _call(api, "/api/health/providers")
    if status != 200 or not isinstance(report, dict):
        raise Failure(f"/api/health/providers answered {status}")
    selected = report.get("selected", {})
    lanes = report.get("llm_lanes", {})
    print(f"llm={selected.get('llm')} voice={selected.get('voice')} lanes={lanes}")

    # 3. Sign in.
    _step("dev-login")
    status, session = _call(api, "/api/auth/dev-login", body={})
    if status != 200 or not isinstance(session, dict) or not session.get("access_token"):
        raise Failure(f"dev-login answered {status}: {session}")
    token = str(session["access_token"])
    print("ok")

    # 4. The seeded courses. Zero means the seed never ran against this database,
    #    which looks exactly like a broken app from the browser.
    _step("courses")
    status, courses = _call(api, "/api/courses", token=token)
    if status != 200:
        raise Failure(f"/api/courses answered {status}: {courses}")
    listed = courses if isinstance(courses, list) else (courses or {}).get("courses", [])
    if not listed:
        raise Failure("no courses -- run `python -m app.seed` against the deployed database")
    course_id = listed[0]["id"]
    print(f"{len(listed)} course(s)")

    # 5. A drillable skill.
    _step("skill graph")
    status, graph = _call(api, f"/api/courses/{course_id}/graph", token=token)
    if status != 200 or not isinstance(graph, dict):
        raise Failure(f"course graph answered {status}: {graph}")
    drillable = [node for node in graph.get("nodes", []) if node.get("assessable")]
    if not drillable:
        raise Failure("no assessable node in the first course")
    node = drillable[0]
    print(f"{len(drillable)} assessable, using {node['title']!r}")

    # 6. The question. THIS is the call that answered 500 in production for as
    #    long as Gemini's stronger alias was busy, and it is the reason this
    #    script exists.
    _step("issue a drill")
    key = f"smoke-{int(time.time())}"
    status, drill = _call(
        api,
        f"/api/nodes/{node['id']}/drill",
        token=token,
        body={"question_type": "short_answer"},
        headers={"Idempotency-Key": key},
        timeout=90,
    )
    if status != 201 or not isinstance(drill, dict):
        raise Failure(f"drill answered {status}: {drill}")
    question = str(drill.get("question", ""))
    if not question.strip():
        raise Failure("drill returned an empty question")
    print("ok")
    print(f"      -> {question[:150]}")

    # 7. Grading, which is the other half of the loop and the other Gemini role
    #    a learner waits on.
    _step("grade an answer")
    status, grade = _call(
        api,
        f"/api/attempts/{drill['attempt_id']}/grade",
        token=token,
        body={"answer": "You pass the thumb under the hand to continue the scale smoothly."},
        timeout=90,
    )
    if status != 200 or not isinstance(grade, dict):
        raise Failure(f"grade answered {status}: {grade}")
    if "score" not in grade:
        raise Failure(f"grade returned no score: {grade}")
    print(f"score={grade['score']} verdict={grade.get('verdict')}")
    print(f"      -> {str(grade.get('feedback', ''))[:150]}")

    print("\nThe deployed loop serves: sign in -> courses -> question -> grade.\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Failure as failure:
        print(f"\nFAILED: {failure}\n", file=sys.stderr)
        raise SystemExit(1) from failure

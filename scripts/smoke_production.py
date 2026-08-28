"""The deployed loop, exercised end to end against a live URL.

The unit suite proves the logic and the other smoke scripts prove the loop on a
developer's machine. Neither one can tell you that the thing on the internet
works, and that gap is where this project's worst bug lived: every `POST /drill`
in production answered 500 for as long as Gemini's shared free tier was busy,
while every test on every laptop stayed green, because the tests run on the
deterministic provider and the deterministic provider is never busy.

So this talks to a real deployment over HTTPS, with real credentials configured,
and asserts the four things a visitor actually does:

    sign in -> see courses -> be asked a question -> be graded on it
    -> play a take -> be scored against the score -> be coached about it

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


class Deploying(Exception):
    """The platform is between versions. Not a verdict on the app."""


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
        detail = error.read().decode(errors="replace")
        # A 502 or 503 carrying the platform's own HTML is Render swapping the
        # instance out, not the app answering. Reporting that as a failed loop
        # would cry wolf on exactly the run that matters -- the one straight
        # after a push.
        if error.code in (502, 503) and "<html" in detail[:200].lower():
            raise Deploying(f"the platform answered {error.code} for {path}") from error
        return error.code, detail[:400]
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
    status, alive = _call(api, "/api/health/live", timeout=COLD_START_TIMEOUT)
    if status != 200 or not isinstance(alive, dict):
        raise Failure(f"/api/health/live answered {status}")
    # Which revision answered, so a green run cannot be credited to a build that
    # is not the one you just pushed.
    revision = alive.get("revision") or "unknown"
    print(f"up in {time.monotonic() - started:.0f}s, serving {revision}")

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

    # 8. The headline feature: a take, scored against a digital score, explained
    #    by the examiner. Played perfectly from the exercise's own expected notes,
    #    which is the same no-microphone fixture path the browser offers, so this
    #    needs neither audio nor a real instrument.
    _step("practice exercises")
    status, exercises = _call(api, f"/api/courses/{course_id}/practice/exercises", token=token)
    if status != 200 or not isinstance(exercises, list) or not exercises:
        raise Failure(f"practice exercises answered {status}: {exercises}")
    exercise = exercises[0]
    expected = exercise.get("notes") or []
    if not expected:
        raise Failure(f"exercise {exercise['title']!r} carries no score notes")
    print(f"{len(exercises)} exercise(s), using {exercise['title']!r} ({len(expected)} notes)")

    _step("open a practice session")
    status, practice = _call(api, "/api/practice/sessions", token=token, body={"exercise_id": exercise["id"]})
    if status != 201 or not isinstance(practice, dict):
        raise Failure(f"practice session answered {status}: {practice}")
    print("ok")

    _step("submit a perfect take")
    seconds_per_beat = 60.0 / float(exercise["tempo_bpm"])
    played = [
        {
            "pitch_midi": note["pitch_midi"],
            "onset_seconds": note["onset_beats"] * seconds_per_beat,
            "duration_seconds": note["duration_beats"] * seconds_per_beat,
            "confidence": 1.0,
            "string": note.get("string"),
            "fret": note.get("fret"),
        }
        for note in expected
    ]
    status, attempt = _call(
        api,
        f"/api/practice/sessions/{practice['id']}/attempts",
        token=token,
        body={"observed_notes": played, "analyzer": "smoke-fixture"},
        headers={"Idempotency-Key": f"{key}-take"},
        timeout=90,
    )
    if status != 201 or not isinstance(attempt, dict):
        raise Failure(f"attempt answered {status}: {attempt}")
    score = attempt.get("overall_score")
    if not isinstance(score, (int, float)):
        raise Failure(f"attempt returned no score: {attempt}")
    # A note-perfect replay of the score should not come back mediocre. This is
    # the assertion that would catch an evaluator wired to the wrong instrument.
    if score < 0.8:
        raise Failure(f"a note-perfect take scored {score:.2f} -- the evaluator is not reading this score")
    metrics = attempt.get("metrics") or {}
    print(f"score={score:.2f} exp={attempt.get('exp_awarded')} confidence={attempt.get('alignment_confidence')}")
    print(f"      -> pitch={metrics.get('pitch_accuracy')} rhythm={metrics.get('rhythm_accuracy')}")

    feedback = attempt.get("feedback") or {}
    if not str(feedback.get("summary", "")).strip():
        raise Failure("the examiner said nothing about the take")
    print(f"      -> examiner ({attempt.get('feedback_provider')}): {str(feedback['summary'])[:130]}")

    print("\nThe deployed loop serves: sign in -> courses -> question -> grade -> take -> score -> examiner.\n")
    return 0


#: A Render deploy swaps the instance out for a minute or two -- long enough to
#: wait through, short enough that waiting forever would hide a broken release.
DEPLOY_ATTEMPTS = 8
DEPLOY_PAUSE_SECONDS = 30


if __name__ == "__main__":
    for _remaining in range(DEPLOY_ATTEMPTS, 0, -1):
        try:
            raise SystemExit(main())
        except Failure as failure:
            print(f"\nFAILED: {failure}\n", file=sys.stderr)
            raise SystemExit(1) from failure
        except Deploying as deploying:
            if _remaining == 1:
                print(f"\nFAILED: {deploying}, still, after {DEPLOY_ATTEMPTS} attempts\n", file=sys.stderr)
                raise SystemExit(1) from deploying
            print(f"\n  ({deploying}; waiting {DEPLOY_PAUSE_SECONDS}s and starting over)\n")
            time.sleep(DEPLOY_PAUSE_SECONDS)

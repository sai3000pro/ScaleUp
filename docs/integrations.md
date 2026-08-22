# Integrations

Every external service is **off by default**, and the whole product runs that
way — ingest, scoring, live coaching, voice, quests, email, search. CI runs with
none of them configured. That is not a demo mode: each fallback is a real
implementation, exercised by the same tests as the live path.

Turning one on is configuration, never code. If enabling a provider ever needs a
source edit, that is a bug in the seam.

## The one-command answer

```powershell
cd backend
.\.venv\Scripts\python.exe ..\scripts\check_integrations.py
```

It prints what is live, what is running on a fallback, and — the state worth
having — what was *asked for but is missing its key*. That case otherwise fails
at the first call, inside a Celery task, hours later. Exits non-zero when
something is misconfigured, so it works as a CI gate too.

`GET /api/health/providers` answers the same question over HTTP. Neither ever
includes a secret's value; both report presence only, so they are safe on a demo
screen and safe in a screenshot.

The registry behind both is `backend/app/integrations.py`. Adding an integration
means adding a row there — the script, the endpoint, and the tests all render
from it.

---

## What each one does, and what happens without it

| Integration | Turn on with | Without it |
|---|---|---|
| **Anthropic** | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | A deterministic word matcher runs every prompt, schema, and ledger path. Graphs are real, just less accurate. |
| **OpenAI** | `LLM_PROVIDER=openai` or `EMBEDDING_PROVIDER=openai` + `OPENAI_API_KEY` | Fake embeddings are hashed bag-of-words — directionally sane, so retrieval tests mean something. |
| **Google Gemini** | `LLM_PROVIDER=gemini` or `EMBEDDING_PROVIDER=gemini` + `GEMINI_API_KEY` | The deterministic provider, which streams too — word by word, so the live coach's incremental render and barge-in paths still run. |
| **ElevenLabs** | `VOICE_PROVIDER=elevenlabs` + `ELEVENLABS_API_KEY` | A deterministic silence WAV. Every response still carries `spoken_text`, so the browser speaks it. |
| **n8n inbound** | `WEBHOOK_SECRET` | The three webhook endpoints answer `503`, unless `DEV_WEBHOOKS_ENABLED=true` for local unsigned calls. |
| **n8n outbound** | `N8N_WEBHOOK_URL` | Nothing is emitted. No code path waits on it. |
| **Resend** | `EMAIL_PROVIDER=resend` + `RESEND_API_KEY` | The reset link is logged instead of sent, which is what makes recovery testable locally. |
| **Google OAuth** | `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET` | Email and password sign-in, always available. |
| **Exa** | `RESEARCH_PROVIDER=exa` + `EXA_API_KEY` | Deterministic example results, so propose/review/approve is demoable without a search bill. |
| **Google Cloud Storage** | `STORAGE_BACKEND=gcs` + `GCS_BUCKET` | The local filesystem. Fine on one machine; ephemeral on a managed host. |

### Browser model hosts

Video technique analysis has two credential-free browser dependencies that are not backend
providers: `cdn.jsdelivr.net` serves the pinned MediaPipe Tasks Vision WebAssembly runtime, and
`storage.googleapis.com` serves the pinned hand and pose model assets. The selected MP4 is decoded
locally and is never sent to either host. If either host is unavailable, the interface reports a
model-loading failure and audio practice remains usable.

The exact pinned URLs and the morning verification procedure are documented in
[`video-analysis.md`](video-analysis.md).

---

## ElevenLabs

```dotenv
VOICE_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=sk-...
ELEVENLABS_VOICE_ID=            # empty uses the provider default
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
ELEVENLABS_STREAMING_MODEL_ID=eleven_flash_v2_5
```

Two paths, both behind `app/services/voice.py`:

- **Post-take feedback** — one synthesis per attempt, content-addressed in
  `voice_artifacts` so a re-read never pays twice.
- **Live coaching** — sentence-at-a-time streaming during a take, which is why
  the streaming model defaults to Flash. Latency is the product there; a voice
  that starts two seconds late is worse than a cheaper one that starts now.

A synthesis failure is swallowed at the seam. It degrades delivery and nothing
else — the score is already committed and the text has already reached the
learner.

**`ELEVENLABS_VOICE_ID` feeds the voice-artifact cache key.** Changing the voice
invalidates cached audio, by design: the alternative is serving the old persona
from cache forever.

Verify:

```powershell
cd backend
.\.venv\Scripts\python.exe ..\scripts\smoke_coach.py   # prints the voice provider actually used
```

---

## n8n

Two independent directions. Either can be on without the other.

### Inbound — n8n calls the app

`POST /api/webhooks/v1/{session.completed,feedback.requested,daily-quests.refresh}`

Signed HMAC-SHA256 over the **exact request bytes**:
`X-Webhook-Signature: sha256=<hex>`, keyed by `WEBHOOK_SECRET`. Pretty-printing
the JSON changes the signature, so the shipped workflow serialises once in a
Code node and signs that same string.

Replays are answered from the `webhook_events` ledger by caller-supplied
`event_id` — `status: duplicate`, with the stored result, without re-executing.

Import `n8n/workflows/nightly-quest-refresh.json` and set the secret and user id
in its Build payload node.

### Outbound — the app calls n8n

```dotenv
N8N_WEBHOOK_URL=https://your-n8n/webhook/learn-any-instrument
N8N_TIMEOUT_SECONDS=5
```

So a workflow can react to a finished take rather than polling for one. Events:
`attempt.completed`, `node.unlocked`, `curriculum.published`. Signed with the
same `WEBHOOK_SECRET` when one is set, unsigned when it is not (a local n8n with
no shared secret is a real setup, not an error).

Every delivery failure is swallowed. Events are emitted only *after* the attempt
is committed, so an automation platform being down can never cost a learner a
take. There is no retry queue — if you need delivery guarantees, put a queue in
n8n rather than in the practice path.

Import `n8n/workflows/attempt-completed.json` for a starting point.

---

## Language models

```dotenv
LLM_PROVIDER=gemini             # or anthropic, or openai
GEMINI_API_KEY=AIza...
EMBEDDING_PROVIDER=gemini       # Anthropic has no embeddings endpoint; Gemini and OpenAI do
COURSE_LLM_BUDGET_USD=5.00

# Optional: one key per workload lane, each falling back to GEMINI_API_KEY.
GEMINI_API_KEY_INGEST=AIza...   # curriculum planning, extraction, merge, summaries
GEMINI_API_KEY_TUTOR=AIza...    # drills, grading, examiner feedback, Q&A, scores
GEMINI_API_KEY_LIVE=AIza...     # the streaming coach cue
```

Every role declares which lane it belongs to, in the same registry table that
names its model. Separate keys let the lanes bill and rate-limit independently:
compiling a curriculum is bursty and can exhaust a quota, and when it does, a
learner already mid-take should still hear their coach. A call site never names a
lane or a key — it names a role, and the lane rides on the role.

Callers name a **role**, never a model. The role → model mapping is one table in
`app/llm/registry.py`, so serving the high-volume extraction pass with a cheap
model and the once-per-ingest reduce with a strong one is a one-line change.

Every provider names its **own** model for every role, in its own column of that
table, and every one of those models is priced there. A provider that borrowed
another's column would make the cost endpoint quote the wrong vendor's rates for
calls it did not serve.

**Gemini is the only credentialed provider that streams.** Anthropic and OpenAI
are wired for `structured()` only, so with either of them selected the live coach
falls back to its deterministic sentence; the gateway says so explicitly rather
than reporting the call as failed. Gemini is reached through Google's
OpenAI-compatible endpoint — `GEMINI_BASE_URL` overrides it for a proxy or a
pinned API version — which is why no second SDK appears in the lockfile.

Every call goes through `app/services/llm_gateway.py`, which enforces the
per-course budget *before* the call and writes an `llm_calls` row after it —
including for failures and cancelled streams, which are the rows you most want.
`GET /api/courses/{id}/cost` reads them.

The budget is per course, not per request: one textbook ingest is many calls.

---

## Before deploying

`DEPLOYED=true` turns the development defaults into hard startup errors. The app
**refuses to start** with the committed JWT secret, with dev-login enabled, with
the fake email provider, with local storage, without OAuth credentials, without
a webhook secret, with the SSRF check disabled, or with a loopback CORS origin.

That check is deliberately at startup rather than at first use: every one of
those failures is otherwise silent. A placeholder JWT secret works perfectly —
right up until someone reads it in the repository and forges a token.

`check_integrations.py` lists the same requirements *before* you flip the flag,
which is the friendlier time to find out.

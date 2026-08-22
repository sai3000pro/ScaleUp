# ScaleUp

An AI music tutor that listens while you play, watches how you hold the
instrument, and tells you what to fix — in an examiner's voice, on the beat.

Underneath it is a skill tree with spaced repetition: technique you stop
practising decays, and decayed skills come back as daily quests. Anki's
retention mechanics with a tech tree's dopamine loop, pointed at an instrument.

The loop: **choose a skill → play it → get scored → get coached → earn EXP →
watch it decay → come back.**

---

## What it does

Pick an instrument and open a node on its skill tree. The node hands you an
exercise with a real digital score behind it. Play it.

- **It hears you.** Web Audio captures the take in the browser; a pitch tracker
  turns it into note events with onset, duration, and cents deviation — no
  server round trip, no ML bloat on the page.
- **It reads the score.** Dynamic Time Warping aligns what you played against
  the MusicXML, so "you rushed bars 5–8" and "you missed the third note" are
  facts about specific notes rather than one opaque percentage.
- **It watches your form.** MediaPipe tracks hand and body landmarks in the
  browser. Only the landmarks leave the page — never video — and every metric
  carries a confidence and refuses to guess when the camera cannot see you.
- **It coaches you out loud, while you play.** A WebSocket session follows the
  take note by note: a live cursor and timing read at ~10 Hz with no model
  involved, and at most a few spoken corrections, delivered at the rests. The
  coach stays quiet by default -- a tutor who comments on every mistake is
  talking over the thing you are trying to fix.
- **It remembers.** Every attempt updates SM-2 scheduling and an EXP curve.
  Proficiency decays on a half-life tied to your own review interval, so the
  quest board always knows what is fading.

Six instruments ship with published curricula: **piano, guitar, violin,
trumpet, drums, banjo**. Each has a versioned prerequisite DAG, a working
evaluator, and score-backed exercises.

Instruments overlap more than they differ, so skills are defined once in a shared
catalogue (`backend/app/curricula/catalogue.json`) and an instrument *selects and
specialises*: it names the catalogue skills it includes and overrides only title,
summary, difficulty and key terms. Banjo is the proof -- five of its seven concepts
come from the catalogue, three of them authored in two lines each, and it scores
through the guitar evaluator with no banjo-specific code.

---

## Architecture

```
Next.js 15 (App Router, React 19, @xyflow/react, MediaPipe, Web Audio)
        │  REST + WebSocket, JWT
FastAPI ─┼─ services ── domain (pure: DAG, SRS, EXP, coach policy)
        │      │
        │      ├── Postgres    the only source of truth
        │      ├── Neo4j       derived read-model, for traversal
        │      └── Chroma      derived index, for retrieval
        │
     Celery (Redis) ── curriculum source ingestion
     n8n            ── macro-orchestration, nightly quest refresh
```

Layering is strictly one-directional and enforced by review:

```
routers  ->  services  ->  {repositories | models | llm | vector}  ->  domain
tasks    ->  services
domain   ->  nothing
```

Routers never touch SQLAlchemy. Celery tasks hold no business logic.
`app/domain/` imports nothing from the rest of the app, which is why the DAG,
the SRS, and the coach's turn policy are testable in milliseconds with no Docker.

**Postgres is authoritative; Neo4j and Chroma are derived.** Neither ever takes
an authoritative write, and both rebuild from Postgres via
`POST /api/admin/courses/{id}/reindex`. Consistency is therefore "is the
projection stale?" — a monitorable scalar rather than a correctness bug.

### How a performance becomes a grade

```
browser: mic ──▶ pitch + onset + RMS ──▶ note events (pitch, onset, duration, cents)
         cam ──▶ MediaPipe landmarks ──▶ technique metrics (value, confidence, status)
                                   │
                                   ▼
backend:  MusicXML ──▶ expected notes ──▶ DTW alignment ──▶ metric bundle
                                                     │
                              deterministic examiner ─┴─▶ LLM upgrade ──▶ voice
                                                            │
                                              EXP + SM-2 ◀──┘
```

Two properties hold at every stage:

- **The deterministic path is the floor, never a mock.** Scoring, examiner
  feedback, and score generation all work with `LLM_PROVIDER=fake`, no keys, and
  no network. A model can improve the wording; it can never change the numbers.
- **An unreliable measurement never becomes a confident grade.** Silence, a
  low-confidence alignment, or an unseen hand is reported as such and withholds
  EXP rather than inventing a score.

### How the curricula are built

Instrument trees are **versioned curriculum data, not code**. A curriculum
version is drafted, its prerequisite edges are proposed with quoted evidence,
a human reviews them, and only a *published* version can affect unlocks, EXP,
SRS, or quests. Drafts are inert.

Piano, guitar, trumpet, and drums ship as checked-in curriculum JSON compiled
through that pipeline. Violin is generated from source material through the same
generic compiler, with no violin-specific graph code — which is the proof that
adding an instrument does not mean writing Python.

That compiler's source path is the document ingestion engine this project began
as. See [`docs/archive/`](docs/archive/) for what it was and why it stayed.

---

## Getting started

Docker Desktop must be running first. Compose runs **datastores only** — the API,
worker, and frontend run on the host (see *Why the app is not containerised*).

```powershell
# 1. Datastores (postgres, redis, neo4j, chroma)
docker compose up -d
docker compose ps                      # wait for all four to report healthy

# 2. Backend
Copy-Item .env.example .env
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\alembic.exe upgrade head

# Idempotent. Creates dev@example.com / devpassword123 and six published
# curricula -- 11-node piano and 10-node guitar, offered ready-made, plus
# 8-node trumpet, 9-node drums, banjo and a source-generated violin as
# internal courses -- each with score-backed exercises, so the frontend,
# SRS, and practice loop are developable with zero LLM calls. The violin tree
# is compiled from source sections, which is what keeps the document path
# covered with no violin-specific code.
.\.venv\Scripts\python.exe -m app.seed

.\.venv\Scripts\uvicorn.exe app.main:app --reload    # http://localhost:8000/docs
```

```powershell
# 3. Celery worker -- SEPARATE terminal. --pool=solo is required on Windows.
# -Q is NOT optional: tasks route to the ingest queue, and a worker started
# without it consumes only `default`, so every ingest sits queued for ever with
# no error anywhere.
cd backend
.\.venv\Scripts\celery.exe -A app.tasks.celery_app worker --loglevel=INFO --pool=solo -Q default,ingest,llm,graph
```

```powershell
# 4. Frontend -- SEPARATE terminal
cd frontend
npm install
npm run dev                            # http://localhost:3000
```

`.env.example` ships `DEV_AUTH_ENABLED=true`, which registers
`POST /api/auth/dev-login` — the "Use the seeded dev account" button on the login
page, and what the smoke scripts below call. The route is not registered at all
when the flag is off: the endpoint genuinely does not exist rather than merely
refusing, and `Settings` refuses to start with the flag on when `DEPLOYED=true`.

Dev login creates its user if it is missing, so it keeps working after a test run
truncates the table. `python -m app.seed` is still what builds the seeded
courses.

### No API keys needed

`LLM_PROVIDER=fake` is the default, and it is the default on purpose: the whole
practice, scoring, coaching, and drilling loop runs and is tested with **no keys
and no spend**. `VOICE_PROVIDER=fake` returns a deterministic silence WAV and
always carries the spoken text, so the browser falls back to its own TTS. Set
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` and `ELEVENLABS_API_KEY` when you want the
real thing.

Every integration -- Anthropic, OpenAI, ElevenLabs, n8n in both directions,
Resend, Google OAuth, Exa, GCS -- is off by default with a working fallback, and
turning one on is configuration rather than code. `docs/integrations.md` lists
what each one does and what happens without it. To see what actually took
effect:

```powershell
cd backend
.\.venv\Scripts\python.exe ..\scripts\check_integrations.py
```

It reports what is live, what is on a fallback, and what was asked for but is
missing its key -- the case that otherwise fails at the first call rather than
at startup.

---

## Tests

```powershell
cd backend;  .\.venv\Scripts\pytest.exe -q;  .\.venv\Scripts\ruff.exe check .
cd frontend; npm run typecheck; npm run lint; npm run test
```

`tests/unit` needs no datastores and runs with Docker stopped.

## The mascot's sprites

Quartz's twenty frames are cut from `design/sprite_sheet.jpg` by a committed script. Both
the frames and the manifest it writes are committed, so this only runs when the artwork
changes:

```powershell
cd frontend
npm run build:sprites     # -> public/sprites/quartz/*, lib/quartzSprites.ts
```

It is deliberately outside the Next build graph — nothing under `app/` or `lib/` imports
`scripts/`, and `sharp` stays a devDependency. The script gates its own assumptions: a sheet
that does not cut into five rows of four, or a frame that encodes without transparency, fails
the run rather than shipping a sheared drawing. See
`docs/intent/interface/interface-design.md § The mascot`.

## Test an MP4 locally

Open **Video** in the app navigation (or `/video-analysis`), choose an instrument skill, select an MP4,
and press **Analyze video**. Hand and body landmark models run in the browser over the local file;
the MP4 and its audio track are not uploaded or scored. The result includes current feedback, a
timestamped correction timeline, a full-window Pass/Retry/Insufficient-evidence verdict, and a
derived-metric JSON export containing the versioned skill profile and requirement breakdown.

See [`docs/video-analysis.md`](docs/video-analysis.md) for the morning test procedure, network
requirements, responsibility boundary, and the physical-instrument calibration limitations.

> **`pytest` TRUNCATEs every table, including any course you have created.**
> Re-run `python -m app.seed` afterwards to get the seeded courses back. Dev
> login itself survives — it provisions its own user.

## Scripts

```powershell
cd backend
# The headline loop over the real WebSocket: open a coached take, stream notes,
# fall silent, hear the coach, finalize, and prove the idempotency key holds.
.\.venv\Scripts\python.exe ..\scripts\smoke_coach.py

# The practice loop: seed -> choose an exercise -> submit a take -> score ->
# examiner feedback -> EXP -> quest board -> the three webhook contracts.
.\.venv\Scripts\python.exe ..\scripts\smoke_webhooks.py

# The drill loop on the seeded piano course: drill -> grade -> EXP -> unlock.
.\.venv\Scripts\python.exe ..\scripts\smoke_drill.py

# Whole source-ingest chain against a live worker: upload -> parse -> chunk ->
# embed -> extract -> project -> graph.
.\.venv\Scripts\python.exe ..\scripts\smoke_ingest.py

# The time machine. Everything the SRS does is a function of elapsed time, so
# without this the only way to watch a skill decay is to wait days.
.\.venv\Scripts\python.exe ..\scripts\timewarp.py --days 45
.\.venv\Scripts\python.exe ..\scripts\timewarp.py --reset
```

`app.seed` is idempotent for *structure* but deliberately leaves existing EXP and
mastery alone — re-seeding does not reset progress.

n8n is optional and external: `n8n/` holds a versioned workflow template for the
nightly quest refresh, and the signed, replay-safe webhook contracts live in
`docs/api_contract.md` (Webhooks section). The app runs identically with n8n
stopped.

---

## Conventions

- **No `continue` statements.** Anywhere, Python or TypeScript. Use explicit
  `if/elif/else` so every path through a loop is visible at the point of
  decision. Enforced mechanically by `backend/tests/test_no_continue.py` (walks
  the AST) and by `no-continue: error` in the frontend ESLint config.
- **Celery arguments carry identifiers, never content.** Always
  `(job_id, chunk_id_range)`, never a page of text. A 1000-page method book must
  never exist as a single task payload.
- **Callers name an LLM *role*, never a model.** `LLMRole.PERFORMANCE_FEEDBACK`,
  not `"claude-opus-5"`. The role → provider/model/prompt mapping lives in one
  table in `app/llm/registry.py`.
- **Prompts are versioned files, never edited in place.** A new version is a new
  file (`v2.md`), and every `llm_calls` row records `prompt_id`,
  `prompt_version`, and `prompt_sha256`. "Did the coaching change after I edited
  the rubric?" is unanswerable retroactively without the hash.
- **Raw media stays in the browser.** The camera path sends derived landmarks and
  metrics, never video. Audio takes are preserved only as content-addressed
  recordings the owner can delete.
- **Endpoints are stateless and idempotent.** Uploads dedupe on
  `(course_id, content_sha256)`. `POST /drill` and performance submission honour
  `Idempotency-Key`. Re-submitting a graded attempt returns the stored result
  rather than awarding EXP twice or paying a provider twice.
- **Nothing time-derived is stored.** Storing mastery guarantees drift the moment
  a threshold changes, and forces a cron job to keep rows fresh as the clock
  moves.
- **Migrations run explicitly, never on process start.** Auto-migrating at
  startup is the most common way to corrupt a dev database when the API and the
  worker boot concurrently.
- Python: ruff, `line-length = 130`. SQLAlchemy 2.0 `Mapped[]` style. TypeScript
  everywhere on the frontend; `npm run typecheck` must be clean.

`docs/` holds the interface contracts between components. `docs/api_contract.md`
is the seam between `backend/` and `frontend/`, and `frontend/lib/types.ts` is its
literal mirror — with no shared codegen, that document *is* the type system
between the two halves.

---

## Windows specifics

- Celery must run `--pool=solo`. The default `prefork` pool relies on `fork()`,
  which Windows does not have. (Inside a Linux container `prefork` is correct —
  this constraint is specific to running the worker natively.)
- Celery must also run `-Q default,ingest,llm,graph`. The failure mode when you
  forget is silent: the job stays `queued` at 0%, the worker logs nothing, and the
  API is healthy. Check with
  `celery -A app.tasks.celery_app inspect active_queues`.
- Virtualenv executables live at `.venv\Scripts\`, not `.venv/bin/`.
- Host ports are deliberately non-default — Postgres `5433`, Redis `6380`, Chroma
  `8001` — to avoid colliding with local installs. If a bind fails anyway, check
  Hyper-V's reserved ranges:
  `netsh interface ipv4 show excludedportrange protocol=tcp`.

## Why the app is not containerised

This repo lives under a OneDrive-synced path, and Docker Desktop bind mounts do
not propagate inotify events from one. Containerising the app would force polling
watchers for both uvicorn `--reload` and the Next.js dev server, and would put
`node_modules` and `.venv` inside a synced bind mount — which produces
intermittent `EPERM: operation not permitted` during installs and has OneDrive
uploading tens of thousands of `.next` files on every rebuild. `.gitignore` does
not help; OneDrive does not read it.

Datastores get named Docker volumes, so their files never touch the sync path.
Production Dockerfiles are a real thing to want and explicitly not stage-1 work.

- **If installs start failing with `EPERM`, pause OneDrive sync.** It is OneDrive
  holding a file handle, not npm or pip.
- **Never run `npm run build` while `npm run dev` is running.** They share
  `frontend/.next`, and the build overwrites the chunks the dev server is
  serving. The failure looks like application code — `Cannot find module
  './vendor-chunks/zustand.js'`, or a page that renders HTML but never hydrates.
  The fix is always: stop the dev server, delete `.next`, start it again.

---

## Where it stands

Working end to end: auth and Google OAuth, versioned curricula for five
instruments with a generated exercise on every node, the skill tree with five
node states, drilling and grading, EXP and unlocks, SM-2 decay and daily quests,
performance scoring with per-instrument evaluators plus dynamics and posture,
the live coaching socket, deterministic and LLM examiner feedback, spoken
feedback with an ElevenLabs seam, browser hand and pose landmark metrics,
preserved takes, cohort leaderboards, course sharing, signed n8n webhooks, and
the admin reindex surface.

Known limits, stated plainly:

- **Pitch detection is autocorrelation, and monophonic.** It cannot hear a
  chord, so the open-chord exercise is scored from the reference note path rather
  than from audio. Swapping in a CREPE-class detector is a contained change --
  the segmentation layer above it is already pure and tested.
- **Posture thresholds are educated guesses.** They are versioned and the raw
  geometry is persisted precisely so they can be corrected against real takes,
  but nobody has calibrated them yet.
- **Streaming audio into the browser mid-utterance is best-effort.** The text
  always arrives and the OS voice always speaks it; decoded ElevenLabs audio is
  the upgrade, not the guarantee.
- A live take is pinned to one API process. Multi-instance deployment needs
  sticky sessions.

`docs/roadmap.md` is the live work board and tracks what is not done yet.
[`docs/archive/`](docs/archive/) holds the textbook product this began as, and
explains why its pipeline is still running underneath the curriculum compiler.

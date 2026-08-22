# Learn-Any-Instrument

An AI music tutor. A learner picks a skill off an instrument's prerequisite DAG,
plays the exercise behind it, and gets scored on pitch, rhythm, dynamics, and
physical technique — then coached about it in an examiner's voice. EXP and SM-2
decay sit underneath, so unpractised technique fades and returns as a Daily
Quest. Anki's retention mechanics with a tech tree's dopamine loop.

The core loop: **choose a skill → play it → score & coach → reward → decay &
retain.**

Six instruments ship with published, versioned curricula: piano, guitar,
violin, trumpet, drums, banjo. Skills common to several of them are defined once
in `backend/app/curricula/catalogue.json`; an instrument selects from it and
overrides only what genuinely differs.

The document-ingestion engine this project began as is not retired — it is the
curriculum compiler's source path, which is how the violin tree is generated
with no violin-specific code. Its docs live in `docs/archive/`; the pipeline
itself is live and load-bearing.

## Getting started

Docker Desktop must be running first.

```powershell
# 1. Datastores (postgres, redis, neo4j, chroma)
docker compose up -d
docker compose ps                      # wait for all four to report healthy

# 2. Backend
Copy-Item .env.example .env            # then fill in ANTHROPIC_API_KEY / OPENAI_API_KEY
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\alembic.exe upgrade head
# Idempotent. Creates dev@example.com / devpassword123, two courses the project
# offers ready-made (11-node piano, 10-node guitar), and four internal courses
# (8-node trumpet, 9-node drums, banjo, and a source-generated violin), each
# with a score-backed exercise, so the frontend, SRS, and practice loop are
# developable with zero LLM calls. Which shelf a course sits on is declared in
# app/core/shelves.py; the learner's list shows their own, the prebuilt set is a
# tab, and internal courses appear on neither.
.\.venv\Scripts\python.exe -m app.seed

.\.venv\Scripts\uvicorn.exe app.main:app --reload    # http://localhost:8000/docs

# 3. Celery worker — SEPARATE terminal, --pool=solo is required on Windows.
# `-Q` is NOT optional: tasks route to ingest/llm/graph (see celery_app.py), so a
# worker started without it consumes only `default` and every ingest sits queued
# forever with no error anywhere.
cd backend
.\.venv\Scripts\celery.exe -A app.tasks.celery_app worker --loglevel=INFO --pool=solo -Q default,ingest,llm,graph

# 4. Frontend — SEPARATE terminal
cd frontend
npm install
npm run dev                            # http://localhost:3000
```

Tests and linting:

```powershell
cd backend;  .\.venv\Scripts\pytest.exe -q;  .\.venv\Scripts\ruff.exe check .
cd frontend; npm run typecheck; npm run lint; npm run test
```

**`pytest` TRUNCATEs every table, including the seeded dev user.** Re-run
`python -m app.seed` after a test run or dev-login will 404.

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

## Scripts

```powershell
cd backend
# Whole ingest chain against a live worker: upload -> parse -> chunk -> embed
# -> extract -> project -> graph.
.\.venv\Scripts\python.exe ..\scripts\smoke_ingest.py

# What is wired up, what is on a fallback, what is misconfigured. No secrets.
.\.venv\Scripts\python.exe ..\scripts\check_integrations.py

# The live coaching socket end to end, with no keys: notes -> cues -> a spoken
# correction -> a scored attempt -> EXP.
.\.venv\Scripts\python.exe ..\scripts\smoke_coach.py

# The drill loop on the seeded piano course: drill -> grade -> EXP -> unlock.
.\.venv\Scripts\python.exe ..\scripts\smoke_drill.py

# Does the arrow of intent reach the code? Fails on a broken @spec pointer, a
# duplicate spec ID, or a segment missing a doc; prints citation coverage.
.\.venv\Scripts\python.exe ..\scripts\check_arrow.py
.\.venv\Scripts\python.exe ..\scripts\check_arrow.py --coverage --segment evaluation

# The time machine. Everything the SRS does is a function of elapsed time, so
# without this the only way to watch a node decay is to wait days.
.\.venv\Scripts\python.exe ..\scripts\timewarp.py --days 45
.\.venv\Scripts\python.exe ..\scripts\timewarp.py --days 45 --slug keyboard-layout
.\.venv\Scripts\python.exe ..\scripts\timewarp.py --reset
```

Note that `app.seed` is idempotent for *structure* but deliberately leaves
existing EXP and mastery alone — re-seeding does not reset a user's progress.

## Conventions

- **No `continue` statements.** Anywhere, in Python or TypeScript. Use explicit
  `if/elif/else` branching so every path through a loop is visible at the point
  of decision. Enforced mechanically by `backend/tests/test_no_continue.py`
  (walks the AST) and by `no-continue: error` in the frontend ESLint config.
- **Layering, strictly one-directional:**
  ```
  routers  ->  services  ->  {repositories | models | llm | vector}  ->  domain
  tasks    ->  services      (tasks are thin: load session, call service, update job)
  domain   ->  nothing
  ```
  Routers never touch SQLAlchemy. Celery tasks contain no business logic.
  `app/domain/` imports nothing from the rest of the app — which is exactly why
  the DAG and SRS logic can be tested in milliseconds with no Docker running.
- **Postgres is the only source of truth.** Neo4j is a derived read-model for
  traversal; Chroma is a derived index for retrieval. Neither ever receives an
  authoritative write, and both are rebuildable from Postgres via
  `POST /api/admin/courses/{id}/reindex`. Consistency is therefore "is the
  projection stale?" — a monitorable scalar, not a correctness bug.
- **Celery arguments carry identifiers, never content.** Always
  `(job_id, chunk_id_range)`, never a page of text. Content lives in Postgres
  and on disk. A 1000-page book must never exist as a single task payload.
- **Callers name an LLM *role*, never a model.** `LLMRole.GRAPH_EXTRACT_MAP`,
  not `"claude-opus-5"`. The role -> provider/model/prompt mapping lives in one
  table in `app/llm/registry.py`.
- **`LLM_PROVIDER=fake` is the default.** The whole pipeline runs and is tested
  with no API keys and no spend. Tests must never depend on a real provider;
  the one suite that does is marked `@pytest.mark.live` and is opt-in.
- **Prompts are versioned files, never edited in place.** A new version is a new
  file (`v2.md`), and every `llm_calls` row records `prompt_id`,
  `prompt_version`, and `prompt_sha256`. "Did grading accuracy change after I
  edited the rubric?" is unanswerable retroactively unless you store the hash.
- **Endpoints are stateless and idempotent.** Re-uploading a document dedupes on
  `(course_id, content_sha256)`. `POST /drill` honours `Idempotency-Key`.
  Grading an already-graded attempt returns the stored result rather than
  awarding EXP twice.
- **Nothing time-derived is stored.** Mastery, proficiency, and node state are
  computed on read from `(last_reviewed_at, interval_days, ease)`. Storing them
  guarantees drift the moment a threshold changes, and forces a cron job to keep
  rows fresh as the clock moves.
- Python: ruff, `line-length = 130`, `select = ["E", "F", "I", "W"]`. SQLAlchemy
  2.0 `Mapped[]` style. TypeScript everywhere on the frontend; `npm run
  typecheck` must be clean.
- **Raw media stays in the browser.** The camera path sends derived landmarks
  and metrics, never video. Audio takes are preserved only as content-addressed
  recordings their owner can delete.
- `docs/` holds the interface contracts between components. `docs/api_contract.md`
  is the seam between `backend/` and `frontend/`, and `frontend/lib/types.ts` is
  its literal mirror — with no shared codegen, that document *is* the type
  system between the two halves. `docs/roadmap.md` is the live work board.
  `docs/archive/` holds the textbook product this began as, including
  `graph_extraction_contract.md`, which is still the live contract for
  `app/ingestion/`. `docs/integrations.md` covers every external service and
  its fallback; `app/integrations.py` is the table both it and
  `GET /api/health/providers` render from.

## Why the app is not containerised

Compose runs datastores only. The API, worker, and frontend run on the host.

This repo lives under a OneDrive-synced path, and Docker Desktop bind mounts do
not propagate inotify events from one. Containerising the app would force
polling watchers for both uvicorn `--reload` and the Next.js dev server, and
would put `node_modules` and `.venv` inside a synced bind mount — which produces
intermittent `EPERM: operation not permitted` during installs and has OneDrive
uploading tens of thousands of `.next` files on every rebuild. `.gitignore` does
not help; OneDrive does not read it.

Datastores get named Docker volumes, so their files never touch the sync path at
all. Production Dockerfiles are a real thing to want and explicitly not stage-1
work.

**If installs start failing with `EPERM`, pause OneDrive sync.** It is OneDrive
holding a file handle, not npm or pip.

**Never run `npm run build` while `npm run dev` is running.** They share
`frontend/.next`, and the build overwrites the chunks the dev server is serving.
The failure looks like application code — `Cannot find module './vendor-chunks/
zustand.js'`, or a page that renders HTML but never hydrates. The fix is always
the same: stop the dev server, delete `.next`, start it again. Running two dev
servers at once does it too.

## Windows specifics

- Celery must run `--pool=solo`. The default `prefork` pool relies on `fork()`,
  which Windows does not have. (Inside a Linux container `prefork` is correct —
  this constraint is specific to running the worker natively.)
- Celery must also run `-Q default,ingest,llm,graph`. The failure mode when you
  forget is silent: the job stays `queued` at 0%, the worker logs nothing, and
  the API is healthy. Check with `celery -A app.tasks.celery_app inspect
  active_queues` if an ingest never starts.
- Virtualenv executables are at `.venv\Scripts\`, not `.venv/bin/`.
- Host ports are deliberately non-default — Postgres `5433`, Redis `6380`,
  Chroma `8001` — to avoid colliding with local installs. If a bind fails
  anyway, check Hyper-V's reserved ranges:
  `netsh interface ipv4 show excludedportrange protocol=tcp`.

## Migrations

Run them explicitly; never on process start.

```powershell
cd backend
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
.\.venv\Scripts\alembic.exe upgrade head
```

Auto-migrating at startup is the most common way to corrupt a dev database when
the API and the worker boot concurrently.

## LID
- Mode: Full
- Version: 1.3.0

## LID Tooling
- Coherence check: `python scripts/check_arrow.py`

## Linked-Intent Development (MANDATORY)

**Consult the `linked-intent-dev` skill for ALL code changes.** All changes flow through the arrow of intent in one direction:

```
HLD → LLDs → EARS → Tests → Code
```

- **New features and refactors**: full six-phase workflow (HLD check → LLD check/draft → EARS → intent-narrowing edge audit → tests-first → code).
- **Bug fixes**: walk the arrow like any other change — find where behavior diverged from intent and cascade from there. No short-circuit.
- **If unsure**: use the full workflow.

Stop after each phase for user review. **Docs carry current intent, written to be read cold** — write each doc as if authored fresh today, from current intent alone: no narration of how it changed, no meaning that needs the conversation that produced it, no rebuttals to questions only a past discussion raised. Rationale, considered alternatives, and constraints a fresh author would independently write stay; record rejected alternatives and why in the LLD's Decisions & Alternatives table, not as asides in body prose.

**Memory vs. intent.** Before saving durable project knowledge to agent or tool memory, test whether it is project *intent* — would a fresh agent, in any tool, next session, need it to build this system correctly? If yes, record it in the arrow (HLD / LLD / EARS / decision doc), which travels and cascades — not in private, per-tool memory, where intent escapes the arrow. Knowledge about the user or how they like to work stays in memory.

### Tooling

Structural coherence checks are delegated to `scripts/check_arrow.py`. It runs in
CI's `fast` job and fails only on a broken link -- a `@spec` citing a spec that
does not exist, a duplicate spec ID, a segment folder missing its design doc.
Citation coverage is printed and never enforced: an uncited spec is a gap in
linkage rather than a defect in the code, and failing a build for one would
penalise the honest move of writing the spec down.

### Navigation

| What you need | Where to look |
|---|---|
| High-level design | `docs/high-level-design.md` |
| Design tree (sub-HLDs, LLDs, their specs) | `docs/intent/` — one folder per node |
| EARS specs | beside each design doc as `{node}-specs.md` in the node's folder under `docs/intent/` |
| Decision docs | `docs/decisions/` (project-level) and `docs/intent/<segment>/decisions/` |
| Arrow of intent overlay | `docs/arrows/index.yaml` and per-segment docs in `docs/arrows/` |

### Terminology

- **HLD**: High-Level Design — single project-level doc at `docs/high-level-design.md`.
- **LLD**: Low-Level Design — detailed component design doc in `docs/intent/`. The design layer is a recursive tree: the root is the HLD, leaf LLDs own EARS, and a component deep enough to outgrow one doc becomes a sub-HLD (HLD-shaped, owns no EARS) with children beneath it. "HLD" and "LLD" are roles by position; depth-2 (one HLD over flat leaf LLDs) is the default.
- **EARS**: Easy Approach to Requirements Syntax — structured one-line requirements beside each design doc as `{node}-specs.md` in the node's folder under `docs/intent/`. IDs are path-concatenated — the root-to-leaf path of the owning segment plus a number — so a prefix grep gathers a subtree. Markers: `[x]` implemented, `[ ]` active gap, `[D]` deferred.
- **Arrow**: the unidirectional chain from vision to code (HLD → LLDs → EARS → Tests → Code). Strictly a DAG of intent.
- **Arrow segment**: the territory owned by one leaf LLD — the LLD itself plus the specs, tests, and code that cite its EARS IDs. The boundary is the leaf prefix. Within-segment cascade is free; across-segment cascade pauses.
- **Cascade**: propagating a change downstream through the arrow so adjacent levels stay coherent.

### Code annotations

Annotate code and tests with `@spec` comments citing EARS IDs:

```
// @spec AUTH-UI-001, AUTH-UI-002
```

Place the annotation at the *entry point of the behavior's implementation graph* — the topmost function or module owning the specified behavior, not every helper. When a behavior spans multiple subsystems (UI + API + database, for example), annotate at the entry point in each subsystem. Tests follow the same rule: annotate the test that directly exercises the spec, not every inner assertion.

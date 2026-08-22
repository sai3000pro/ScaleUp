# Demo deployment — Render + Vercel

A public, shared-account deployment of ScaleUp for showing the practice loop to
people. Three managed services and a frontend: no cloud provider account, no
OAuth consent screen, no object storage, no credential obtained from a third
party.

This is deliberately **not** the production shape. `docs/deployment.md` describes
that one — Cloud Run, GCS, Resend, Google OAuth, and `DEPLOYED=true` enforcing
all of it. Read that document when the app needs real user accounts. Read this
one when the goal is a URL someone can open.

The distinction is one setting. `DEPLOYED=false` leaves the startup validator in
`app/config.py` switched off, and every integration behind it falls back to the
deterministic path the whole system is built and tested against. Off is a
supported state here, not a broken one.

```text
Vercel                      Render
┌──────────────┐            ┌─────────────────────┐
│ Next.js      │ ─ HTTPS ─► │ FastAPI web service │
│ (frontend/)  │ ─  WSS  ─► │ (backend/)          │
└──────────────┘            └──────────┬──────────┘
                                       ├── Render Postgres
                                       └── Render Key Value (Redis)
```

Names used throughout. Substitute your own consistently — they appear in two
settings that reference each other:

| | Name | URL |
|---|---|---|
| Render web service | `scaleup-api` | `https://scaleup-api.onrender.com` |
| Vercel project | `scaleup` | `https://scaleup.vercel.app` |

Choose both before creating anything. The API needs the frontend's origin for
CORS and the frontend needs the API's URL compiled into its bundle, so deciding
the names up front turns a two-pass setup into one.

## What this deployment does and does not do

Works:

- The full practice loop on the six seeded courses — choose a skill, record a
  take, get scored on pitch, rhythm, dynamics and technique, earn EXP, watch the
  tree unlock.
- The live coach. Render web services carry WebSockets, so `WS
  /api/practice/coach` connects and cues stream.
- Camera technique analysis, which runs entirely in the browser.
- Examiner feedback in the deterministic voice. `LLM_PROVIDER` stays `fake`, so
  wording comes from `app/evaluation/feedback.py` rather than a model. Numbers
  are unaffected either way — a model never touches them.

Does not work, by construction:

| Absent | Consequence |
|---|---|
| Celery worker | Document ingestion and reindex jobs enqueue and stay at `queued` 0% forever. Nothing errors; the job simply never starts. |
| Neo4j | `GET /api/health/ready` reports it down, and reindex staleness cannot be computed. No practice read path touches it. |
| Chroma | The Ask panel, search, and retrieval-backed drills fail. The instrument practice loop does not use it. |
| Object storage | `STORAGE_BACKEND=local` writes to the container's ephemeral disk. Uploaded sources and recorded takes do not survive a redeploy. |

Everyone shares one account. `DEV_AUTH_ENABLED=true` registers `POST
/api/auth/dev-login` (`app/api/routers/dev.py:21`, wired in `app/main.py:74`),
which issues a token for the seeded `dev@example.com` with no password. Anyone
who reaches the URL is that user, and every visitor shares one set of courses,
one EXP total, and one practice history. That is the intent of this deployment;
it is also its entire access-control model.

`JWT_SECRET` is left at the committed placeholder in this configuration, so
tokens are forgeable by anyone who reads the repository. With a single shared
account holding nothing private this changes little, but it is the reason this
shape must not be pointed at real users: the moment a second real account
exists, that account is forgeable too. Setting `JWT_SECRET` to the output of
`python -c "import secrets;print(secrets.token_urlsafe(48))"` closes it and
costs nothing.

## 0. Verify the production build locally

Stop the dev server first.

```powershell
cd frontend
npm run build
```

`npm run build` and `npm run dev` share `frontend/.next`, and building while the
dev server is live overwrites the chunks it is serving. The failure presents as
application code — `Cannot find module './vendor-chunks/…'`, or a page that
renders HTML but never hydrates. The fix is always: stop the dev server, delete
`.next`, start again.

Expect a route table listing `/`, `/courses`, `/login`, `/quests` and the rest.
A failure here is a failure on Vercel too, and it is far cheaper to read the
error locally.

## 1. Postgres

Render dashboard → **New** → **Postgres**. Any region; keep every service in the
same one so they can talk over the internal network.

Render shows two connection strings once it finishes provisioning:

- **Internal Database URL** — `postgresql://scaleup:…@dpg-xxxxx/scaleup` — works
  only from other Render services in the same region. Use this one; it is faster
  and is not exposed to the internet.
- **External Database URL** — has a full public hostname like
  `dpg-xxxxx.oregon-postgres.render.com`. Use this only to connect from your own
  machine.

This application needs **two** URLs derived from the internal one, each naming
its driver explicitly. Take Render's string and insert the driver after
`postgresql`:

```
Render gives you:   postgresql://scaleup:PASSWORD@dpg-xxxxx/scaleup
                              ▲
DATABASE_URL:       postgresql+asyncpg://scaleup:PASSWORD@dpg-xxxxx/scaleup
SYNC_DATABASE_URL:  postgresql+psycopg://scaleup:PASSWORD@dpg-xxxxx/scaleup
```

Both point at the same database. `DATABASE_URL` serves the API through
SQLAlchemy's async engine; `SYNC_DATABASE_URL` serves Alembic, which reads it
directly (`alembic/env.py:20`).

Omitting a driver prefix fails at boot with a SQLAlchemy dialect error that does
not mention the missing prefix. If the API will not start, check this first.

Free Render Postgres instances are deleted after a limited window. Check the
current terms before relying on one for anything you would mind rebuilding — a
rebuild is step 4 again, which is cheap, but the data is gone.

## 2. Redis

Render dashboard → **New** → **Key Value** (Render's name for its managed Redis;
older documentation calls it Redis). Same region as Postgres.

Take the **Internal Key Value URL** and append a database number:

```
CELERY_BROKER_URL=redis://red-xxxxx:6379/0
CELERY_RESULT_BACKEND=redis://red-xxxxx:6379/1
```

If the instance rejects database 1, point both at `/0`. Nothing consumes the
queue in this deployment, so broker and backend never collide.

Redis is still worth attaching even with no worker: `/api/health/ready` probes
it, and the live coach uses it for the cross-instance session claim — which
degrades to a warning when Redis is unreachable, so a missing instance is
survivable rather than fatal.

## 3. The API

Render dashboard → **New** → **Web Service** → connect this repository.

| Field | Value |
|---|---|
| Name | `scaleup-api` |
| Language / Runtime | **Docker** |
| Root Directory | `backend` |
| Dockerfile Path | `./backend/Dockerfile` |
| Health Check Path | `/api/health/live` |
| Instance Type | Free is fine; see cold starts below |

`backend/Dockerfile` needs no changes. It reads `PORT`, which Render supplies,
and it already copies `alembic.ini` and `alembic/`, so the same image runs
migrations in step 4.

**Use `/api/health/live`, not `/api/health/ready`.** `/live` returns
`{"ok": true}` and touches nothing. Readiness deliberately probes all four
datastores, and Neo4j and Chroma are absent here — so pointing Render's health
check at `/ready` produces a service that is permanently marked unhealthy and
restarts forever, with logs that look like a crash loop rather than a
misconfigured probe.

Environment variables. Paste the two database URLs and the two Redis URLs from
steps 1 and 2; the last two are literal:

```
DATABASE_URL=postgresql+asyncpg://scaleup:PASSWORD@dpg-xxxxx/scaleup
SYNC_DATABASE_URL=postgresql+psycopg://scaleup:PASSWORD@dpg-xxxxx/scaleup
CELERY_BROKER_URL=redis://red-xxxxx:6379/0
CELERY_RESULT_BACKEND=redis://red-xxxxx:6379/1
DEV_AUTH_ENABLED=true
CORS_ORIGIN_REGEX=https://scaleup\.vercel\.app
```

`CORS_ORIGIN_REGEX` is a regular expression, so the dots in the hostname are
escaped — an unescaped `.` matches any character and quietly widens the
allowlist. Its default permits loopback origins only, which rejects every
request from the deployed frontend with a CORS error in the browser console and
nothing at all in the Render logs.

Everything else keeps its default, and every default is a working fallback:

| Setting | Default | What that means here |
|---|---|---|
| `LLM_PROVIDER` | `fake` | Coaching text is deterministic. Scores are unaffected — a model never touches a number. |
| `EMBEDDING_PROVIDER` | `fake` | No embedding spend. Only retrieval paths care. |
| `VOICE_PROVIDER` | `fake` | No spoken audio; `spoken_text` still returned. |
| `EMAIL_PROVIDER` | `fake` | Password reset logs a link instead of sending one. |
| `STORAGE_BACKEND` | `local` | Ephemeral container disk. |
| `WEBHOOK_SECRET` | empty | Inbound webhooks return 503 "not configured" rather than accepting unsigned calls (`app/api/routers/webhooks.py:64`). |
| `JWT_SECRET` | placeholder | See the note above. |
| `FRONTEND_URL` | localhost | Used only for password-reset links and OAuth redirect safety, neither of which exists here. |
| `DEPLOYED` | `false` | The startup validator stays off. Setting it true here fails to boot, by design. |

## 4. Migrate and seed

Once, after the service first deploys. Render dashboard → `scaleup-api` →
**Shell**.

```bash
alembic upgrade head
python -m app.seed
```

Run them in that order and never on process start — migrating at startup is how
a database gets corrupted when two instances boot concurrently.

`alembic upgrade head` should print a chain of `Running upgrade …` lines and
exit silently. `python -m app.seed` prints what it creates.

**The seed is not optional.** It creates:

- the user `dev@example.com` / `devpassword123`
- two ready-made courses — an 11-node piano tree and a 10-node guitar tree
- four internal courses — trumpet, drums, banjo, and a source-generated violin

Six instruments, each with a score-backed exercise, which is what makes the app
demonstrable with zero LLM calls. Without this step the API is healthy and the
app is empty.

The seed is idempotent for structure and deliberately leaves existing EXP and
mastery alone, so re-running it after a redeploy is safe and will not reset
anyone's progress.

## 5. The frontend

Vercel → **Add New** → **Project** → import this repository.

| Field | Value |
|---|---|
| Project Name | `scaleup` |
| Framework Preset | Next.js (detected) |
| Root Directory | `frontend` |
| Build / Install commands | leave as detected |

One environment variable:

```
NEXT_PUBLIC_API_BASE_URL=https://scaleup-api.onrender.com
```

Two properties of this value matter:

- **It is compiled in, not read at runtime.** `NEXT_PUBLIC_*` variables are
  inlined into the browser bundle at build time, so changing it requires a
  redeploy, not a restart.
- **It must be absolute.** `lib/coachSocket.ts:26` resolves the WebSocket
  endpoint with `new URL("/api/practice/coach", BASE_URL)`, which throws on a
  relative base. No trailing slash.

`next.config.ts` declares `output: "standalone"`, which exists for self-hosting a
Node server and is redundant on Vercel.

## Environment reference

| Variable | Where | Value |
|---|---|---|
| `DATABASE_URL` | `scaleup-api` | Internal Postgres URL, `postgresql+asyncpg://` |
| `SYNC_DATABASE_URL` | `scaleup-api` | same database, `postgresql+psycopg://` |
| `CELERY_BROKER_URL` | `scaleup-api` | Internal Key Value URL, database 0 |
| `CELERY_RESULT_BACKEND` | `scaleup-api` | Internal Key Value URL, database 1 |
| `DEV_AUTH_ENABLED` | `scaleup-api` | `true` — the shared-account switch |
| `CORS_ORIGIN_REGEX` | `scaleup-api` | `https://scaleup\.vercel\.app` |
| `NEXT_PUBLIC_API_BASE_URL` | Vercel | `https://scaleup-api.onrender.com` |

Seven values. Four are pasted from Render, three are typed literally.

## Verifying

Work down the list; each step depends on the one above it.

**1. The API is up.**
```
GET https://scaleup-api.onrender.com/api/health/live   →  {"ok": true}
```

**2. Every integration is on its fallback.**
```
GET https://scaleup-api.onrender.com/api/health/providers
```
Reports presence, never secret values, so it is safe to read on a shared screen.

**3. Readiness is partially red, and that is expected.**
```
GET https://scaleup-api.onrender.com/api/health/ready
```
Postgres and Redis healthy; Neo4j and Chroma down. This is why the health check
in step 3 points at `/live`.

**4. The interactive docs load.** `https://scaleup-api.onrender.com/docs` — the
OpenAPI page, titled *ScaleUp API*.

**5. The landing page renders.** Open `https://scaleup.vercel.app`. It renders
with no session and no backend call, so it works even while the API is cold.

**6. Sign in.** The login page offers a dev-login button. Six courses appear.
If the courses list is empty, step 4 did not run.

**7. Record a take.** Open a course, choose a skill, play the exercise. A score
comes back with EXP, and the node's state changes on the tree.

**8. The live coach connects.** Start a live coach take; cues stream over the
WebSocket. This is the step that fails on hosts without WebSocket support.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Service restarts forever, logs look like a crash loop | Health check path is `/api/health/ready`. Change it to `/live`. |
| `sqlalchemy.exc.NoSuchModuleError` or a dialect error at boot | A driver prefix is missing from `DATABASE_URL` or `SYNC_DATABASE_URL`. |
| Browser console shows CORS errors, Render logs show nothing | `CORS_ORIGIN_REGEX` does not match the Vercel origin. Check the escaped dots and the `https://`. |
| Frontend loads, every API call fails | `NEXT_PUBLIC_API_BASE_URL` wrong or missing. It is compiled in — redeploy, do not restart. |
| Live coach never connects, everything else works | `NEXT_PUBLIC_API_BASE_URL` is relative or has a trailing slash. |
| Signed in, but no courses | The seed did not run. Re-run `python -m app.seed`. |
| First request of the day hangs for ~a minute | Free-instance cold start. Not an error. |
| An upload sits at 0% forever | No Celery worker. Expected; see below. |

## Known rough edges

**Cold starts.** Free Render services spin down after inactivity and take tens of
seconds to answer the first request. The frontend surfaces this as a hung load,
not as an error. If you are demoing live, open the URL a minute beforehand. Paid
instances remove it.

**Sessions last a day, then end.** The access token lives in `localStorage`
(`lib/api.ts:62`) and is valid for 24 hours. Silent refresh uses an HttpOnly
cookie set `SameSite=Lax` (`app/api/routers/auth.py:34`), which browsers withhold
from cross-site requests — and the frontend and API are on different sites here.
Logging in again is the workaround; hosting both behind one domain, or
`SameSite=None`, is the fix.

**Recordings do not survive a redeploy.** The container filesystem is ephemeral
and no object storage is configured.

**Uploads appear to work and never finish.** With no Celery worker the job row is
created and stays at `queued` 0%. The API is healthy and nothing logs an error.
This is the same silent failure a worker started without
`-Q default,ingest,llm,graph` produces locally.

**Everyone edits the same account.** Two people practising at once share one EXP
total and one review schedule, and will overwrite each other's progress.

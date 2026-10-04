# Demo deployment — Koyeb + Vercel + Supabase + Upstash

A public deployment of ScaleUp for showing the practice loop to people. Free
managed services and a frontend: no cloud provider account, no OAuth consent
screen, no object storage, no credential obtained from a third party.

This is deliberately **not** the production shape. `docs/deployment.md` describes
that one — Cloud Run, GCS, Resend, Google OAuth, and `DEPLOYED=true` enforcing
all of it. Read that document when the app needs real user accounts. Read this
one when the goal is a URL someone can open.

The distinction is one tier. The API boots in **hosted mode** here: Koyeb sets
`KOYEB_APP_NAME`, which the platform detector in `app/domain/hosting.py`
recognises, so the startup validator arms itself and refuses the development
security defaults — the placeholder JWT secret, dev-login, unsigned webhooks, a
loopback CORS origin. The env block below already sets what it demands. Hosted
mode does NOT demand the deployed-tier integrations (email, OAuth, GCS), so
every one of those stays on the deterministic fallback the whole system is
built and tested against.

```text
Vercel                      Koyeb
┌──────────────┐            ┌─────────────────────┐
│ Next.js      │ ─ HTTPS ─► │ FastAPI web service │
│ (frontend/)  │ ─  WSS  ─► │ (backend/)          │
└──────────────┘            └──────────┬──────────┘
                                       ├── Supabase Postgres (pooler)
                                       └── Upstash Redis
```

Names used throughout. Substitute your own consistently — they appear in two
settings that reference each other:

| | Name | URL |
|---|---|---|
| Koyeb web service | `scaleup-api` | `https://scaleup-api-<org>.koyeb.app` |
| Vercel project | `scaleup` | `https://scaleup.vercel.app` |

Choose both before creating anything. The API needs the frontend's origin for
CORS and the frontend needs the API's URL compiled into its bundle, so deciding
the names up front turns a two-pass setup into one.

## What this deployment does and does not do

Works:

- The full practice loop on the six seeded courses — choose a skill, record a
  take, get scored on pitch, rhythm, dynamics and technique, earn EXP, watch the
  tree unlock.
- The live coach. Koyeb web services carry WebSockets, so `WS
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
| Password-reset email | With `EMAIL_PROVIDER=fake` the reset link is written to the API's log stream — Koyeb logs, visible to the Koyeb account owner — so a reset is an operator action, not self-service. Set `EMAIL_PROVIDER=resend` + `RESEND_API_KEY` to send real mail. |

**Sign-in is per account, not a shared one.** `DEV_AUTH_ENABLED=false` means the
no-password dev-login route does not exist at all. Visitors register real
accounts through the password form, or sign in as the seeded
`dev@example.com` / `devpassword123` — each person's courses, EXP, and practice
history are their own. The hosted tier is what makes this safe to expose: with
a generated `JWT_SECRET`, a forged token is not possible, and dev-login is
simply absent.

The seeded account is a **public demo account**: its password is committed in
this repository, so anyone can sign in as it and alter its courses and
progress. Treat it as a shared scratch account for looking around, and register
a real account for any progress you care about.

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

## 1. Postgres — Supabase

Supabase dashboard → **New project**. Any region; keep the Koyeb service in the
nearest one (Frankfurt or Washington DC).

Supabase exposes several connection strings under **Connect**. Use the
**Session-mode pooler, port 5432** — it looks like
`postgresql://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres`.
Two parts of this are not preferences:

- **Not the transaction-mode pooler (port 6543).** asyncpg uses named prepared
  statements, which transaction-mode pooling breaks — the API fails with
  `prepared statement "__asyncpg_stmt_N__" does not exist` on its second query.
- **Not the direct host.** Supabase's direct `db.<ref>.supabase.co` address is
  IPv6-only on new projects, and Koyeb's free instances have no IPv6 egress.
  The pooler is IPv4.

This application needs **two** URLs derived from that pooler string, each
naming its driver explicitly:

```
Supabase gives you:   postgresql://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
                                   ▲
DATABASE_URL:         postgresql+asyncpg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
SYNC_DATABASE_URL:    postgresql+psycopg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Both point at the same database. `DATABASE_URL` serves the API through
SQLAlchemy's async engine; `SYNC_DATABASE_URL` serves Alembic, which reads it
directly (`alembic/env.py:20`). Supabase requires TLS on the pooler, which both
drivers negotiate by default — no query parameters needed.

Omitting a driver prefix fails at boot with a SQLAlchemy dialect error that does
not mention the missing prefix. If the API will not start, check this first.

## 2. Redis — Upstash

Upstash console → **Create Database**. Free tier is 256 MB and 500K
commands/month — ample without a worker. Take the TLS URL (`rediss://`, port
6379 by default) and append a database number:

```
CELERY_BROKER_URL=rediss://default:PASSWORD@<host>.upstash.io:6379/0
CELERY_RESULT_BACKEND=rediss://default:PASSWORD@<host>.upstash.io:6379/0
```

Both on database 0. Nothing consumes the queue in this deployment, so broker
and backend never collide — and if a Celery worker is ever attached, its
polling alone would eat most of the free command budget, which is worth knowing
before reaching for it.

Redis is still worth attaching even with no worker: `/api/health/ready` probes
it, and the live coach uses it for the cross-instance session claim — which
degrades to a warning when Redis is unreachable, so a missing instance is
survivable rather than fatal.

## 3. The API — Koyeb

Koyeb console → **Create Service** → connect this repository (or push the image
from `backend/Dockerfile` to a registry and deploy it — the Git path builds the
same thing).

| Field | Value |
|---|---|
| Name | `scaleup-api` |
| Builder | **Dockerfile** |
| Dockerfile | `backend/Dockerfile` |
| Working directory | `backend` |
| Instance type | **Free** (512 MB / 0.1 vCPU, one per org) |
| Region | Frankfurt or Washington DC — same one as Supabase |
| Port | `8080` |
| Health check path | `/api/health/live` |
| Scaling | to zero after ~1 h idle (see cold starts below) |

`backend/Dockerfile` needs no changes. It reads `PORT`, which Koyeb supplies,
and it already copies `alembic.ini` and `alembic/`, so the same image runs
migrations in step 4.

**Use `/api/health/live`, not `/api/health/ready`.** `/live` returns
`{"ok": true}` and touches nothing. Readiness deliberately probes all four
datastores, and Neo4j and Chroma are absent here — so pointing the health check
at `/ready` produces a service that is permanently marked unhealthy and
restarts forever, with logs that look like a crash loop rather than a
misconfigured probe.

Environment variables. Paste the two database URLs and the two Redis URLs from
steps 1 and 2; generate the JWT secret; the last three are literal:

```
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
SYNC_DATABASE_URL=postgresql+psycopg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
CELERY_BROKER_URL=rediss://default:PASSWORD@<host>.upstash.io:6379/0
CELERY_RESULT_BACKEND=rediss://default:PASSWORD@<host>.upstash.io:6379/0
JWT_SECRET=<output of: python -c "import secrets;print(secrets.token_urlsafe(48))">
DEV_AUTH_ENABLED=false
CORS_ORIGIN_REGEX=https://scaleup\.vercel\.app
```

The last three are the hosted tier doing its job. Koyeb sets `KOYEB_APP_NAME`,
so `is_hosted` is true and the API **refuses to boot** without them — the
refusal names the signal, e.g. `refusing to start (KOYEB_APP_NAME (Koyeb)):
JWT_SECRET is still the committed placeholder`. That refusal is the check
working, not a misconfiguration to work around.

`CORS_ORIGIN_REGEX` is a regular expression, so the dots in the hostname are
escaped — an unescaped `.` matches any character and quietly widens the
allowlist.

Everything else keeps its default, and every default is a working fallback:

| Setting | Default | What that means here |
|---|---|---|
| `LLM_PROVIDER` | `fake` | Coaching text is deterministic. Scores are unaffected — a model never touches a number. Set to `gemini` with a `GEMINI_API_KEY` for model-written questions, grading and coaching; an overloaded model falls back to a cheaper one and then to the deterministic floor, so a busy free tier degrades the wording rather than failing the request. |
| `EMBEDDING_PROVIDER` | `fake` | No embedding spend. Only retrieval paths care. |
| `VOICE_PROVIDER` | `fake` | No spoken audio; `spoken_text` still returned. |
| `EMAIL_PROVIDER` | `fake` | Password reset logs a link instead of sending one — see the "does not work" table above. |
| `STORAGE_BACKEND` | `local` | Ephemeral container disk. |
| `WEBHOOK_SECRET` | empty | Inbound webhooks return 503 "not configured" rather than accepting unsigned calls (`app/api/routers/webhooks.py:64`). |
| `FRONTEND_URL` | localhost | Used only for password-reset links and OAuth redirect safety, neither of which exists here. |
| `HOSTED` | `false` | Already armed by `KOYEB_APP_NAME`; the flag exists for platforms the detector does not recognise. |
| `DEPLOYED` | `false` | The production tier stays off. Setting it here fails to boot, by design — it demands email, OAuth, and GCS. |

## 4. Migrate and seed

Once, after the service first deploys. Koyeb's free tier has no shell, so run
them **from your own machine** against the Supabase session-pooler URLs:

```bash
export SYNC_DATABASE_URL='postgresql+psycopg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres'
export DATABASE_URL='postgresql+asyncpg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres'
cd backend
alembic upgrade head
python -m app.seed
```

Run them in that order and never on process start — migrating at startup is how
a database gets corrupted when two instances boot concurrently.

`alembic upgrade head` should print a chain of `Running upgrade …` lines and
exit silently. `python -m app.seed` prints what it creates.

**The seed is not optional.** It creates:

- the user `dev@example.com` / `devpassword123` — a public demo account; its password is committed in this repository, so it is a shared scratch account, not private storage
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
NEXT_PUBLIC_API_BASE_URL=https://scaleup-api-<org>.koyeb.app
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
| `DATABASE_URL` | `scaleup-api` | Supabase session-pooler URL, `postgresql+asyncpg://` |
| `SYNC_DATABASE_URL` | `scaleup-api` | same database, `postgresql+psycopg://` |
| `CELERY_BROKER_URL` | `scaleup-api` | Upstash `rediss://` URL, database 0 |
| `CELERY_RESULT_BACKEND` | `scaleup-api` | Upstash `rediss://` URL, database 0 |
| `JWT_SECRET` | `scaleup-api` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `DEV_AUTH_ENABLED` | `scaleup-api` | `false` — real accounts only |
| `CORS_ORIGIN_REGEX` | `scaleup-api` | `https://scaleup\.vercel\.app` |
| `NEXT_PUBLIC_API_BASE_URL` | Vercel | `https://scaleup-api-<org>.koyeb.app` |

Eight values. Four are pasted from Supabase and Upstash, one is generated,
three are typed literally.

## Verifying

Work down the list; each step depends on the one above it.

**1. The API is up.**
```
GET https://scaleup-api-<org>.koyeb.app/api/health/live   →  {"ok": true}
```

**2. Every integration is on its fallback.**
```
GET https://scaleup-api-<org>.koyeb.app/api/health/providers
```
Reports presence, never secret values, so it is safe to read on a shared screen.
It also reports `hosted: true` and `hosting_signal: "KOYEB_APP_NAME (Koyeb)"` —
confirmation the hosted tier armed itself.

**3. Readiness is partially red, and that is expected.**
```
GET https://scaleup-api-<org>.koyeb.app/api/health/ready
```
Postgres and Redis healthy; Neo4j and Chroma down. This is why the health check
in step 3 points at `/live`.

**4. The interactive docs load.** `https://scaleup-api-<org>.koyeb.app/docs` —
the OpenAPI page, titled *ScaleUp API*.

**5. The landing page renders.** Open `https://scaleup.vercel.app`. It renders
with no session and no backend call, so it works even while the API is cold.

**6. Sign in.** Register through the password form, or use the shared demo
account `dev@example.com` / `devpassword123` — its password is public, so use
it only to look around. Six courses appear. If the courses list
is empty, step 4 did not run.

**7. Record a take.** Open a course, choose a skill, play the exercise. A score
comes back with EXP, and the node's state changes on the tree.

**8. The live coach connects.** Start a live coach take; cues stream over the
WebSocket. This is the step that fails on hosts without WebSocket support.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `prepared statement "__asyncpg_stmt_N__" does not exist` | On the transaction-mode pooler (port 6543). Switch `DATABASE_URL`/`SYNC_DATABASE_URL` to the session-mode pooler, port 5432. |
| Connection to the database host times out from Koyeb | Pointed at the direct `db.<ref>.supabase.co` host — it is IPv6-only and free Koyeb instances cannot reach it. Use the pooler. |
| `refusing to start (KOYEB_APP_NAME (Koyeb)): JWT_SECRET…` | The hosted tier is armed and a security default is still set. Set `JWT_SECRET`, `DEV_AUTH_ENABLED=false`, `CORS_ORIGIN_REGEX`. |
| Service restarts forever, logs look like a crash loop | Health check path is `/api/health/ready`. Change it to `/live`. |
| `sqlalchemy.exc.NoSuchModuleError` or a dialect error at boot | A driver prefix is missing from `DATABASE_URL` or `SYNC_DATABASE_URL`. |
| Browser console shows CORS errors, Koyeb logs show nothing | `CORS_ORIGIN_REGEX` does not match the Vercel origin. Check the escaped dots and the `https://`. |
| Frontend loads, every API call fails | `NEXT_PUBLIC_API_BASE_URL` wrong or missing. It is compiled in — redeploy, do not restart. |
| Live coach never connects, everything else works | `NEXT_PUBLIC_API_BASE_URL` is relative or has a trailing slash. |
| Signed in, but no courses | The seed did not run. Re-run `python -m app.seed`. |
| First request after an idle spell hangs for a few seconds | Free-instance scale-to-zero cold start (1–5 s). Not an error. |
| An upload sits at 0% forever | No Celery worker. Expected; see below. |
| Every drill answers 500, the browser says only "Failed to fetch" | A Gemini role whose model is overloaded. Roles carry a fallback model and the deterministic floor beneath it, so this should no longer happen; if it does, `GET /api/health/providers` names the lanes and `llm_calls` names the model that ran. |

## Alternatives considered

| Platform | Verdict |
|---|---|
| Render | Works — same Docker path, same env block, same shape. Reliability on the free tier has been an issue for this project; kept as the fallback host. |
| Fly.io | No free tier for new accounts since October 2024. |
| Hugging Face Docker Spaces | Now require a paid plan. |
| Railway | Trial credit only, then paid. |
| Cloud Run | Kept as the DEPLOYED=true production shape (`docs/deployment.md`); overkill for a demo. |

## Known rough edges

**Cold starts.** Free Koyeb instances scale to zero after about an hour of
inactivity and take 1–5 s to answer the first request. The frontend surfaces
this as a brief hang, not an error. If you are demoing live, open the URL
beforehand.

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

# Demo deployment — Render + Vercel

A public, shared-account deployment for showing the practice loop to people.
Three managed services and a frontend: no cloud provider account, no OAuth
consent screen, no object storage.

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
/api/auth/dev-login`, which issues a token for the seeded `dev@example.com` with
no password. Anyone who reaches the URL is that user, and every visitor shares
one set of courses, one EXP total, and one practice history. That is the intent
of this deployment; it is also its entire access-control model.

`JWT_SECRET` is left at the committed placeholder in this configuration, so
tokens are forgeable by anyone who reads the repository. With a single shared
account holding nothing private this changes little, but it is the reason this
shape must not be pointed at real users: the moment a second real account
exists, that account is forgeable too. Setting `JWT_SECRET` to the output of
`python -c "import secrets;print(secrets.token_urlsafe(48))"` closes it and
costs nothing.

## Before starting

Pick both service names first. Render serves at `https://<service>.onrender.com`
and Vercel at `https://<project>.vercel.app`, so choosing the names up front
breaks the circular dependency — the API needs the frontend's origin for CORS,
and the frontend needs the API's URL at build time.

Verify the production frontend build locally, with the dev server stopped:

```powershell
cd frontend
npm run build
```

`npm run build` and `npm run dev` share `frontend/.next`, and building while the
dev server is live corrupts the chunks it is serving. The failure presents as
application code — a missing vendor chunk, or a page that renders but never
hydrates.

## 1. Postgres

Create a Render Postgres instance and copy its connection string.

Render supplies `postgresql://…`. This application needs two URLs derived from
it, each naming its driver explicitly:

```
DATABASE_URL=postgresql+asyncpg://…        # the API, via SQLAlchemy async
SYNC_DATABASE_URL=postgresql+psycopg://…   # Alembic and the Celery worker
```

Both point at the same database. Omitting the driver prefix fails at boot with a
dialect error that does not mention the missing prefix.

Free Render Postgres instances are deleted after a limited window. Check the
current terms before relying on one for anything you would mind rebuilding.

## 2. Redis

Create a Render Key Value instance:

```
CELERY_BROKER_URL=redis://…/0
CELERY_RESULT_BACKEND=redis://…/1
```

Nothing consumes the queue in this deployment. Redis is still worth attaching:
`/api/health/ready` probes it, and the live coach uses it for the cross-instance
session claim — which degrades to a warning when Redis is unreachable, so a
missing instance is survivable rather than fatal.

## 3. The API

A Render Web Service from this repository.

- Runtime: Docker
- Root directory: `backend`
- Dockerfile: `backend/Dockerfile`
- Health check path: **`/api/health/live`**

The Dockerfile needs no changes. It reads `PORT`, which Render supplies, and it
already copies `alembic.ini` and `alembic/`, so the same image runs migrations.

Use `/api/health/live`, not `/api/health/ready`. Readiness touches all four
datastores, and Neo4j and Chroma are absent here — pointing Render's health
check at it produces a service marked unhealthy that restarts forever.

Environment:

```
DATABASE_URL=postgresql+asyncpg://…
SYNC_DATABASE_URL=postgresql+psycopg://…
CELERY_BROKER_URL=redis://…/0
CELERY_RESULT_BACKEND=redis://…/1
DEV_AUTH_ENABLED=true
CORS_ORIGIN_REGEX=https://<project>\.vercel\.app
```

`CORS_ORIGIN_REGEX` is a regular expression, so the dots in the hostname are
escaped. Its default permits loopback origins only, which rejects every request
from the deployed frontend.

Everything else keeps its default. `LLM_PROVIDER`, `EMBEDDING_PROVIDER`,
`VOICE_PROVIDER` and `EMAIL_PROVIDER` stay `fake`; `STORAGE_BACKEND` stays
`local`; `WEBHOOK_SECRET` stays empty, which closes the inbound webhook
endpoints with a 503 rather than leaving them unsigned. `FRONTEND_URL` is used
only for password-reset links and OAuth redirect safety, neither of which exists
here.

## 4. Migrate and seed

Once, from the Render shell or a one-off job, never on process start:

```bash
alembic upgrade head
python -m app.seed
```

Migrating on startup is how a database gets corrupted when two instances boot
concurrently.

The seed is not optional. It creates `dev@example.com` / `devpassword123`, the
two ready-made courses and four internal ones — six instruments in total, each
with a score-backed exercise. Without it the API is healthy and the app is
empty. The seed is idempotent for structure and deliberately leaves existing EXP
and mastery alone, so it is safe to re-run.

## 5. The frontend

A Vercel project from this repository, root directory `frontend`.

```
NEXT_PUBLIC_API_BASE_URL=https://<service>.onrender.com
```

This value is inlined into the browser bundle at build time rather than read at
runtime, so changing it requires a rebuild. It must be absolute:
`lib/coachSocket.ts` resolves the WebSocket endpoint with `new URL(path,
BASE_URL)`, which throws on a relative base.

`next.config.ts` declares `output: "standalone"`, which exists for self-hosting a
Node server and is redundant on Vercel.

## Environment reference

| Variable | Where | Value |
|---|---|---|
| `DATABASE_URL` | Render API | Postgres URL, `postgresql+asyncpg://` |
| `SYNC_DATABASE_URL` | Render API | same database, `postgresql+psycopg://` |
| `CELERY_BROKER_URL` | Render API | Key Value URL, database 0 |
| `CELERY_RESULT_BACKEND` | Render API | Key Value URL, database 1 |
| `DEV_AUTH_ENABLED` | Render API | `true` — the shared-account switch |
| `CORS_ORIGIN_REGEX` | Render API | escaped Vercel origin |
| `NEXT_PUBLIC_API_BASE_URL` | Vercel | absolute Render API URL |

Seven values, none of them a credential obtained from a third party.

## Verifying

1. `GET https://<service>.onrender.com/api/health/live` returns ok.
2. `GET /api/health/providers` reports every integration on its fallback. This
   endpoint reports presence, never secret values, and is safe to read aloud.
3. Open the Vercel URL. The landing page renders without a session.
4. Sign in through dev-login. Six courses appear.
5. Open a course, choose a skill, record a take. A score comes back with EXP and
   the node's state changes on the tree.
6. Start a live coach take. Cues stream over the WebSocket.

## Known rough edges

**Cold starts.** Free Render services spin down after inactivity and take tens of
seconds to answer the first request. The frontend surfaces this as a hung load,
not as an error. Paid instances remove it.

**Sessions last a day, then end.** The access token lives in `localStorage` and
is valid for 24 hours. Silent refresh uses an HttpOnly cookie set `SameSite=Lax`
(`app/api/routers/auth.py:34`), which browsers withhold from cross-site
requests — and the frontend and API are on different sites here. Logging in
again is the workaround; hosting both behind one domain, or `SameSite=None`, is
the fix.

**Recordings do not survive a redeploy.** The container filesystem is ephemeral
and no object storage is configured.

**Uploads appear to work and never finish.** With no Celery worker the job row is
created and stays at `queued` 0%. The API is healthy and nothing logs an error.
This is the same silent failure a worker started without
`-Q default,ingest,llm,graph` produces locally.

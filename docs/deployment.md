# Managed-cloud deployment

For a shared-account demo deployment with no third-party accounts, see
`docs/deployment-render.md`. This document is the production shape: real
user accounts, durable storage, and `DEPLOYED=true` enforcing both.

The repository now has production images for the FastAPI API, the Celery worker
(image override), and the Next.js frontend. The intended managed-cloud shape is:

```text
Next.js container (Cloud Run)
        │ HTTPS + CORS
        ▼
FastAPI container (Cloud Run service)
        │
        ├── PostgreSQL (managed, reachable from the service)
        ├── Redis (managed broker/result backend)
        ├── Neo4j (managed or private service)
        └── Chroma (managed or private service)

Celery worker container (Cloud Run worker pool or another long-running managed
container runtime) ────────────────┘
```

This is packaging and an operations seam, not an automatic deployment. No
credentials belong in this repository or in an image.

## Images

Build from the repository root with Artifact Registry configured:

```bash
export PROJECT_ID="your-gcp-project"
export REGION="us-central1"
export REPOSITORY="learn-anything"

gcloud artifacts repositories create "$REPOSITORY" \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT_ID"

gcloud builds submit backend \
  --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/backend:latest"

# The API URL is embedded into the browser bundle at build time.
gcloud builds submit frontend \
  --config=- <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - --build-arg
      - NEXT_PUBLIC_API_BASE_URL=https://api.example.com
      - -t
      - $REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/frontend:latest
      - .
images:
  - $REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/frontend:latest
EOF
```

The backend image is reusable for both commands:

```bash
# API default command
docker run --rm -p 8080:8080 backend-image

# Worker command; the worker must run in a long-lived worker runtime.
docker run --rm backend-image \
  celery -A app.tasks.celery_app worker --loglevel=INFO \
  -Q default,ingest,llm,graph
```

## Required production prerequisites

Before setting `DEPLOYED=true`, provide all of the following through the cloud
runtime's secret/configuration manager:

- A random `JWT_SECRET`; never use the committed placeholder.
- `REFRESH_TOKEN_TTL_DAYS` for rotating HttpOnly auth sessions (the default is
  30 days). The API and frontend must use HTTPS in deployment so the refresh
  cookie is marked Secure.
- `DATABASE_URL` and `SYNC_DATABASE_URL` for the same managed PostgreSQL
  database. Run migrations explicitly before starting the API.
- `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` for managed Redis.
- Reachable Neo4j and Chroma endpoints.
- A Google Cloud Storage bucket, with the runtime service account granted object
  read/write access to the configured prefix. The application uses Application
  Default Credentials/Workload Identity; do not ship a service-account key.
- `STORAGE_BACKEND=gcs`, `GCS_BUCKET`, and optionally `GCS_PREFIX`.
- Real LLM/embedding credentials if using non-fake providers.
- `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, and a verified `EMAIL_FROM` sender.
- `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`.
- `FRONTEND_URL` set to the public HTTPS frontend origin.
- `GOOGLE_OAUTH_REDIRECT_URI` set to the public API URL plus
  `/api/auth/google/callback`.
- `CORS_ORIGIN_REGEX` set to the frontend origin, for example
  `https://app\\.example\\.com`.
- `DEPLOYED=true`, `DEV_AUTH_ENABLED=false`, and
  `URL_FETCH_ALLOW_PRIVATE_HOSTS=false`.

Google Cloud OAuth must allow the exact redirect URI configured above. Resend
must have a verified sending domain. These are provider-console setup steps and
must not be replaced with local defaults in the image.

## Migration job

Migrations are never run on API startup. Run the migration image as a one-off
managed job using the same database environment as the API. The exact secret
flags depend on the chosen Secret Manager setup; the shape is:

```bash
gcloud run jobs deploy learn-anything-migrate \
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/backend:latest" \
  --region "$REGION" \
  --command alembic \
  --args upgrade,head \
  --set-env-vars DEPLOYED=false

gcloud run jobs execute learn-anything-migrate \
  --region "$REGION" \
  --wait
```

Attach the database URL and any required network connector/secrets to that job
before execution. Verify the migration result with `alembic current` from a
controlled operator environment.

## API service

Deploy the backend as an HTTP Cloud Run service. Cloud Run supplies `PORT`; the
image listens on `0.0.0.0` and exposes `/api/health/live` for liveness. Keep at
least one warm instance while the application is using a long-lived database
pool, and set request timeout high enough for the bounded URL-ingest endpoint.

The `/api/health/ready` endpoint checks PostgreSQL, Redis, Neo4j, and Chroma and
is useful for operations, but it should not be used as the only liveness probe.

## Worker runtime

Celery is a pull-based, long-running process. The current managed-cloud target
is a **Cloud Run Worker Pool**, which is designed for continuous background work
and has no HTTP endpoint. Worker Pools do not autoscale and are currently marked
pre-GA by Google, so size the instance count deliberately and monitor queue
latency. If that launch status is not acceptable for production, use another
managed runtime with the same long-lived process semantics.

The repository includes `deploy/cloud-run/worker-pool.yaml` as a secret-free
starting point. Replace its image placeholder, then configure the same database,
Redis, GCS, LLM, and auth secrets as the API. Deploy it with:

```bash
gcloud run worker-pools replace deploy/cloud-run/worker-pool.yaml \
  --region "$REGION"
```

The worker command is:

```text
celery -A app.tasks.celery_app worker --loglevel=INFO -Q default,ingest,llm,graph
```

Do not omit the queue list. A worker consuming only `default` leaves ingest work
queued indefinitely. The API and worker must use identical `DATABASE_URL`,
`SYNC_DATABASE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, and
`STORAGE_BACKEND`/`GCS_BUCKET` values.

## Frontend service

Deploy the frontend image as a separate Cloud Run HTTP service. Set
`NEXT_PUBLIC_API_BASE_URL` during the image build to the stable API HTTPS origin;
changing it at container runtime does not update the already-bundled browser
code. Point `FRONTEND_URL` and the backend CORS regex at this same origin.

## Durable source storage

The ingestion path now supports Google Cloud Storage without changing the
content-hash/idempotency contract. Set `STORAGE_BACKEND=gcs` for both the API
and Celery worker; `storage_path` values become `gs://...` object identifiers.
The worker downloads a source into its ephemeral filesystem only when a parser
stage needs a filesystem path, and reuses a local cache for later stages.

For local development and offline tests, keep `STORAGE_BACKEND=local`; bytes are
stored under `UPLOAD_DIR` exactly as before. Never mix `local` and `gcs` between
the API and worker: a local API upload produces a path the cloud worker cannot
read, while a GCS API upload is the portable choice for every runtime.

The remaining production prerequisites are the managed PostgreSQL, Redis,
Neo4j, and Chroma services plus provider credentials described above. GCS is
now the durable source-of-truth for uploaded textbook bytes; derived graph and
vector stores remain rebuildable projections.

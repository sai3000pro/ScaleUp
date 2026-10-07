# n8n orchestration

This directory versions the n8n side of the macro-orchestration seam. It is a
**template**, not the source of truth: every side effect runs through the
backend webhook endpoints (`/api/webhooks/v1/*`), and the backend owns
verification, dedupe, and the decay math. n8n owns scheduling and delivery.

The product never depends on n8n. The synchronous practice path works with n8n
stopped; the fake webhook runner (`scripts/smoke_webhooks.py`) exercises the
same endpoints without n8n at all.

## The three webhook contracts

| Event | Purpose | Backend endpoint |
|---|---|---|
| `session.completed` | Attempt finished → notify/badge/downstream | `POST /api/webhooks/v1/session.completed` |
| `feedback.requested` | Fetch (or synthesize) the examiner feedback | `POST /api/webhooks/v1/feedback.requested` |
| `daily-quests.refresh` | Nightly quest board computation | `POST /api/webhooks/v1/daily-quests.refresh` |
| `audio.retention.cleanup` | Purge raw recordings and synthesized audio cache after 30 days | `POST /api/webhooks/v1/audio.retention.cleanup` |

Full payloads, response shapes, and the dedupe semantics are in
`docs/api_contract.md` (Webhooks section).

## The outbound direction

The table above is n8n calling the app. The app can also call n8n, so a workflow
reacts to a finished take instead of polling for one:

```dotenv
N8N_WEBHOOK_URL=https://your-n8n/webhook/learn-any-instrument
```

Empty (the default) means nothing is emitted at all -- not "emitted to a stub".
No code path waits on it, and every delivery failure is swallowed, because an
automation platform being down must never cost a learner a take. Events are sent
only after the attempt is committed.

Events: `attempt.completed`, `node.unlocked`, `curriculum.published`. Each
carries `event_id`, `correlation_id`, `occurred_at`, and a `payload`.

Import `workflows/attempt-completed.json` for a receiver that verifies the
signature over the exact bytes and refuses anything that does not check out.

There is no retry queue on the app side. If you need delivery guarantees, put
them in n8n -- not in the practice path.

## Authentication

Every request signs the **exact request bytes** with HMAC-SHA256 keyed by
`WEBHOOK_SECRET`:

```
X-Webhook-Signature: sha256=<hex>
```

The signature covers the raw body — pretty-printing the JSON changes the
signature. In the shipped workflows the body is serialized once in a Code node
and the same string is both signed and sent. For HTTP Request nodes, use the
**Raw** body content type with `application/json`; do not parse the signed string
into a JSON object, because n8n's JSON mode reserializes it and can change the
signed bytes. The cleanup template is exported with `contentType: "raw"`,
`rawContentType: "application/json"`, and `body: "={{ $json.body }}"`.

Local development without n8n: set `DEV_WEBHOOKS_ENABLED=true` (accepts
unsigned requests) or export `WEBHOOK_SECRET` and sign manually:

```bash
python -c "import hmac,hashlib,sys; print('sha256='+hmac.new(b'<WEBHOOK_SECRET>', sys.stdin.buffer.read(), hashlib.sha256).hexdigest())" < payload.json
```

## Importing the workflow

1. In n8n, **Workflows → Import from File** → `workflows/nightly-quest-refresh.json`.
2. Edit the **Build payload** Code node:
   - `user_id`: the learner whose board to refresh (seeded dev user id is
     `00000000-0000-4000-8000-000000000001`).
   - `WEBHOOK_SECRET` (the `const SECRET = ...` line): match the backend env.
3. Edit the **Send webhook** HTTP Request node URL if the API is not on
   `http://localhost:8000`.
4. Set the Schedule Trigger to the desired local time (it ships as every 24h).
5. Activate the workflow.

The inbound `session.completed`, `feedback.requested`, `daily-quests.refresh`,
and `audio.retention.cleanup` requests follow the same signed envelope shape.
The cleanup workflow is `workflows/audio-retention-cleanup.json`; import it,
replace the webhook secret and API host, then activate it. Verify one execution
against the backend before enabling the schedule: a signature mismatch means
the n8n version or node export did not preserve the raw body as configured. It removes only recording bytes and generated
voice artifacts older than 30 days. Attempts, metrics, feedback, and progress
are retained indefinitely. Run daily; each scheduled run gets a fresh event ID
and retries reuse the same ID. The cleanup endpoint is callable manually with a
signed envelope too.

## Verification without n8n

```powershell
cd backend
# needs docker compose up -d, python -m app.seed, DEV_AUTH_ENABLED=true
.\.venv\Scripts\python.exe ..\scripts\smoke_webhooks.py
```

The smoke runner signs in as the dev user, completes a real piano attempt, then
fires all three webhooks and replays one to prove the ledger answers
`duplicate` without re-executing.

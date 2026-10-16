---
parent: high-level-design
prefix: OPS
---

# Operations

## Context and Design Philosophy

Operations covers what it takes to run the system: configuration and its validation, the
register of external services, health and readiness, object storage, the webhook boundary in
both directions, schema migrations, continuous integration, the seed, and the documents that
define the contracts between segments.

**Every external service is off by default, and every fallback is real.** The whole product
runs with no credentials, and the test suite runs that way. Turning a service on is
configuration, never code — if enabling a provider requires a source edit, that is a defect
in the seam rather than a task.

**The interesting state is not on or off, but asked-for-and-missing.** Selecting a provider
without supplying its credential is the failure that otherwise surfaces at the first call,
inside a background task, hours later. It is reported as a distinct state, before anything
starts.

**Configuration is validated at startup, not at first use.** Development defaults become
hard startup errors when the system is marked as deployed. Every one of those defaults fails
silently otherwise: a placeholder signing secret works perfectly right up until someone
reads it in the repository.

**Migrations are explicit and argue for themselves.** They never run on process start —
concurrent boot of the API and the worker is the most reliable way to corrupt a development
database. Several carry substantive rationale, including two that document their own
destructive downgrade or their own refusal to accept a generated diff.

**Idempotency is enforced by the schema.** Nine distinct unique constraints implement it,
rather than nine pieces of application code hoping. Where the caller supplies the key as a
primary key, a concurrent duplicate becomes a constraint violation rather than a race.

**Secrets are never rendered.** The health surface and the integration report name the
variables an operator must set and report only presence, so both are safe on a shared screen.

## Configuration

Settings are typed and centralised. Provider selection is by name with a deterministic
default; credentials are separate. A declarative integration table drives both the
command-line report and the health endpoint, so adding an integration is a row rather than a
change in three places.

### Hosting tiers

Development defaults become startup refusals in two tiers, driven by one requirements table
(`DEPLOYMENT_REQUIREMENTS` in `app/integrations.py`) that both the startup validator and the
pre-deploy report read.

**Hosted** arms the security defaults only: placeholder JWT, dev-login, unsigned webhooks,
the disabled SSRF check and a loopback CORS origin all refuse to boot. It is armed three
ways — a recognised platform variable (`KOYEB_APP_NAME`, `RENDER`, `FLY_APP_NAME`,
`RAILWAY_ENVIRONMENT`, `K_SERVICE`), `HOSTED=true` for a platform the detector does not
know, or `DEPLOYED=true`, which implies it. A `CI` or `GITHUB_ACTIONS` variable never arms
it: a runner carrying a platform variable is still a runner.

**Deployed** adds the durability and integration requirements on top: real email, Google
OAuth credentials, GCS storage and bucket, and a webhook secret.

## The webhook boundary

The automation platform is n8n, and it is the intended home for macro-orchestration —
nightly decay and quest refresh, reacting to a finished take, notifying on a published
curriculum. Business logic stays in services; n8n schedules and routes.

**Inbound**, callers are authenticated by a signed digest computed over the exact request
bytes — pretty-printing the payload changes the signature. Replays are answered from a ledger
keyed by the caller's event identifier, returning the stored result without re-executing.

**Outbound**, events are emitted only after the originating work is committed, and every
delivery failure is swallowed. There is deliberately no retry queue: delivery guarantees
belong in the automation platform, not in the practice path. An automation platform being
down must never cost a learner a take.

## Health

Liveness and readiness are distinct. Readiness probes each datastore with a bounded timeout,
and reports rather than raises — a health endpoint that throws when a dependency is down has
told the operator nothing.

## Storage

Source bytes are content-addressed with a local filesystem default and an object-store
backend. The local backend is correct on one machine and ephemeral on a managed host, which
is why the object store is required once deployed: the API and the worker must see the same
bytes.

## Continuous integration

Two jobs. A fast job runs linting, type checking and unit tests for both halves with no
datastores. An integration job runs the rest against real datastores. Keeping the fast job
free of datastores is what keeps it fast enough that people run it.

## Current state versus intent

**The schema and the models agree.** `alembic check` against a migrated database proposes
nothing; the integration suite runs it. The naming-convention drift that two earlier
revisions deferred is settled by one revision that moved the live schema to the models'
form (a column declared `unique=True, index=True` is one unique index, not a constraint
plus a non-unique index). Every constraint the code relies on -- including the partial
unique index that makes "copy to my account" idempotent -- is declared on its model.

**Binary content lives in object storage.** Practice recordings and synthesised speech are
written content-addressed through the storage backend and the row holds a `storage_path`;
the former binary columns are nullable and read only for rows that predate the move.

**Retention is a stated policy.** `retention_service.RETENTION_POLICY` names what is kept
for how long: raw audio for thirty days, then rows and objects go together (an object is
released only once no row still points at it, because content addressing lets two rows
share one); derived metrics for the life of their attempt, leaving only by owner deletion.

**Queue routing is tested.** Every registered task must resolve to a queue, and the queue
list in each operator document must equal the set routing produces.

**The client types descend from the published schema.** `scripts/export_openapi.py` writes
the server's OpenAPI document to `frontend/lib/openapi.json`; `npm run build:api-types`
generates `frontend/lib/apiSchema.ts` from it. The hand-named interfaces the UI reads by are
checked field-for-field against the generated schema, and the committed schema is checked
against the running application, so neither can go stale unnoticed.

**Documentation is held to the code.** A test fails when a document names a repository
file that does not exist. The catalogued disagreements -- the worker queue list, the
deployment platform named in comments, whether guitar chord scoring shipped, a moved
frontend module -- are reconciled.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Provider default | Deterministic fallbacks, no credentials | Require credentials to run | The product must be developable and testable with no keys and no spend. |
| Enabling a provider | Configuration only | Code change | A seam that needs an edit is not a seam. |
| Misconfiguration | A distinct reported state | Fail at first call | Otherwise it surfaces inside a background task, hours later. |
| Deployment defaults | Hard startup failure | Warn and continue | Every one of these defaults fails silently and dangerously. |
| Integration registry | One declarative table | Checks in each consumer | The report, the endpoint and the tests must not be able to disagree. |
| Credential reporting | Presence only, never value | Report a masked value | Presence answers the question; a value is a leak on a shared screen. |
| Migration timing | Explicit, never on start | Migrate at boot | Concurrent API and worker boot is the classic way to corrupt a database. |
| Idempotency | Schema constraints | Application checks | A constraint makes a concurrent duplicate an error instead of a race. |
| Inbound signature | Over exact request bytes | Over a canonical re-serialisation | Re-serialising invites two implementations that disagree. |
| Replay handling | Answered from a ledger with the stored result | Re-execute | Re-execution makes a retry a second side effect. |
| Outbound emission | After commit, failures swallowed, no retry queue | Emit in-transaction; retry locally | A platform outage must not cost a learner a take; delivery guarantees belong upstream. |
| Readiness probe | Reports, with a bounded timeout | Raises on failure | An endpoint that throws has told the operator nothing. |
| Containerisation | Datastores only; app on the host | Containerise everything | The working tree sits on a synced path where bind mounts do not propagate change events, which forces polling watchers and puts dependency trees inside a synced mount. |
| Fast CI job | No datastores | One job for everything | A slow check is a skipped check. |
| Naming-convention drift | Move the live schema to the models' form in one revision | Rename the models to match the first migrations | Both forms enforce the same rule; the models are what every future diff is generated from, so they are the side to keep. |
| Audio bytes | Object storage, `storage_path` on the row, old column nullable and read-only | Keep bytes in Postgres; migrate old rows in the revision | Audio grows the primary database without bound; the thirty-day window retires the pre-move rows on its own, so copying them would be wasted work. |
| Derived-metric retention | For the life of the attempt | A time window like audio | Metrics are the learner's progress and hold no media; a window would erase history the learner can still see. |
| Client types | Generated schema committed; hand-named interfaces proven to project it exactly | Replace `types.ts` with the generated module outright | The UI narrows bare wire strings to known-member unions and reads by product names; the generated module is the authority, the hand file a verified view of it. |
| Deployment target | Supabase Postgres + Upstash Redis + Vercel frontend + a long-lived container host (Koyeb free instance; Render as the alternative) | Cloud Run (kept as the DEPLOYED=true production shape); Vercel serverless for the API | The live coach is a WebSocket and needs a process that stays up; Render has been unreliable for this project. |

## Open Questions & Future Decisions

### Deferred

1. **Copying pre-move audio into object storage** rather than letting retention retire it;
   worth doing only if the retention window ever lengthens.
2. **Replacing `types.ts` with the generated module** once the UI no longer needs the
   known-member narrowing of wire strings.

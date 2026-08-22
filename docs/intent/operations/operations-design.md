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

**Deployment requirements are enforced twice, differently.** A hard startup check and an
advisory pre-deploy report overlap but do not agree. Two rule sets for one question means one
of them is wrong at any moment.

**A promised migration was never written.** One revision deferred a naming-convention drift
to "its own migration"; a later revision independently hit the same wall and also deferred.
Neither was followed. Every future generated diff will re-propose dropping a unique index and
rewriting four constraints — which makes this the one self-identified, twice-blocked, never
resolved structural debt in the system, and a latent blocker for any schema change.

**The chain has one degenerate merge**, whose second parent is already an ancestor. The head
is single and the chain is otherwise linear.

**Binary content lives in the primary database.** Practice recordings and synthesised speech
are stored as large binary columns. The deployment document discusses object storage for
document bytes and does not mention that audio grows the primary database.

**An invariant is documented but not declared.** A model comment describes a partial unique
index that does not appear in the model's table arguments; a schema elsewhere depends on that
index existing. It exists, if at all, only in a migration.

**Thirteen documentation-versus-code disagreements** are catalogued, including three
documents disagreeing on whether a scoring feature shipped and three disagreeing on the
deployment platform. Two documented request contracts are contradicted by the repository's
own scripts.

**The integration report advertises itself as a continuous-integration gate and is not
wired as one.**

**No test exercises real queue routing.** Background work runs eagerly under test, so the
routing configuration — and the operator instruction that depends on it — is untested by
construction. That instruction is now wrong: it names queues nothing routes to, which the
routing module's own comment describes as dead letterboxes.

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

## Open Questions & Future Decisions

### Deferred

1. **The naming-convention migration must be written** before any further schema change is
   safe to generate.
2. **Which deployment-requirement check is authoritative**, and how the two are reconciled.
3. **Should binary content move out of the primary database?** The object-store backend
   already exists.
4. **The deployment target is Render.** `docs/deployment.md` and the Cloud Run manifest
   describe a different platform and must be reconciled to it, or explicitly kept as a
   secondary target with the primary named.
5. **Should the integration report actually gate continuous integration**, as it advertises?
6. **Type generation for the wire contract.** The client type module is a hand-maintained
   mirror of the contract document, and the server already emits a machine-readable schema.
7. **No retention or deletion job exists** for recordings and derived metrics, though
   owner-deletion is implemented and the privacy position is stated.
8. **The declared partial unique index** should be declared in the model or removed from the
   comment.

## References

- `docs/api_contract.md` — the contract between the backend and the client
- `docs/integrations.md` — external services and their fallbacks
- `docs/deployment.md` — the deployment target, disputed
- `CLAUDE.md` — repository-wide engineering conventions

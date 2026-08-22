# Arrow: operations

Configuration and its validation, the integration register, health, object storage, the
webhook boundary, schema migrations, continuous integration, and the documented seam between
the halves of the system.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). The integration and webhook seams
are strong. Schema migration carries the system's one self-identified, twice-deferred
structural debt, and documentation disagrees with code in thirteen catalogued places.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/operations/operations-design.md`

### EARS
- `docs/intent/operations/operations-specs.md` (52 specs)

### Tests
- `backend/tests/unit/test_health.py`, `test_integrations.py`, `test_env_example.py`, `test_api_contract.py`, `test_no_continue.py`, `test_object_storage.py`
- `backend/tests/integration/test_webhooks.py`, `test_admin_reindex.py`

### Code
- `backend/app/services/health_service.py` — the provider and datastore report the health surface renders
- `scripts/check_arrow.py` — the structural coherence check CI runs
- `backend/app/config.py`, `backend/app/integrations.py`, `backend/app/main.py`
- `backend/app/services/webhook_service.py`, `n8n_service.py`, `object_storage.py`
- `backend/app/api/routers/health.py`, `webhooks.py`
- `backend/alembic/versions/` — 32 revisions
- `scripts/check_integrations.py`, `scripts/smoke_*.py`, `scripts/timewarp.py`
- `.github/workflows/ci.yml`, `docker-compose.yml`, `.env.example`
- `docs/api_contract.md`, `docs/integrations.md`, `docs/deployment.md`, `CLAUDE.md`

## Architecture

**Purpose:** Make the system runnable with nothing configured, make every external service a
row rather than a code path, and make a misconfiguration visible before it becomes a
three-in-the-morning failure.

**Key Components:**
1. `config.py` — typed settings; development defaults become hard startup errors when deployed.
2. `integrations.py` — one declarative register rendering both the report and the health endpoint.
3. `webhook_service.py` / `n8n_service.py` — signed inbound with a replay ledger; fire-and-forget outbound after commit.
4. `alembic/versions/` — explicit, never on start; single head.
5. `ci.yml` — a datastore-free fast job and a datastore-backed integration job.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Configuration | `OPS-CONFIG-001` – `007` | 5 | 1 | 1 |
| Integration register | `OPS-INTEG-001` – `008` | 6 | 0 | 2 |
| Health | `OPS-HEALTH-001` – `004` | 4 | 0 | 0 |
| Webhook boundary | `OPS-HOOK-001` – `010` | 9 | 1 | 0 |
| Object storage | `OPS-STORE-001` – `005` | 3 | 0 | 2 |
| Schema | `OPS-MIGRATE-001` – `007` | 5 | 0 | 2 |
| Continuous integration | `OPS-CI-001` – `006` | 5 | 0 | 1 |
| Documented seam | `OPS-CONTRACT-001` – `005` | 2 | 0 | 3 |

**Summary:** 39 of 52 implemented; 2 deliberate non-wants; 11 active gaps — the highest count
of any segment.

## Key Findings

1. **A promised migration was never written.** Revision `49db625e8d49` deferred an Alembic
   naming-convention drift to "a separate question with its own migration"; `f6a7b8c9d0e1`
   independently hit the same wall and also deferred. Neither followed. Every future
   `--autogenerate` will re-propose dropping `uq_courses_owner_copy` and rewriting four unique
   constraints. This is the system's only self-identified, twice-blocked, never-resolved
   structural debt, and a latent blocker for any schema change (`OPS-MIGRATE-006`).

2. **Deployment requirements are enforced twice, differently.** A hard startup check in
   `config.py` and an advisory report in `integrations.py` overlap but do not agree. Two rule
   sets for one question means one of them is wrong at any moment (`OPS-CONFIG-007`).

3. **Thirteen documentation-versus-code disagreements are catalogued**, including three
   documents disagreeing on whether guitar chord scoring shipped. The deployment target is
   decided — Render — so `docs/deployment.md` and the Cloud Run manifest are now the
   documents that must be reconciled rather than an open question. Two documented request contracts are contradicted
   by the repository's own smoke scripts (`OPS-CONTRACT-004`).

4. **A file cited by documentation and by live code does not exist.** `score.py` is imported
   at runtime by `backend/collapsed.py:21` and cited as real by
   `docs/archive/graph_extraction_contract.md:228` and `app/ingestion/toc.py:303`
   (`OPS-CONTRACT-005`).

5. **The operator instruction for the worker is now false.** `CLAUDE.md` states that tasks
   route to `ingest`, `llm` and `graph`, and that omitting them leaves ingests queued forever.
   `celery_app.py` routes exactly one queue, and its own comment says the `llm` and `graph`
   entries "named tasks that have never existed … so the queues were dead letterboxes and
   anyone debugging an idle one was chasing a phantom." The documented command still works;
   its stated reason does not (`OPS-CI-006`, and no test covers routing because tasks run
   eagerly under test).

6. **Binary content lives in the primary database.** Practice recordings and synthesised
   speech are large binary columns; `docs/deployment.md` discusses object storage only for
   document bytes (`OPS-STORE-004`).

7. **An invariant is documented but not declared.** `models/course.py:36-37` describes a
   partial unique index absent from the model's table arguments, which `schemas/social.py`
   depends on (`OPS-MIGRATE-007`).

8. **The integration seam is the segment's strongest property.** One declarative register
   drives the report, the endpoint and the tests, so they cannot disagree; a service selected
   without its credential is reported as misconfigured rather than failing at first call; and
   no surface ever renders a credential value.

## Work Required

### Must Fix
1. Write the naming-convention migration (`OPS-MIGRATE-006`). Until it lands, no generated
   schema diff is trustworthy.
2. Correct the worker-queue instruction in `CLAUDE.md`, or restore the routing it describes.
3. Restore or withdraw the missing `score.py` reference (`OPS-CONTRACT-005`).

### Should Fix
4. Define deployment requirements once (`OPS-CONFIG-007`).
5. Reconcile `docs/deployment.md` and `deploy/cloud-run/` to Render, the decided target (`OPS-CONTRACT-004`).
6. Declare the MediaPipe CDN hosts in the integration register (`OPS-INTEG-007`) — see
   `capture`.
7. Declare the partial unique index in the model (`OPS-MIGRATE-007`).

### Consider
8. Generate the client types from the published schema (`OPS-CONTRACT-003`).
9. Move recordings and synthesised audio out of the primary database (`OPS-STORE-004`).
10. Add a retention policy (`OPS-STORE-005`) — owner deletion exists; expiry does not.
11. Wire the integration report as an actual CI gate (`OPS-INTEG-008`).

# Operations — EARS Specs

Prefix: `OPS`. Facets: `CONFIG` (settings and validation), `INTEG` (the integration
register), `HEALTH` (liveness and readiness), `HOOK` (the webhook boundary),
`STORE` (object storage), `MIGRATE` (schema), `CI` (continuous integration),
`CONTRACT` (the documented seam).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Configuration

- [x] **OPS-CONFIG-001**: The system shall run with no external credentials configured.
- [x] **OPS-CONFIG-002**: The system shall select each provider by name, with a deterministic default.
- [x] **OPS-CONFIG-003**: When marked as deployed, the system shall refuse to start with a placeholder signing secret, with development sign-in enabled, with the deterministic mail provider, with local storage, without federated credentials, without a webhook secret, with the address check disabled, or with a loopback origin.
- [x] **OPS-CONFIG-004**: The system shall validate configuration at startup rather than at first use.
- [x] **OPS-CONFIG-005**: Every setting the system reads shall be documented in the example environment file.
- [D] **OPS-CONFIG-006**: Enabling an external service shall never require a source change.
- [ ] **OPS-CONFIG-007**: Deployment requirements shall be defined once, so the startup check and the pre-deployment report cannot disagree.

## Integration register

- [x] **OPS-INTEG-001**: The system shall describe every external service in one declarative register.
- [x] **OPS-INTEG-002**: The register shall render both the command-line report and the health endpoint, so they cannot diverge.
- [x] **OPS-INTEG-003**: The system shall report a service selected without its credential as misconfigured, distinctly from off and from live.
- [x] **OPS-INTEG-004**: The system shall report each service's fallback behaviour while it is off.
- [x] **OPS-INTEG-005**: The system shall name the variables an operator must set, and shall never report a credential's value.
- [x] **OPS-INTEG-006**: The report shall exit non-zero when any service is misconfigured.
- [x] **OPS-INTEG-007**: Every external host the product depends on at runtime shall appear in the register, including those reached from the browser.
- [ ] **OPS-INTEG-008**: The integration report shall gate continuous integration, as it advertises.

## Health

- [x] **OPS-HEALTH-001**: The system shall expose liveness independently of dependency health.
- [x] **OPS-HEALTH-002**: The system shall probe each datastore for readiness with a bounded timeout.
- [x] **OPS-HEALTH-003**: The readiness probe shall report a failing dependency rather than raising.
- [x] **OPS-HEALTH-004**: No health response shall contain a credential value.
- [x] **OPS-HEALTH-005**: The liveness response shall name the build it is serving, so which revision is live is observable rather than inferred from behaviour.

## The webhook boundary

- [x] **OPS-HOOK-001**: The system shall authenticate an inbound webhook by a signature computed over the exact request bytes.
- [x] **OPS-HOOK-002**: The system shall reject an inbound webhook whose signature does not verify.
- [x] **OPS-HOOK-003**: The system shall answer a replayed event from its ledger with the stored result, without re-executing it.
- [x] **OPS-HOOK-004**: The system shall refuse an unknown event type rather than routing it.
- [x] **OPS-HOOK-005**: Where no webhook secret is configured, inbound endpoints shall refuse rather than accept unsigned calls, unless development webhooks are explicitly enabled.
- [x] **OPS-HOOK-006**: The system shall emit an outbound event only after the originating work is committed.
- [x] **OPS-HOOK-007**: The system shall swallow every outbound delivery failure without affecting the originating work.
- [x] **OPS-HOOK-008**: Where no outbound endpoint is configured, the system shall emit nothing and no path shall wait on it.
- [x] **OPS-HOOK-009**: The system shall sign an outbound event with the shared secret when one is configured, and send it unsigned when none is.
- [D] **OPS-HOOK-010**: The system shall not implement a delivery retry queue in the practice path.

## Object storage

- [x] **OPS-STORE-001**: The system shall store source bytes content-addressed.
- [x] **OPS-STORE-002**: The system shall support a local filesystem backend and an object-store backend, selected by configuration.
- [x] **OPS-STORE-003**: When marked as deployed, the system shall require the object-store backend so that the API and the worker read the same bytes.
- [ ] **OPS-STORE-004**: Practice recordings and synthesised audio shall be stored outside the primary relational database.
- [ ] **OPS-STORE-005**: The system shall apply a retention policy to recordings and derived metrics.

## Schema

- [x] **OPS-MIGRATE-001**: Migrations shall be applied by explicit command and never on process start.
- [x] **OPS-MIGRATE-002**: The migration chain shall resolve to a single head.
- [x] **OPS-MIGRATE-003**: A migration that alters meaning rather than shape shall record its rationale.
- [x] **OPS-MIGRATE-004**: A column shall be nullable where its absence means inapplicable, and that meaning shall be recorded.
- [x] **OPS-MIGRATE-005**: Idempotency shall be enforced by database constraint rather than by application check alone.
- [ ] **OPS-MIGRATE-006**: A generated migration diff shall contain only intended changes, with no drift proposed by naming-convention mismatch.
- [ ] **OPS-MIGRATE-007**: Every constraint the models rely on shall be declared in the models, not only in a migration.

## Continuous integration

- [x] **OPS-CI-001**: The fast job shall run linting, type checking and unit tests for both halves with no datastores.
- [x] **OPS-CI-002**: The integration job shall run against real datastores.
- [x] **OPS-CI-003**: The suite shall pass with no external credentials configured.
- [x] **OPS-CI-004**: The system shall reject a loop-continuation statement in either language.
- [x] **OPS-CI-005**: The seed shall be idempotent for structure and shall not reset existing progress.
- [ ] **OPS-CI-006**: Queue routing shall be exercised by test rather than assumed.

## The documented seam

- [x] **OPS-CONTRACT-001**: The contract document and the client type module shall be changed together.
- [x] **OPS-CONTRACT-002**: A test shall assert that the client types match the documented contract.
- [ ] **OPS-CONTRACT-003**: The client types shall be generated from the server's published schema rather than maintained by hand.
- [ ] **OPS-CONTRACT-004**: Where documentation states a behaviour, the code shall implement it or the documentation shall be corrected.
- [ ] **OPS-CONTRACT-005**: A file referenced by documentation or by live code shall exist in the repository.

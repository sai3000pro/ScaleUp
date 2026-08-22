# Model Gateway — EARS Specs

Prefix: `LLM`. Facets: `ROLE` (addressing), `PROMPT` (versioning),
`BUDGET` (spending), `LEDGER` (recording), `FAKE` (the deterministic floor),
`EMBED` (embeddings).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Role addressing

- [x] **LLM-ROLE-001**: A caller shall request a model by role, never by provider or model name.
- [x] **LLM-ROLE-002**: The system shall resolve a role to its provider, model, prompt and schema through a single registry.
- [x] **LLM-ROLE-003**: The system shall support distinct providers and models for different roles simultaneously.
- [x] **LLM-ROLE-004**: Where a role declares a response schema, the system shall validate the response against it and shall retry on mismatch.
- [x] **LLM-ROLE-005**: The system shall expose streaming generation as a protocol distinct from structured generation.
- [D] **LLM-ROLE-006**: A caller shall not name a model identifier at its call site.

## Provider selection

- [x] **LLM-PROV-001**: The system shall select its language-model provider by configuration, and shall refuse to start on a provider name it does not implement rather than falling back silently.
- [x] **LLM-PROV-002**: Where a provider is selected without the credential it requires, the system shall refuse to start with a message naming both the missing setting and the deterministic alternative.
- [x] **LLM-PROV-003**: Each provider shall name its own model for every role, and no call shall be priced at a model identifier other than the one that served it.
- [x] **LLM-PROV-004**: At least one credentialed provider shall support streaming generation, so live coaching can be served by a model rather than only by the deterministic floor.
- [x] **LLM-PROV-005**: Where the selected provider cannot stream, the system shall report that the provider cannot stream, rather than reporting the call as failed.
- [ ] **LLM-PROV-006**: A streamed call shall be recorded against the token counts its provider reported, where the provider reports them.
- [x] **LLM-PROV-007**: The system shall accept a distinct provider credential per workload lane, so a quota exhausted by one lane does not stop the others.
- [x] **LLM-PROV-009**: Where a workload lane has no credential for the selected provider, that lane shall run on the deterministic provider rather than refusing, so a deployment can pay for one lane at a time.
- [x] **LLM-PROV-010**: Every recorded call shall name the provider that actually served it, including where a lane fell back to the deterministic provider.
- [x] **LLM-PROV-008**: A caller shall name neither a provider credential nor a workload lane; the lane shall be a property of the role.

## Prompt versioning

- [x] **LLM-PROMPT-001**: Prompts shall be stored as versioned files.
- [x] **LLM-PROMPT-002**: A change to a prompt shall be published as a new version file rather than editing an existing one.
- [x] **LLM-PROMPT-003**: Every recorded call shall carry its prompt identifier, prompt version, and prompt content hash.
- [ ] **LLM-PROMPT-004**: A prompt version no longer referenced by any role shall be identifiable as superseded from the prompt store itself.
- [x] **LLM-PROMPT-005**: A prompt shall interpolate its variables in the one syntax the renderer substitutes, and a prompt that does not shall be identifiable without calling a provider.

## Budget

- [x] **LLM-BUDGET-001**: The system shall enforce a spending ceiling scoped to a course rather than to a request.
- [x] **LLM-BUDGET-002**: The system shall check the ceiling before dispatching a call, not after.
- [x] **LLM-BUDGET-003**: When the ceiling is exhausted, the system shall refuse the call with a distinct, catchable condition.
- [x] **LLM-BUDGET-004**: The system shall report accumulated spend per course, broken down by role.
- [ ] **LLM-BUDGET-005**: When prompt rendering fails, the system shall refuse the call rather than proceeding without a budget check.

## Ledger

- [x] **LLM-LEDGER-001**: The system shall write exactly one ledger row per call, including calls that fail.
- [x] **LLM-LEDGER-002**: The system shall record a cancelled stream as cancelled, distinctly from success and from failure.
- [x] **LLM-LEDGER-003**: The system shall record a ledger row even when the caller abandons a stream mid-generation.
- [x] **LLM-LEDGER-004**: The system shall record token counts and estimated cost per call.
- [x] **LLM-LEDGER-005**: The system shall link a ledger row to the work that caused it.
- [ ] **LLM-LEDGER-006**: The system shall be able to compare outcomes across prompt versions from the recorded ledger.

## The deterministic floor

- [x] **LLM-FAKE-001**: The system shall select deterministic providers by default, requiring no credentials to run.
- [x] **LLM-FAKE-002**: The whole product shall be operable — ingestion, grading, feedback, coaching, curriculum compilation — with no provider credentials configured.
- [x] **LLM-FAKE-003**: The deterministic providers shall produce identical output for identical input.
- [x] **LLM-FAKE-004**: The deterministic providers shall satisfy the same response schemas as configured providers.
- [x] **LLM-FAKE-005**: The deterministic provider shall stream incrementally, so streaming consumers are exercised without credentials.
- [x] **LLM-FAKE-006**: The continuous integration suite shall run with no provider credentials configured.
- [D] **LLM-FAKE-007**: No test shall depend on a live provider except those explicitly marked as opt-in.
- [ ] **LLM-FAKE-008**: Where the deterministic provider parses a renderer's output format, that format shall be shared mechanically rather than restated on each side.

## Embeddings

- [x] **LLM-EMBED-001**: The system shall support an embedding provider selected independently of the generation provider.
- [x] **LLM-EMBED-002**: The deterministic embedding provider shall produce vectors whose similarity behaves directionally like a real provider's.
- [x] **LLM-EMBED-003**: The system shall record embedding spend in the same ledger as generation.
- [ ] **LLM-EMBED-004**: Every embedding provider shall return unit-normalised vectors, so that similarity thresholds carry the same meaning across providers.

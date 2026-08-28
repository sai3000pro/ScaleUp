---
parent: high-level-design
prefix: LLM
---

# Model Gateway

## Context and Design Philosophy

Every call to a language or embedding model in this system passes through one seam. That
seam maps a *role* to a provider and model, enforces a spending ceiling before the call,
records what happened after it, and guarantees a working answer when no provider is
configured at all.

**Callers name a role, never a model.** A caller asks for graph extraction, or examiner
feedback, or a live coaching cue. The mapping from role to provider, model and prompt lives
in one registry, so serving a high-volume extraction pass with a cheap model and a
once-per-ingest reduction with a strong one is a one-line change rather than a search
through call sites.

**The fake provider is the default, and it is a real implementation.** The entire product —
ingestion, grading, examiner feedback, coaching, curriculum compilation — runs with no API
keys and no network, and the test suite runs that way in CI. The deterministic providers are
exercised by the same tests as the live ones. This is not a demo mode; it is the floor the
product stands on.

**Prompts are versioned files, never edited in place.** A change to a prompt is a new
version file. Every call records the prompt's identifier, version and content hash, because
"did grading accuracy change after I edited the rubric?" is unanswerable retroactively
unless the hash was stored at the time.

**Budget is enforced before the call, and recorded after it.** The ceiling is per course
rather than per request, because one document ingest is many calls. Failures and cancelled
streams are written to the ledger too — those are precisely the rows worth having.

## Roles and the registry

`app/llm/registry.py` holds the role table. A role names its provider, its model, its prompt
identifier and version, and its response schema where one applies.

Structured responses are validated against a JSON schema at the tool-call layer, so a model
that returns a malformed object is retried rather than allowed to propagate a shape the
caller cannot use.

Streaming is a separate protocol from structured generation, so that adding token streaming
for live coaching does not weaken the schema guarantee that structured callers depend on.

## Providers

Three credentialed providers -- Anthropic, OpenAI and Gemini -- plus the deterministic one
that is the default. Selection is configuration; the factory in `app/llm/factory.py` is the
only place that reads it, and it refuses rather than falling back. An unimplemented provider
name and a selected provider with no credential are both configuration mistakes, and a
silent downgrade to the fake provider would hide a production deployment quietly running on
a word matcher.

Every provider names its **own** model for every role, in its own column of the role table,
and every one of those models is priced in the same table. Borrowing a sibling's column
would be cheaper and would make the cost endpoint quote one vendor's rates for another
vendor's calls -- in a table whose purpose is answering what an ingest costs.

### Availability

A model identifier is not a guarantee that the model will answer. Google's shared free
tier answers `503 UNAVAILABLE` on its stronger aliases for minutes at a time while the
cheaper alias beside it stays healthy, so a role that names one model has an availability
no better than that model's busiest hour.

The role table therefore names a **fallback model** per provider alongside the primary one,
and the answer to an overloaded or rate-limited primary is to re-attempt on the fallback
rather than to fail. The fallback is a real, priced, reachable model, and the ledger records
whichever one actually served -- a call that fell back is billed at the model that answered
it, not at the one the caller would have preferred.

Below the fallback is the deterministic provider, which is the floor the whole product
already runs on with no credentials at all. A provider outage therefore costs the learner
answer *quality*, never the feature: a drill still issues a question, a take is still
graded, an examiner still speaks. The ledger names the deterministic provider on those
rows, so a degraded answer is distinguishable from a paid one after the fact rather than
being invisible.

Two boundaries keep that from becoming the silent downgrade this segment otherwise refuses.
It is a **runtime** response to an outage, never a **startup** response to a missing
credential -- an unimplemented provider name and an absent key are still refusals, because
those are configuration mistakes that a fallback would hide forever. And it is recorded,
so "how much of last week ran on the word matcher?" is a query rather than a guess.

How long a call may wait before that ladder is walked is a property of the **lane**, not of
the provider, and it budgets the **whole call** rather than each attempt. Per-attempt, a role
with a fallback silently costs twice its stated deadline the moment both models are slow --
which is precisely when someone is waiting. So the primary gets a share of the lane's budget
and the fallback gets whatever is left; when too little is left for a second attempt to
finish, none is started, because the deterministic floor was available instantly the whole
time and reaching it sooner is the better answer. The three lanes differ by who is waiting: an ingest runs unattended inside a
Celery task and can afford to be patient; a learner watching a drill spinner cannot; a
learner mid-take has already started playing again. A single provider-wide timeout has to
be set for the most patient of the three, which is how an overloaded model turned a drill
into an eighty-second wait that still ended in the deterministic question -- the fallback
was correct and arrived far too late to matter.

Interactive lanes also decline the SDK's own retry, because retrying the same overloaded
alias doubles the wait to reach an answer the sibling model would have given immediately.
The fallback model *is* the retry, and it is a retry against something different.

Each role also declares a **workload lane** -- `ingest` for compiling a curriculum,
`tutor` for drilling, grading and feedback, `live` for the streaming coach -- and a
provider credential may be set per lane. Compiling a curriculum is bursty and can
exhaust a rate limit; when it does, a learner already mid-take should still hear
their coach. The lane lives on the role rather than at the call site, so a caller
names a role and nothing else, exactly as it names no model.

A lane with no credential runs on the deterministic provider rather than refusing.
A deployment rarely turns a paid provider on everywhere at once -- a key goes
against the work being tested, and the rest waits until it is worth spending on --
and refusing would make that choice all-or-nothing. This is the same floor the
whole product runs on with no keys configured, so the fallback is a supported state
rather than a degraded one. The ledger records the provider that actually served
each call, because a row naming the configured provider instead of the serving one
would make the cost record fiction.

Streaming is not uniform across them: Gemini implements it and the other two do not, so
selecting Gemini is what allows the live coach to speak from a model rather than from its
deterministic sentence. The gateway reports an unstreamable provider as exactly that, so the
absence reads as a capability the deployment lacks rather than as a failed call.

Gemini is reached through Google's OpenAI-compatible endpoint rather than the vendor SDK. It
speaks both things this application asks of a model -- a JSON object matching a supplied
schema, and a stream of prose -- through a package the project already depends on and error
types already mapped. Its schema is sent unmodified, without the strict-mode rewrite the
OpenAI path performs, because strict mode's rules are OpenAI's own and a compatibility layer
may reject the keys they imply; the guarantee remains schema validation plus one repair turn,
which is where it lives for every provider.

## The ledger

`llm_gateway.py` writes exactly one ledger row per call, in a `finally` block guarded
against double-recording, so a cancelled stream still records the tokens it burned. A
barge-in is recorded as cancelled rather than as success — recording it as success would
make "how often does the learner interrupt?" unanswerable.

`GET /api/courses/{id}/cost` reads these rows.

## Determinism

The fake providers are deterministic: the same input produces the same output, asserted by
test. Fake embeddings are hashed bag-of-words vectors, normalised to unit length, so that
similarity behaves directionally like the real thing and retrieval tests mean something.

## Current state versus intent

**The fake provider is the most tightly coupled component in the system.** It reverse-parses
the wire format of at least four renderers that live in other segments — the drill rubric
renderer, the ingestion fragment renderer, the skill-list renderer, and the passage
renderer. Two of those carry explicit "these must change together" comments. The coupling is
real, load-bearing, and enforced only by comment: no shared constant, no shared parser, no
test that fails when one side moves.

**An unstated invariant holds up similarity scoring.** `ingestion/extract.py:157` defines
`_cosine` as a bare dot product with no normalisation. It is correct only because every
embedding provider currently returns unit vectors. Nothing states that requirement — not a
type, not a docstring, not a test — so a provider that returns unnormalised vectors would
silently change what the concept-merge thresholds mean rather than fail.

**Budget enforcement can be skipped.** `_enforce_budget` returns without checking when
prompt rendering raises, so a rendering failure bypasses the ceiling rather than refusing
the call.

**Superseded prompts are retained with no marker.** Several prompt versions and schemas
remain in the tree with nothing indicating they are superseded; only the registry's silence
about them distinguishes live from dead. That is a deliberate consequence of never editing a
prompt in place, but it means the directory cannot be read without the registry beside it.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Call addressing | By role | By model name at the call site | Re-pointing a stage becomes one line instead of a search through call sites. |
| Default provider | Deterministic fake | Require a key to run | The product must be developable, testable and demonstrable with no keys and no spend. |
| Fake quality | A real implementation, same tests as live | A stub returning fixtures | A stub rots, and its failures only appear in production. |
| Prompt changes | New version file | Edit in place | Without the stored hash, no question about a past result is answerable. |
| Call recording | One row per call, including failures and cancellations | Record successes | The failures are the rows worth having. |
| Budget scope | Per course | Per request | One ingest is many calls; a per-request ceiling bounds nothing that matters. |
| Budget timing | Checked before the call | Reconciled afterwards | A ceiling enforced after the spend is not a ceiling. |
| Structured output | Schema-validated at the tool-call layer | Parse and hope; schema embedded in prompt text | Validation at the boundary lets the model retry on mismatch. |
| Streaming | A separate protocol | Extend the structured client | Structured callers must keep their schema guarantee. |
| Embedding vectors | Normalised by the fake provider | Return raw magnitudes | `[inferred]` — normalisation is implemented but not stated as a contract. It is what makes the dot-product similarity correct. Confirm and record as a provider requirement. |
| Provider selection | Configuration, refusing on an unknown name or a missing credential | Fall back to the deterministic provider | A silent downgrade means a deployment runs on a word matcher and nothing says so. |
| Per-provider models | Each provider names its own model per role, priced in the same table | Share one model column; map names at the provider | The cost table would quote one vendor's rates for another vendor's calls. |
| Reaching Gemini | Google's OpenAI-compatible endpoint | The `google-genai` SDK | The compatible endpoint reaches both structured output and streaming through a dependency already present and error types already mapped. The SDK's extra surface serves no role here. |
| Gemini schema strictness | The shared schema, unmodified | The OpenAI strict-mode rewrite | Strict mode's requirement that `required` name every property is OpenAI's rule; a compatibility layer may reject what it implies. Validation and one repair turn are the guarantee for every provider anyway. || Credential granularity | One per workload lane, falling back to a shared key | One key per provider; one key per role | One key makes a bursty ingest able to rate-limit a live take. One per role is fourteen settings to answer a question with three real answers. |
| Where the lane is declared | On the role, in the registry table | Passed by the caller; inferred from the call stack | A caller that picks a credential is a caller that knows about providers, which is the thing role addressing exists to prevent. || An unserved lane | Runs on the deterministic provider | Refuse to start; route it to a served lane | Refusing makes turning on one lane an all-or-nothing choice. Borrowing another lane's key spends money the operator declined to spend there. |
| An overloaded model | Re-attempt on the role's fallback model, then the deterministic floor | Fail the call; retry the same model with backoff | The stronger free-tier aliases are unavailable for minutes, not seconds, so backoff on the same model just spends the learner's patience. A cheaper reachable model is a worse answer; no answer is a broken product. |
| A degraded call in the ledger | Recorded against the provider and model that actually served | Recorded against the role's nominal model | The cost table answers what a workload costs. A row naming a model that did not run makes it fiction, and hides how often the floor is carrying the product. |
| Where the fallback ladder lives | Model fallback inside the provider; the deterministic floor as a wrapper in the factory | One try/except at each call site | A call site that handles provider outages is a call site that knows about providers, which is what role addressing exists to prevent. |
| Call timeouts | Per workload lane, budgeting the whole call | One provider-wide value; per attempt | A provider-wide value has to suit the most patient caller, so the impatient ones inherit it. A per-attempt value quietly doubles when a fallback runs, so the number does not mean what it says. |
| Retrying a timed-out interactive call | Move to the fallback model | The SDK's own retry against the same model | Retrying the alias that is overloaded doubles the wait before reaching the answer the sibling had all along. |
## Open Questions & Future Decisions

### Deferred

1. **The fake-provider coupling has no mechanical guard.** Four renderers in other segments
   must stay in step with the fake's parser, enforced only by comment.
2. **The unit-vector requirement should be a stated contract**, a type, or a test — currently
   it is an accident that holds.
3. **The budget bypass on render failure** should refuse rather than proceed.
4. **No evaluation harness reads the ledger.** Prompt version and hash are recorded on every
   call specifically to make prompt changes measurable, and nothing measures them.
5. **Superseded prompt files carry no marker**, so the prompts directory cannot be read
   independently of the registry.
6. **Voice spend is recorded under a pseudo-role.** Whether synthesis belongs in the same
   ledger as model calls is unresolved.

## References

- `docs/integrations.md` — provider selection and fallbacks
- `docs/intent/coaching/coaching-design.md` — the streaming consumer
- `docs/intent/curriculum/curriculum-design.md` — the highest-volume consumer

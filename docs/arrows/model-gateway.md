# Arrow: model-gateway

Every paid model call in one seam: role addressing, versioned prompts, budget enforcement,
a ledger, and a deterministic floor that needs no credentials.

## Status

**AUDITED** — last audited 2026-08-21 (git SHA `2006ff8`). The seam holds: the whole product
runs and is tested with no credentials. Two invariants it depends on are unstated, and one
budget path can be bypassed.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/model-gateway/model-gateway-design.md`

### EARS
- `docs/intent/model-gateway/model-gateway-specs.md` (44 specs)

### Tests
- `backend/tests/unit/test_course_budget.py`, `test_fake_provider.py`
- `backend/tests/unit/test_gemini_provider.py` — provider selection, per-provider pricing, streaming
- `backend/tests/unit/test_prompt_placeholders.py` — every prompt interpolates in the renderer's syntax
- `backend/tests/integration/test_cost_ledger.py`, `test_ledger_links.py`

### Code
- `backend/app/llm/registry.py` — the role table
- `backend/app/llm/base.py`, `factory.py`, `anthropic_provider.py`, `openai_provider.py`, `gemini_provider.py`
- `backend/app/llm/lane_router.py` — per-lane provider routing, with the deterministic floor underneath
- `backend/app/llm/fake_provider.py` — the deterministic floor
- `backend/app/services/llm_gateway.py` — budget and ledger
- `backend/app/repositories/llm_calls.py`
- `backend/app/prompts/` — versioned prompt files

## Architecture

**Purpose:** Let callers name a role, keep spending bounded and recorded, and guarantee a
working answer with no provider configured.

**Key Components:**
1. `registry.py` — role to provider, model, prompt version and schema.
2. `llm_gateway.py` — checks the ceiling before the call, writes exactly one ledger row after it.
3. `fake_provider.py` — deterministic generation, streaming and embeddings.
4. `prompts/` — versioned files; a change is a new file.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Role addressing | `LLM-ROLE-001` – `006` | 5 | 1 | 0 |
| Provider selection | `LLM-PROV-001` – `010` | 9 | 0 | 1 |
| Prompt versioning | `LLM-PROMPT-001` – `005` | 4 | 0 | 1 |
| Budget | `LLM-BUDGET-001` – `005` | 4 | 0 | 1 |
| Ledger | `LLM-LEDGER-001` – `006` | 5 | 0 | 1 |
| Deterministic floor | `LLM-FAKE-001` – `008` | 6 | 1 | 1 |
| Embeddings | `LLM-EMBED-001` – `004` | 3 | 0 | 1 |

**Summary:** 36 of 44 implemented; 2 deliberate non-wants; 6 active gaps.

## Key Findings

1. **An unstated invariant holds up similarity scoring.** `ingestion/extract.py:157` defines
   `_cosine` as a bare dot product with no normalisation. It is correct only because every
   embedding provider currently returns unit vectors — `fake_provider.py:981` normalises, and
   OpenAI's embeddings arrive normalised. Nothing states that requirement: not a type, not a
   docstring, not a test. A provider that returned unnormalised vectors would silently change
   what the concept-merge thresholds mean rather than fail (`LLM-EMBED-004`).

2. **Budget enforcement can be skipped.** `_enforce_budget` returns without checking when
   prompt rendering raises, so a rendering failure bypasses the ceiling instead of refusing
   the call (`LLM-BUDGET-005`).

3. **The deterministic provider is the most tightly coupled component in the system.** It
   reverse-parses the wire format of four renderers in other segments — the drill rubric, the
   ingestion fragments, the skill list, and the QA passages. Two carry explicit "these must
   change together" comments. The coupling is real, load-bearing, and guarded only by comment:
   no shared constant, no shared parser, no failing test (`LLM-FAKE-008`).

4. **Superseded prompts carry no marker.** Several prompt versions and schemas remain with
   nothing indicating they are superseded; only the registry's silence distinguishes live from
   dead, so the prompts directory cannot be read on its own (`LLM-PROMPT-004`).

5. **The ledger is complete and unread.** One row per call including failures and
   cancellations, with prompt identifier, version and hash — precisely the data needed to
   answer whether a prompt change helped. One endpoint reads it for cost; nothing reads it for
   quality (`LLM-LEDGER-006`).

6. **The floor is real, not a mock.** The whole product — ingestion, grading, feedback,
   coaching, curriculum compilation — runs with no credentials, and CI runs that way.

## Work Required

### Must Fix
1. Refuse the call when prompt rendering fails, rather than proceeding unchecked
   (`LLM-BUDGET-005`).

### Should Fix
2. State and enforce the unit-vector requirement for embedding providers — as a type, a test,
   or a normalisation at the seam (`LLM-EMBED-004`).
3. Share the rendered wire formats mechanically between the renderers and the deterministic
   parser (`LLM-FAKE-008`).

### Consider
4. Mark superseded prompt versions in the prompt store (`LLM-PROMPT-004`).
5. Build the prompt evaluation harness the ledger was designed to feed (`LLM-LEDGER-006`).
6. Decide whether voice synthesis belongs in the same ledger as model calls.

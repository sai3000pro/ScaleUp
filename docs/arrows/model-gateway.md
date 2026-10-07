# Arrow: model-gateway

Every paid model call in one seam: role addressing, versioned prompts, budget enforcement,
a ledger, and a deterministic floor that needs no credentials.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). The seam holds: the whole product
runs and is tested with no credentials.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/model-gateway/model-gateway-design.md`

### EARS
- `docs/intent/model-gateway/model-gateway-specs.md` (44 specs)

### Tests
- `backend/tests/unit/test_course_budget.py`, `test_fake_provider.py`
- `backend/tests/unit/test_stream_usage.py` — streamed usage recorded when reported
- `backend/tests/unit/test_render_refusal.py` — a prompt that will not render is refused
- `backend/tests/unit/test_vectors.py` — unit-normalised embeddings at the seam
- `backend/tests/unit/test_wire_formats.py` — shared render/parse formats round-trip
- `backend/tests/unit/test_superseded_prompts.py` — superseded versions derivable from the store
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
| Provider selection | `LLM-PROV-001` – `010` | 10 | 0 | 0 |
| Prompt versioning | `LLM-PROMPT-001` – `005` | 5 | 0 | 0 |
| Budget | `LLM-BUDGET-001` – `005` | 5 | 0 | 0 |
| Ledger | `LLM-LEDGER-001` – `006` | 6 | 0 | 0 |
| Deterministic floor | `LLM-FAKE-001` – `008` | 7 | 1 | 0 |
| Embeddings | `LLM-EMBED-001` – `004` | 4 | 0 | 0 |

**Summary:** 42 of 44 implemented; 2 deliberate non-wants; 0 active gaps.

## Key Findings

1. **Wire formats are shared mechanically.** `app/domain/wire_formats.py` holds each
   prompt listing's render function next to the parse regex that must round-trip with
   it. The renderers in `drill_service`, `segment`, `prereqs`, `summarise`, and
   `qa_service` call the domain functions; the deterministic provider imports the
   regexes (`LLM-FAKE-008`).

2. **Embedding vectors are unit length at the seam.** `embed_texts_recorded`
   normalises every provider vector through `domain.vectors.unit_normalise`, so
   `extract._cosine` is an honest dot product and similarity thresholds mean the
   same for every provider (`LLM-EMBED-004`).

3. **A prompt that will not render is refused.** `_enforce_budget` lets the render
   error propagate after recording exactly one failure row — refused before any
   provider spend (`LLM-BUDGET-005`).

4. **Streamed calls record reported usage.** A provider that reports token counts
   ends its stream with a `StreamDelta` carrying `usage`; the ledger prefers it and
   falls back to the character estimate only when nothing was reported
   (`LLM-PROV-006`).

5. **Superseded prompts are derivable.** `prompts.registry.superseded_prompts`
   returns every version on disk no live role references; `check_integrations.py`
   prints the list (`LLM-PROMPT-004`).

6. **The ledger answers "did the edit help?".** `GET /courses/{id}/cost` groups
   outcomes by `(role, prompt_id, prompt_version)` into `by_prompt_version`
   (`LLM-LEDGER-006`).

7. **The floor is real, not a mock.** The whole product — ingestion, grading, feedback,
   coaching, curriculum compilation — runs with no credentials, and CI runs that way.

## Work Required

### Consider
1. Decide whether voice synthesis belongs in the same ledger as model calls.

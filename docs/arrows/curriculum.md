# Arrow: curriculum

Source material becomes a published prerequisite graph of skills, with derived stores for
traversal and retrieval.

## Status

**AUDITED** — last audited 2026-08-21 (git SHA `2006ff8`). The largest segment: 106 files,
roughly a quarter of the repository. The compiler works and is measured; its measured quality
is mediocre and its measurement harness is missing from the repository.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/curriculum/curriculum-design.md`

### EARS
- `docs/intent/curriculum/curriculum-specs.md` (85 specs)

### Tests
- `backend/tests/unit/test_skill_catalogue.py` — the shared catalogue, spec by spec
- `backend/tests/unit/test_goal_planner.py` — instrument resolution, the floor, plan validation
- `backend/tests/integration/test_goal_to_tree.py` — a sentence to a published, playable tree
- `backend/tests/integration/test_goal_plan_fallback.py` — a proposal that cannot be trusted
- `backend/tests/unit/test_course_shelves.py` — the shelf declaration itself
- `backend/tests/unit/test_lesson_sets.py` — a skill's lesson run climbs and stays one skill
- `backend/tests/unit/test_dag.py` — acyclic admission, transitive reduction, what a rejection keeps
- `backend/tests/integration/test_course_shelves.py` — the shelf on the payload the list is drawn from
- `frontend/lib/courses.test.ts` — which courses stand in which list
- `backend/tests/unit/test_toc.py`, `test_prereqs.py`, `test_segment.py`, `test_summarise.py`, `test_extract.py`, `test_curriculum_*.py`
- `backend/tests/integration/test_ingest_pipeline.py`, `test_graph_persistence.py`, `test_curriculum_graph_lifecycle.py`, `test_structural_nodes.py`

### Code
- `backend/app/ingestion/` — `toc.py`, `segment.py`, `summarise.py`, `prereqs.py`, `extract.py`, `chunking.py`, `embed.py`, `fetch.py`, `parsers/`
- `backend/app/services/` — `graph_service.py`, `curriculum_graph_service.py`, `ingest_pipeline.py`, `course_service.py`, `admin_service.py`, `search_service.py`, `qa_service.py`
- `backend/app/core/shelves.py` — the shelf declaration and the seeded course ids
- `frontend/lib/courses.ts`, `frontend/app/courses/page.tsx` — the learner's list and the prebuilt view
- `backend/app/curricula/catalogue.json` — the shared skill catalogue
- `backend/app/curricula/banjo.json` — five of seven concepts drawn from it
- `backend/app/curricula/loader.py` — catalogue resolution, `OVERRIDABLE_FIELDS`, suggested edges
- `backend/app/curricula/planner.py` — goal to definition: resolution, the floor, plan validation
- `backend/app/services/curriculum_plan_service.py` — goal-first orchestration and provenance
- `backend/app/prompts/curriculum_plan/v1.md`, `backend/app/llm/json_schemas/curriculum_plan.v1.json`
- `backend/app/research/`, `backend/app/vector/`, `backend/app/repositories/neo4j_repo.py`
- `backend/app/tasks/ingest.py` — the ingest task chain (`CURR-JOB-001` – `005`)
- `frontend/components/course/CurriculumPlanner.tsx`

## Architecture

**Purpose:** Turn documents into a reviewable, versioned, evidence-backed skill graph — with
the relational store as the only authority and everything else rebuildable from it.

**Key Components:**
1. Two construction paths — structure-first from a document's own outline, inference-first over content windows — selected per document on outline-entry count.
2. `prereqs.py` — prerequisite inference with quote-backed evidence and confidence.
3. `graph_service.persist_graph` — replacement, cycle rejection, stable identity mapping.
4. `curriculum_graph_service` — versions, candidate review, publication.
5. Derived stores — graph for traversal, vector for retrieval; both rebuildable.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Shared catalogue | `CURR-CAT-001` – `011` | 10 | 1 | 0 |
| Goal-first construction | `CURR-GOAL-001` – `018` | 17 | 1 | 0 |
| Course shelving | `CURR-SHELF-001` – `006` | 6 | 0 | 0 |
| Source acquisition | `CURR-SOURCE-001` – `007` | 7 | 0 | 0 |
| Structure extraction | `CURR-PARSE-001` – `008` | 6 | 1 | 1 |
| Prerequisite inference | `CURR-EDGE-001` – `007` | 6 | 0 | 1 |
| Graph persistence | `CURR-GRAPH-001` – `006` | 4 | 0 | 2 |
| Versioning | `CURR-VERSION-001` – `011` | 9 | 0 | 2 |
| Derived stores | `CURR-PROJ-001` – `006` | 5 | 1 | 0 |
| Background work | `CURR-JOB-001` – `006` | 5 | 0 | 1 |

**Summary:** 75 of 85 implemented; 4 deliberate non-wants; 7 active gaps.

## Key Findings

0. **A sentence is now a construction path.** A learner types "I want to learn how to play
   guitar" and gets a published, playable tree in one request — no document, no ingest, no
   background job. The instrument is read out of the goal; a shipped instrument assembles from
   its own reviewed curriculum, and anything else goes to a model with the *whole catalogue as
   a closed vocabulary* to select from. Passing the vocabulary rather than a description is
   what makes two instruments share a skill entity instead of two similarly-worded copies.

1. **The floor is the feature, not a mock of it.** With no provider configured, every goal
   still resolves: the shared catalogue supplies the spine and the catalogue's own suggested
   edges supply the order, so a learner gets reading, pulse, orientation and phrasing in a
   sensible sequence while the instrument-specific half waits for a key. Four tests break the
   proposal in four different ways — unknown skill, undersized plan, provider outage, and a
   valid plan — and all four end with a playable tree.

2. **Skills are shared, and the sharing is bounded.** Seven catalogue skills back 22 concepts
   across six instruments. Difficulty inherits from the catalogue in 15 of 17 links, so the
   shared difficulty judgement genuinely holds; summaries are almost always restated, because
   "keep the pulse with the hi-hat" and "keep the pulse with the bow" are different sentences
   about one skill. Banjo is the proof: 5 of its 7 concepts come from the catalogue, three of
   them authored in two lines, and it scores through the guitar evaluator with no
   banjo-specific code anywhere.

8. **Graph replacement can take learner progress with it.** `persist_graph` replaces a
   course's graph wholesale, and its cascade has previously destroyed a learner's experience
   and review history — an incident recorded verbatim in three source comments
   (`admin_service.py:15`, `ingest_pipeline.py:582`, `test_admin_reindex.py:12`) as **1325 EXP
   and 9 reviews**. Six integration test modules independently guard the operation. Six tests
   defending one call is the boundary asking to be moved (`CURR-GRAPH-005`).

2. **Extraction quality is measured and mediocre.** The reference corpus yields 37 nodes at
   recall 0.397 and precision 0.600, with zero backwards edges. Edge direction is reliable;
   node granularity is not.

3. **Those measurements are currently unreproducible.** The scoring harness they were produced
   with is imported at runtime by `backend/collapsed.py:21` and cited as real by both
   `docs/archive/graph_extraction_contract.md:228` and live code at `app/ingestion/toc.py:303`
   — and it does not exist in the repository. Neither does the hand-authored reference tree
   they were scored against.

4. **A stale comment inverts a live invariant.** `prereqs.py:152-155` still asserts outline
   edges sit at 0.95 and "must keep winning cycle contests against inference", which is the
   stated reason the inference caps sit at 0.85 and 0.9. Outline edges were deliberately
   lowered to 0.45 after measurement (`toc.py:243`, with its rationale at 249). The caps
   remain; the guarantee they protected is now reversed, and inference outranks structure
   (`CURR-EDGE-007`).

5. **Sub-section segmentation is off, and the reason is measured** — it improves granularity
   and collapses prerequisite precision. Title-distinctiveness filtering is the named
   prerequisite for switching it on (`CURR-PARSE-007`).

6. **Sibling modules collide on names** — two section-length minimums, three summary-length
   constants, three unrelated `_absorb` functions, two unrelated `_merge` functions, and three
   independent statements of "four entries is enough of a table of contents".

7. **Evidence discipline is excellent.** Every inferred edge carries an exact source quote,
   extractor and prompt hashes, and a confidence; rejected edges stay recorded with reasons.

## Work Required

### Must Fix
1. Separate graph replacement from learner-progress lifetime by construction
   (`CURR-GRAPH-005`). Test coverage is currently the only thing preventing a repeat.
2. Restore or replace the measurement harness and reference tree, or withdraw the accuracy
   claims that depend on them.

### Should Fix
3. Declare the confidence ordering in one place and assert it; correct the stale comment
   (`CURR-EDGE-007`).
4. Implement skill split, merge, rename and retirement across versions (`CURR-GRAPH-006`) —
   without them a substantive revision cannot preserve progress.
5. Land title-distinctiveness filtering, then re-measure with segmentation enabled
   (`CURR-PARSE-007`).

### Consider
6. Build the candidate-review surface showing affected unlock paths (`CURR-VERSION-008`).
7. Add publication quality gates (`CURR-VERSION-007`).
8. Resolve the sibling-module name collisions.

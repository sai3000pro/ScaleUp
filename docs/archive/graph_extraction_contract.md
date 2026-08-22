# Graph Extraction Contract

**Owner:** `backend/app/ingestion/` + `backend/app/domain/dag.py`
**Consumer:** `backend/app/services/graph_service.py`, and every read path via `GET /api/courses/{id}/graph`

This is the interface between "a PDF, HTML document, or web page arrived" and "a skill tree exists". It is the
highest-risk part of the product: everything downstream is only as good as the
graph, and the graph is produced by a language model that must be assumed
unreliable.

---

## Edge direction, once and for all

`source → target` means **"learn source before target"**. `source` is the
prerequisite. In the database the columns are `prereq_id` and `target_id`; in the
API they are `source` and `target` (matching React Flow). Nothing else in this
project is allowed to invent a third naming.

---

## Stage 1: parse

`ingestion/parsers/pdf.py` (PyMuPDF) and `ingestion/parsers/html.py` (BeautifulSoup)
emit the same `ParsedDocument`: pages/blocks where each block carries its text
and a heading level or `None`. HTML uses synthetic pages so source references and
chunk ownership keep the same shape as PDF ingestion.

Heading detection is worth its ~40 lines because it is what makes chunking good:
take per-span font sizes from `page.get_text("dict")`, treat the modal size as
body text, and promote a line to a heading candidate when it is ≥1.15× body size
**and** short (<80 chars), cross-checked against a numbering regex
`^\s*(\d+(?:\.\d+){0,2})\s+\S`. Levels come from the numbering depth when present
and from the size ranking otherwise.

The output of this stage is a `section_path` per block, like `"3 / 3.2 / 3.2.1"`.

---

## Stage 2: chunk

`ingestion/chunking.py`, pure and unit-tested, no I/O (with HTML parsing
normalizing web-page blocks into the same input shape):

1. Accumulate blocks until adding another would exceed **800 tokens**
   (tiktoken `cl100k_base`).
2. **Never cross a heading of level ≤ 2.** Flush early instead. A chunk spanning
   two chapters produces garbage skills.
3. A single section over 800 tokens is sliding-windowed at 800 with **120 tokens
   of overlap**, splitting only on sentence boundaries.
4. Every chunk carries `section_path`, `page_start`, `page_end`, `ordinal`.
5. Drop chunks under 60 tokens — page numbers, orphan captions — unless a chunk
   is the entire content of its section.

`section_path` is not decoration. It is passed into the extraction prompt, and it
is most of what stops the model from inventing a concept called "Introduction"
forty times.

---

## Stage 3: map — per-window extraction

One LLM call per window of **6 chunks** (~5k input tokens), never crossing a
level-1 heading. Role `GRAPH_EXTRACT_MAP` — deliberately the *cheap* model, since
a 1000-page book is ~120 of these calls.

Enforced with forced tool-calling (Anthropic) / strict `json_schema`
(OpenAI), then validated again with `jsonschema` on our side. On validation
failure: exactly one repair turn feeding the validator error back verbatim, then
record the failure and move on. A third attempt almost never helps and the cost
is linear.

### `llm/json_schemas/concept_map.v1.json`

```jsonc
{
  "type": "object",
  "additionalProperties": false,
  "required": ["concepts", "prerequisites"],
  "properties": {
    "concepts": {
      "type": "array", "maxItems": 12,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["slug", "title", "summary", "difficulty", "assessable", "evidence_ordinals"],
        "properties": {
          "slug":       { "type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$", "maxLength": 64 },
          "title":      { "type": "string", "minLength": 3, "maxLength": 80 },
          "summary":    { "type": "string", "minLength": 20, "maxLength": 400 },
          "difficulty": { "type": "integer", "minimum": 1, "maximum": 5 },
          "assessable": { "type": "boolean" },
          "key_terms":  { "type": "array", "maxItems": 8, "items": { "type": "string", "maxLength": 40 } },
          "evidence_ordinals": { "type": "array", "items": { "type": "integer" } }
        }
      }
    },
    "prerequisites": {
      "type": "array", "maxItems": 24,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["prereq_slug", "target_slug", "confidence", "rationale"],
        "properties": {
          "prereq_slug": { "type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$" },
          "target_slug": { "type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$" },
          "confidence":  { "type": "number", "minimum": 0, "maximum": 1 },
          "rationale":   { "type": "string", "maxLength": 200 }
        }
      }
    }
  }
}
```

The `slug` regex is doing real work: it forces the model into a canonical key
space, which makes the exact-match half of deduplication free.

### Prompt constraints (`prompts/graph_extract/v1.md`)

- A **skill** is something a learner can be asked to *demonstrate*, not a section
  title. "Chapter 3" is not a skill; "computing a partial derivative" is.
- `slug` names the **concept**, not the chapter, and prefers the conventional
  textbook term over the author's phrasing — two windows describing the same idea
  must produce the same slug, because the slug is the merge key.
- `summary` ≤240 chars, phrased as what the learner can *do*.
- `assessable: false` when the window has too little substance to write a
  short-answer question about. Non-assessable concepts are still stored (they
  carry the tree's structure) but never appear in drills or quests. See
  [Structural nodes](#structural-nodes-assessable--false) for what that flag
  costs and why it is safe to set.
- **At most 12 concepts per window.** Without a cap you get one per paragraph.
- Emit only prerequisites defensible from *this window's text*. Cross-window
  prerequisites are the reduce phase's job.

---

## Stage 4: reduce — merging ~1500 raw concepts into ~250 nodes

Deterministic first, model last. Each step is cheaper and more predictable than
the one after it, so as much as possible is resolved before any LLM is involved.

1. **Exact slug merge.** Normalise (lowercase, strip leading articles,
   singularise a trailing `s` when the stem is ≥4 chars). Merge; sum
   `mention_count`; union `source_chunk_ids`; keep the longest summary.
2. **Embedding merge.** Embed `title + ". " + summary` for each survivor in one
   batched call. Greedy agglomeration against a canonical list ordered by
   `mention_count` descending: cosine **≥ 0.90** merges, recording the alias.
3. **Bounded LLM adjudication.** *Only* pairs in the ambiguous band
   **0.82–0.90**, batched 40 pairs per call to role `GRAPH_MERGE`, returning
   `[{a, b, same: bool}]`. This is typically 3–6 calls, not 1500. Anything below
   0.82 is never sent to a model.
4. **Alias rewrite.** Every edge's slugs are rewritten through the alias map
   before edges are unioned. Edge confidence is the max over occurrences;
   `support` is the count. Edges with `support == 1 AND confidence < 0.5` are
   dropped as `low_confidence` — a prerequisite claimed once, weakly, in a
   700-chunk book is noise.

A second LLM pass (role `GRAPH_MERGE`, one call over the deduplicated concept
list — typically 30–150 concepts, a few thousand tokens) also proposes the
**cross-window prerequisites** that no single window could see, plus the set of
root concepts. Its edges join the same candidate pool.

Prompt constraints for that pass:

- "`A → B` means a learner who does not understand A **cannot meaningfully
  attempt** B. It does not mean A and B are related, adjacent, or usually taught
  together."
- "Never emit both `A → B` and `B → A`. Never emit `A → A`."
- "Prefer the minimal edge set. If `A→B` and `B→C`, do not also emit `A→C`."
- "Every concept must be reachable: it is either a root or has ≥1 prerequisite."

---

## The outline gives nodes and labels, never edges

A table of contents is a **containment tree**, and containment is not a
prerequisite relation. The pipeline used to emit one `parent -> child` edge per
outline entry at confidence `0.95`. Measured on CO 250 that was **38 of 77
edges**: half the graph was the book's contents page, asserted more strongly than
every edge actually derived from the prose, whose best was `0.90`.

It also produced the wrong shape. Every chapter became a root and every skill
hung beneath one, so the canvas rendered the author's filing system rather than
the dependency structure the product exists to show.

What the outline contributes now:

| | Contributes |
|---|---|
| Nodes | Yes -- one per heading that owns prose of its own |
| `section` label | Yes -- the outermost ancestor's title, as provenance |
| Edges | **Only** `build_introduces_edges`, below |
| Structural nodes | No -- a heading owning no chunk is not a node at all |

`app.ingestion.toc.section_labels` computes the label. It is stored on
`skill_nodes.section`, surfaced in `GraphNodeOut.section`, and used by the canvas
to group and to tell a learner where in the book a skill lives. It gates nothing.

### The one surviving structural edge

`build_introduces_edges` emits `parent -> child` **only where the parent is
drillable** -- where `is_drillable` says it owns prose belonging to no one else.
CO 250's "Integer programs" spends page 75 on why an IP is harder than an LP
before its first subsection begins, so it teaches something and "Cutting planes"
genuinely follows it. "Duality" owns nothing, is not a node, and cannot precede
anything.

On CO 250 that narrow case is worth **five edges, every one between two real
skills**, and it is the difference between recall `0.353` and `0.397` at
identical precision.

Its confidence is `INTRODUCES_CONFIDENCE = 0.45`, deliberately **below**
`prereqs.MIN_CONFIDENCE` (0.5). This inverts the old ordering: when a structural
claim and a claim read out of the prose disagree during cycle resolution, the
prose wins. It is evidence about the material; this is an inference from where
the material was printed.

### Measured effect

```
                nodes  containers  edges  recall  precision  backwards
before             44           7     77   0.397      0.600          0
after              37           0     45   0.397      0.600          0
```

Identical quality, seven fewer phantom nodes, and 32 fewer edges asserting that
page adjacency is a knowledge dependency. `score.py` already dropped every
container-incident edge before scoring, which is why the measured numbers do not
move: what changed is what the learner sees.

## Structural nodes (`assessable = false`)

A skill is something a learner can be asked to *demonstrate*. A chapter heading
usually is not, and the outline path emits both.

**The test is exclusive chunk ownership, not the shape of the outline.**
`owner_of_page` assigns every chunk to the *deepest* heading whose page range
contains it, so "owns at least one chunk" means "has prose that belongs to no
one else" — which is exactly the material a drill question would be generated
from and graded against. `ingestion/toc.py:is_drillable` is that one line, and it
catches two different populations:

| Population | Example | How it arises |
|---|---|---|
| Pure container | CO 250 "Duality" | Its first section starts on the chapter's own opening page, so no page is exclusively its own. CO 250 has seven. |
| Empty heading | CS 251, seven of 34 nodes | The heading's pages produce no chunk at all — too short, or a page of figures. Not a container: it has no children. |

`has_children` is the tempting one-line test and it is **wrong**. CO 250's
"Integer programs" spends page 75 on why an IP is harder than an LP before its
first subsection begins: children *and* a genuine skill. It owns that page, so it
stays assessable.

Two consequences follow, and both are load-bearing:

**A structural node gets no provenance and no borrowed text.** There used to be a
fallback that handed a container the first couple of chunks of its own subtree,
reasoning that a node with no `source_chunk_ids` cannot be drilled. It was worse
than nothing: on CO 250 it gave "Duality" text byte-identical to its child "Weak
duality" — same 2696 characters, same pages 54–56 — and the content-derived
prerequisite pass then read the child's prose while believing it was the
parent's. Three of the edges it produced came back out of `build_acyclic_edges`
as *duplicates of the structural edges*: the pass had re-derived the child's own
relationships from a copy of the child's text. Copying a child's material up into
its parent does not make the parent drillable; it makes two nodes claiming one
skill.

**Structural nodes are excluded from the closed vocabulary sent to
`PREREQ_INFER`.** An edge into or out of a container asserts nothing a learner
can act on — you cannot send the reader of "Strong duality" away to go and learn
"Duality", because there is nothing there to learn. Leaving them in the listing
was the other half of the problem: a chapter title that appears in its own
sections' prose collects an edge from every one of them, and those edges displace
the real child-to-child ones. On CO 250 this took content-derived edges incident
to a container from 8 to 0 while leaving the 16 edges between real skills
untouched.

### Why `assessable = false` is safe now, and was not before

The pipeline used to force `assessable = true` on every outline node with this
justification: a node that can never be drilled records no attempt, so its
mastery stays 0.0 for ever, so every descendant is permanently `LOCKED` — and the
quest board excludes structural nodes, so nothing could ever unlock it. One
container quarantined its whole subtree with no in-app way out.

`domain/states.py:gating_masteries` removed that. A structural node is
**transparent** rather than unfinished: it contributes the masteries of its *own*
prerequisites instead of its non-existent one. A container with no prerequisites
is trivially cleared and gates nothing; a container that genuinely sits behind
real work still passes that work through. All four consumers go through it —
`graph_read.build_snapshot`, `drill_service` (eligibility and unlock detection),
and `quest_service.build_board` — and `tests/integration/test_structural_nodes.py`
is the end-to-end proof across the graph read, drill eligibility, the quest board
and the EXP/level math.

`graph_read._blocking_prereqs` mirrors the same walk while keeping ids, so a
locked node's `blocked_by` names something the user can actually go and drill
rather than a heading they cannot.

---

## Difficulty comes from the dependency graph

`skill_nodes.difficulty` (1–5, the key into `DIFFICULTY_MULT`) is derived from
`topological_depths`, not from outline nesting.

Nesting depth was the previous signal and it inverted on real books. Containers
came out at 2 while their own sections came out at 4–5, so a chapter was "easier"
than everything inside it. And CO 250's convex hulls (chapter 4) and the KKT
theorem (the book's last section) are both level-2 entries, so nesting could not
tell them apart at all.

`ConceptSpec.difficulty` is therefore `None` by default, meaning *derive it*, and
`persist_graph` resolves it with `toc.difficulty_from_depth(depth, max_depth)`.
An explicit number overrides — the seed fixture names its own, and the LLM path
keeps the model's, which was read off the material rather than off the tree.

**It is stored, and that is deliberate.** "Nothing time-derived is stored"
(CLAUDE.md) is about values whose inputs change while nobody is writing; a
graph-derived value has no such problem. Difficulty is written inside
`persist_graph`, in the same transaction as `depth`, from the same
`topological_depths` call, and `persist_graph` rewrites *every* node in the
course — so the only event that can change the input is the one event that
recomputes the output. Computing it on read would mean loading the full edge set
and running Kahn's algorithm on every graph fetch to reproduce a number already
sitting in the row next to it.

---

## Stage 5: cycle rejection

**Policy: never trust the model's acyclicity claim, and never repair after the
fact.** The graph is acyclic *by construction* — candidate edges are admitted
greedily in descending confidence, and any edge whose target already reaches its
source is rejected.

Greedy-by-confidence is the right policy because it makes the failure mode
sensible: when the model reports both `limits → derivatives` at 0.95 and
`derivatives → limits` at 0.41, the confident one wins and the contradiction is
recorded with its actual cycle path.

`domain/dag.py` exposes three pure functions:

| Function | Guarantee |
|---|---|
| `build_acyclic_edges(slugs, candidates, min_confidence)` | Returns `(accepted, rejected)`. The accepted set is a DAG. Deterministic: ties break on `(-confidence, -support, prereq, target)`, so re-ingesting the same document yields byte-identical output. |
| `topological_depths(slugs, edges)` | Kahn's algorithm. Raises `CycleError` if the input is cyclic — the post-condition assertion that `build_acyclic_edges` did its job. Supplies `skill_nodes.depth`, which drives the dagre rank. |
| `transitive_reduction(slugs, edges)` | Drops `u→v` when a longer `u→…→v` path exists. **Display only** — the full edge set stays in Postgres; the reduced set is what the API returns. |

`transitive_reduction` is the highest-value-per-line function in the project for
perceived quality. Roughly 40% of extracted edges are transitively implied, and
rendering them turns a legible tree into a hairball.

Rejections are persisted to `skill_edge_rejections` with `reason ∈ {self_loop,
duplicate, unknown_node, low_confidence, cycle}` and, for cycles, the actual
`cycle_path`. That table is the primary debugging material for prompt iteration —
`SELECT reason, count(*) FROM skill_edge_rejections GROUP BY 1` after a real
ingest tells you what the model is getting wrong.

**Partial failure is tolerated.** A textbook that loses 3 of 120 extract batches
to schema-validation failures still produces a usable graph; the count surfaces
in `stage_detail.failed_windows`. Failing the whole job over it is the wrong
trade.

---

## Stage 6: persist

The graph unit is the **course**, not the document. Before this stage runs for an
upload, `ingest_pipeline.extract_graph` assembles the outline and inferred
contributions from every committed document in the course. Each document is
processed independently for outline eligibility and fallback extraction, then the
candidate concepts and edges are combined into one course vocabulary. This is
what makes adding a second textbook or web page additive instead of replacing the
first document's graph.

One transaction: upsert `skill_nodes` on `(course_id, slug)`, replace
`skill_edges` for the course, insert `skill_edge_rejections`, write `depth` from
`topological_depths`, bump `courses.graph_version`. Replacing edges is safe because
edges have no learner-owned dependants; node upserts retain existing UUIDs by slug,
so `node_progress`, questions, and attempts remain attached. A new document whose
heading collides with an existing slug receives a deterministic suffix rather than
silently inheriting the existing node.

Then, and only after commit, project to the derived stores: Neo4j
(`(:Skill)-[:PREREQUISITE_OF]->(:Skill)`) and Chroma (chunk embeddings for
retrieval). Neither is ever written before Postgres, and both are rebuildable via
`POST /api/admin/courses/{id}/reindex`.

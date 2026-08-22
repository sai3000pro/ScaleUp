# Learn-Anything (archived product description)

> This is the original product framing, kept for provenance. The live product is
> [Learn-Any-Instrument](../../README.md). The pipeline described here still
> runs — see [the archive note](README.md) for why.

Turn a textbook, paper, or web page into an RPG-style skill tree you can explore,
search, question, and drill — with spaced repetition underneath, so what you
learn decays unless you come back for it.

The loop: **ingest & map → assess & drill → grade & reward → decay & retain.**

Anki's retention mechanics with a tech tree's dopamine loop.

---

## What it did

Upload a PDF or point it at a URL. The pipeline reads the document's own
structure, turns it into a directed acyclic graph of skills, and hands you a
canvas of orbs — locked, ready, fading, mastered.

- **Explore.** Pan a dependency-ordered graph. Locked nodes tell you what they
  are waiting on; a guided path tells you where to start.
- **Search.** Fuzzy over titles, semantic over the chunk embeddings, unioned and
  mapped back to owning nodes.
- **Ask.** RAG over the course that answers with citations pointing at nodes and
  the chunks they came from.
- **Drill.** Generated questions per node, graded against a rubric, awarding EXP.
- **Decay.** SM-2 scheduling. Mastery is an exponential moving average, and
  nothing time-derived is ever stored — it is computed on read from
  `(last_reviewed_at, interval_days, ease)`.

Every one of those surfaces still exists. They are now pointed at method books,
syllabi, and exercise catalogues instead of textbooks, and they feed the
curriculum compiler rather than being the product themselves.

---

## How the graph gets built

**Table of contents first, model second.** The primary path reads the document's
own outline — the embedded PDF bookmark tree, or a printed Contents page, or
HTML `h1..h6` — and makes each heading that owns prose of its own a node.
Prerequisite edges then come from two content passes over a *closed* skill
vocabulary: a forward pass ("what does this section depend on?") and a reverse
pass ("which sections use this skill?"), the second because the first can only
ever surface a prerequisite the prose happens to name by title.

**The outline gives nodes and labels, not edges.** A table of contents is a
containment tree, and containment is not a prerequisite relation. Emitting
`parent -> child` as an edge made 38 of CO 250's 77 edges the book's contents
page, asserted above every edge derived from the prose — so the canvas rendered
the author's filing system instead of the dependency structure. The chapter
survives as a `section` label on each skill: provenance, gating nothing. The one
exception is a heading that teaches something itself, which genuinely introduces
its own subsections.

Cycles are rejected greedily in confidence order, then the DAG is transitively
reduced so the canvas shows the skeleton rather than the closure.

The LLM map/reduce extractor still exists and runs as the **fallback**, for
documents whose outline is too thin to trust.

Consequences worth knowing:

- Nodes are as granular as the book's own headings. On a textbook that means a
  node is roughly a section, which can be coarser than a concept.
- A concept the book never gives a heading to cannot become a node. Row
  reduction is used throughout CO 250 and appears in no outline entry, so it is
  not in the graph.
- A heading with no prose of its own is not a node at all — it was structure,
  and structure is now the `section` label rather than an orb.

[`graph_extraction_contract.md`](graph_extraction_contract.md) covers this in
full, and remains the live contract for `app/ingestion/`.

---

## Measured extraction quality

These numbers are why `SEGMENT_SECTIONS` is still `false` by default, so they
are worth keeping even though the framing around them has changed.

Measured against a hand-authored 79-concept reference tree for **CO 250**
(Introduction to Optimization):

| | Nodes | Edges | Recall | Precision | Backwards edges |
|---|---|---|---|---|---|
| Shipped default | 37 | 45 | 0.397 | 0.600 | 0 |
| `SEGMENT_SECTIONS=true` | 142 | — | 0.280 | 0.157 | — |

The dominant error term is **granularity**: roughly two reference concepts land
inside the average node, so about 65% of the true edges are inexpressible at the
current node size rather than missed outright.

Sub-section segmentation fixes the granularity (44 nodes → 142) and breaks the
edges. The prerequisite pass sends the whole skill vocabulary with every
section, so at 135 skills × 135 sections a title like "Feasible solution" —
which genuinely appears in most sections of an optimisation textbook — collects
62 outbound edges. A wrong prerequisite locks a learner out of material they are
ready for, so that trade is a regression however much better the granularity is.
Turning it on needs a title-distinctiveness filter on candidate matches first.

With `LLM_PROVIDER=fake`, every inferred edge is keyword overlap. The numbers
above are the no-key floor, not the ceiling.

---

## Other known limits at the time of archiving

- The admin surface has API routes and typed clients but no UI.
- Re-ingesting the same URL usually creates a second document: dedupe is on raw
  bytes, and HTML is rarely byte-stable.

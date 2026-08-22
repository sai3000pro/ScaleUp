---
parent: high-level-design
prefix: CURR
---

# Curriculum

## Context and Design Philosophy

Curriculum turns source material into a published prerequisite graph of skills, and keeps
the derived read-models that make that graph fast to traverse and search. It is the largest
segment in the system and the oldest: the document-ingestion engine underneath it is the
compiler's source path, which is how an instrument tree can be generated with no
instrument-specific code.

**Postgres is the only authoritative write.** The graph store is a derived read-model for
traversal; the vector store is a derived index for retrieval. Neither ever receives an
authoritative write, and both are rebuildable from Postgres on demand. Consistency is
therefore a question of *staleness* — a number you can monitor — rather than a correctness
bug you have to reason about.

**Every inferred edge carries its evidence.** A prerequisite claim records the exact source
quote that supports it, the extractor and prompt hashes that produced it, and its
confidence. A rejected edge stays recorded with its reason. A graph nobody can interrogate
is a graph nobody should trust.

**Draft cannot affect a learner.** Only a published version participates in unlocks,
experience, scheduling or quests. Publication is the boundary between authoring and
consequence.

**Task payloads carry identifiers, never content.** Background work is addressed by job and
range. A thousand-page book must never exist as a single task payload.

## The shared skill catalogue

Instruments overlap far more than they differ, so a skill is defined once and reused.
`catalogue.json` holds each shared skill under a stable identifier — `strumming`,
`steady-pulse`, `instrument-orientation` — with a title, summary, difficulty and key terms.

An instrument curriculum draws a concept from the catalogue with `"from": "<id>"`. The
catalogue definition is applied first and the instrument's own fields are layered over it, so
a concept that names nothing but its slug inherits the shared definition whole.

**Specialisation is bounded by a declared set.** `OVERRIDABLE_FIELDS` names exactly what an
instrument may restate: slug, title, summary, difficulty, key terms. Anything else is refused,
and the refusal lists what is permitted. The bound is the point — an open override surface
turns a catalogue back into one standalone curriculum per instrument wearing a shared name.

**Edges are never inherited.** The catalogue describes skills, not orderings. What must come
before what is a claim about one instrument, and a shared ordering would teach the wrong thing
next for whichever instrument it did not fit.

Every concept records the catalogue skill it realises, or that it was authored inline. That
link is what lets the system know a guitar's strumming and a banjo's strumming are the same
skill — which is what makes a shared evaluator, a shared exercise pattern, and eventually
transfer credit possible.

A concept that needs no restatement is two lines:

```json
{ "from": "strumming", "slug": "banjo-strumming" }
```

## Three construction paths

The segment contains three independent ways to build a graph. Two of them read a document and
are chosen per document; the third reads a learner's stated goal and is chosen by the request.

**Structure-first** uses the document's own table of contents when it has a usable one:
outline extraction, section segmentation, summarisation, and prerequisite inference over the
resulting skills.

**Inference-first** runs a language-model map/reduce over content windows when the document
has too few outline entries to trust its own structure.

**Goal-first** turns a sentence — "I want to learn how to play guitar" — into a published
tree without reading anything, and is the subject of the next section.

All three share only the candidate-edge and concept shapes, and all three end at the same
call: `seed_published_curriculum`. Selection between the two document paths is a single
configuration threshold on outline-entry count; goal-first is selected by which endpoint the
learner reached.

## Goal-first construction

A learner arrives with a sentence, not a curriculum. Goal-first turns that sentence into a
published, playable prerequisite graph in one request, with no document, no ingest and no
background job.

### The catalogue is asked, not searched

The goal text and the entire shared catalogue — every skill's identity, title, summary,
difficulty, key terms, and the catalogue's own suggested ordering — are handed to a model
under the `CURRICULUM_PLAN` role, which returns a **plan**: the instrument it read in the
goal, which catalogue skills that instrument needs, what to override on each, which concepts
are particular to the instrument, and what must come before what.

Passing the whole catalogue matters. A model asked to invent a syllabus invents a different
one every time and shares nothing between instruments; a model asked to *select from a closed
vocabulary* produces a tree whose shared skills are the same entities other instruments
already use, which is what makes "learners of two instruments are learning the same skill"
true rather than aspirational.

### The plan is validated, never repaired

A returned plan is checked before anything is written:

- every `from` names a catalogue skill that exists;
- every override names a field in the declared overridable set;
- concept slugs are unique within the curriculum;
- every edge names concepts the plan itself defines;
- the tree is within the size bounds a learner can actually face.

A plan that fails any check is **refused whole, and the deterministic assembly is used
instead**. It is never partially applied and never patched into validity: a repaired plan is a
tree nobody authored and nobody proposed.

Acyclicity is deliberately *not* on that list. Every construction path in this segment already
runs its candidate edges through the shared graph builder, which admits edges in descending
confidence and rejects any that would close a cycle, recording each rejection with its reason.
A proposed edge that would create a cycle is dropped there, exactly as a compiled one is —
refusing an otherwise sound plan over one such edge would make goal-first the only path in the
segment that treats a cycle as fatal rather than as information.

### The deterministic floor

Every goal resolves to a tree with no provider configured, because the floor is not a mock of
the model — it is the same assembly the project ships. Where the goal names an instrument with
a published curriculum, that curriculum *is* the answer, and the model has nothing to add. Where
it names anything else, the shared catalogue spine plus the catalogue's suggested edges is the
answer, and the learner gets reading, pulse, orientation and phrasing in a correct order while
the instrument-specific half waits for a provider.

### The catalogue's own ordering

The catalogue carries suggested prerequisite edges between catalogue skills. They are a
**prior, not a constraint**: they seed the shared spine when nothing better is available, and
they inform the plan. An instrument's published graph remains its own, because what must come
before what is a claim about that instrument — a shared ordering that holds for rhythm and
reading breaks for technique.

### Provenance

Every version records how it was built in `compiler_version`, and the value is the difference
between a tree the project authored and a tree the system proposed:

| Value | Meaning |
|---|---|
| `catalogue-assembly-v1` | Assembled from a published curriculum this project ships |
| `catalogue-plan-v1` | Proposed by a model against the catalogue, validated, published |
| `curriculum-compiler-v1` | Compiled from source documents with quote-backed evidence |

All three are playable immediately. The label is what keeps that honest.

## Course shelving

Three kinds of course sit in the same table, owned in development by the same
user, and only one kind belongs in a learner's list.

A **learner** course is one they created — from a stated goal, from an upload, or
empty. A **prebuilt** course is one the project offers ready-made, so someone who
has not decided what to learn still has somewhere to start; guitar and piano are
what is offered. An **internal** course is seeded so the admin, cost, scheduling and
evaluation paths are developable with no provider and no upload. Internal courses
are real and playable, and they are not on offer to anybody.

The shelf is a declared list of course ids, held in `app.core.shelves`, which the
seed and the course service both read. Nothing about a course's own row decides it:
a title suffix is a naming habit, and `compiler_version` cannot separate a shipped
guitar tree from a goal-built one, because assembling either runs the same code.

Every course carries its shelf outward on `CourseOut`, and the learner's surface
decides what to show. The list defaults to their own courses; the prebuilt set is a
deliberate second view they ask for. Internal courses appear on neither. Opening a prebuilt
course is opening a course — same tree, same drill loop, same progression — because
the shelf is a statement about where a course came from, not about what it is.

## Confidence

Edges compete. When admitting edges greedily by descending confidence, the confidence
assigned to each *kind* of edge decides which survives a cycle contest, so the ordering
between kinds is a design decision rather than a set of independent constants.

Prose inference is capped below certainty, and a single-direction inference is capped below
an agreed bidirectional one, so that agreement is worth something.

Containment edges derived from the outline are deliberately *low* confidence and narrow in
scope: they are emitted only where the containing heading is a skill in its own right.
Contributing one edge per outline entry at high confidence was measured to turn half the
graph into a table of contents and every chapter into a root — a filing system rather than a
dependency structure.

## Projections

The graph store holds nodes and edges for traversal; the vector store holds chunk embeddings
for retrieval. Both are rebuilt from Postgres by an administrative reindex, and both report
staleness.

## Versioning and publication

Skill definitions carry stable identifiers across revisions, so a graph revision preserves a
learner's progress rather than orphaning it. Versions are immutable once published.
Candidate edges are reviewed with their quote, confidence and provenance, and review
decisions are recorded.

## Current state versus intent

**Extraction quality is measured, and mediocre.** The reference corpus yields 37 nodes at
recall 0.397 and precision 0.600, with zero backwards edges. The direction of the edges is
reliable; the granularity of the nodes is not.

**The measurements are currently unreproducible.** The scoring harness the archived numbers
were produced with is cited as real by both the archived contract document and by live code,
and imported at runtime by a root-level measurement module — and it does not exist in the
repository. Neither does the hand-authored reference tree those numbers were scored against.

**A stale comment inverts a live invariant.** The prerequisite module still asserts that
outline edges sit at high confidence and "must keep winning cycle contests against
inference", which is the stated reason the inference caps sit where they do. Outline edges
were deliberately lowered below those caps after measurement. The caps remain; the guarantee
they were protecting is now reversed, and inference outranks structure in a contest.

**Sub-section segmentation is off, and the reason is measured.** Enabling it improves node
granularity and collapses prerequisite precision. Title-distinctiveness filtering is the
gate that has to land before it can be switched on.

**Graph replacement can take learner progress with it.** The persistence routine replaces a
course's graph wholesale, and its cascade has previously destroyed a learner's experience
and review history — an incident recorded in three separate source comments and defended
against by six integration test modules. Six tests guarding one operation is the boundary
asking to be moved.

**Sibling modules collide on names.** Two different section-length minimums, three different
summary-length constants, three unrelated private absorb functions, two unrelated merge
functions, and three independent statements of "four entries is enough of a table of
contents".

**Two module docstrings contradict their own code**: one denies a fallback that the same
module performs, and one states a confidence value the code no longer uses.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Source of truth | Postgres only; graph and vector stores derived | Write the graph store authoritatively | Derived stores make consistency a staleness metric instead of a correctness bug, and make rebuild always available. |
| Edge evidence | Exact quote, hashes and confidence recorded | Store the edge alone | An unreviewable graph cannot be trusted or corrected. |
| Rejected edges | Retained with reason | Discarded | Rejections are the record of what the compiler decided against. |
| Draft isolation | Only published versions affect learners | Live-edit the active graph | Authoring must not move a learner's tree under them. |
| Skill identity | Stable IDs mapped across revisions | Rebuild identities per version | Otherwise a revision orphans every learner's progress. |
| Goal to instrument | The model reads the instrument out of the goal text | Keyword match on a known-instrument list; ask the learner to pick from a dropdown | A list caps the product at what it already knows and cannot read "six-string" or "fiddle". The deterministic floor still keyword-matches, so a no-provider run is not a dead end. |
| What the model is given | The whole catalogue, as a closed vocabulary to select from | A description of the catalogue; nothing, and let it invent a syllabus | Selection from a closed vocabulary is what makes two instruments share a skill *entity* rather than two similarly-worded copies. Invention shares nothing and is different every call. |
| An invalid plan | Refused; deterministic assembly used instead | Repair it; publish it anyway; fail the request | A repaired plan is a tree nobody authored and nobody proposed. Failing the request makes a provider outage a product outage, against the deterministic-floor tenet. |
| Catalogue suggested edges | A prior that seeds the spine and informs the plan | Binding for every instrument; omitted entirely | A shared ordering that holds for rhythm and reading breaks for technique. Omitting them leaves a no-provider tree with nodes and no order. |
| Where provenance lives | `compiler_version` on the curriculum version | A new column on courses; not recorded | The column already exists and already means "how this version was built". A new column is a migration, and this change needs none. |
| Publishing a proposed tree | Published immediately, labelled | Held as a draft until a human reviews it | A tree in review teaches nobody. The honesty obligation is discharged by saying what the tree is, not by withholding it. |
| Goal-first and the compiler | Separate paths sharing one publish call | One path; the goal drives source research and the compiler | Compilation takes minutes through a queue and measures 0.397 recall today. A first tree must appear in one request. |
| Structure selection | Threshold on outline-entry count | Always infer; always trust structure | A book with a real contents page is better structure than any inference; a book without one has none. |
| Outline edge confidence | Low, and narrow in scope | One edge per entry at high confidence | Measured: the latter made half the graph a contents page and every chapter a root. |
| Sub-section segmentation | Off by default | On | Measured: better granularity, worse prerequisite precision. |
| Cycle handling | Greedy admission by confidence | Reject the graph | A partial acyclic graph is usable; a rejected one is not. |
| Task payloads | Identifiers and ranges | Content in the payload | A large book must never be a single message. |
| Reindex | Explicit administrative action | Automatic on write | Rebuilds are expensive and should be chosen. |
| Skill definition | Once, in a shared catalogue | Once per instrument | Five instruments re-authoring quarter-note reading means improving it improves none of them. |
| Specialisation surface | A fixed declared set of fields | Arbitrary overrides | Unbounded overrides reproduce standalone curricula under a shared name. |
| Edge inheritance | None; edges are the instrument's | Inherit catalogue orderings | Ordering is a pedagogical claim about a specific instrument. |
| Catalogue linkage | Recorded on every concept | Resolve and discard | The link is what makes two instruments' realisations of one skill recognisable as the same skill. |
| Course shelving | A declared list of course ids, read by the seed and the course service | A column on `courses`; a title-suffix convention; `compiler_version` | A column is a migration, and this needs none. A title suffix makes the learner's list depend on a naming habit. `compiler_version` cannot separate a shipped guitar tree from a goal-built one — assembling either runs the same code. |
| Internal courses | Kept seeded, shown to nobody | Deleted from the seed | The admin, cost-ledger and scheduling paths are developed against them; deleting them trades a clean list for a suite of tests with nothing to run on. The learner's complaint is that they are *visible*, not that they exist. |
## Open Questions & Future Decisions

### Open

- **What justifies a prerequisite edge.** Accepting an edge requires a justification, and what
  counts as one depends on where the edge came from: an edge inferred from a document owes an
  exact quote from it, while an edge drawn from the catalogue or proposed against it never read
  a document and owes a recorded rationale instead. Requiring a source quote from a tree built
  without sources would mean quoting a book nobody opened. The review gate and the publication
  gate check the same rule so they cannot disagree (`CURR-GOAL-017`). Whether a rationale is
  *enough* justification for a published edge is the live question.
- **Exercises for an instrument nothing ships.** Publication generates an exercise for every
  node, and the generator has no profile for an instrument outside the shipped set, so a cello
  tree gets exercises shaped by the default profile. They are playable and honestly labelled,
  but they are not cello exercises.
- **Two goals, two courses.** Stating the same goal twice creates two courses. Nothing dedupes
  them, because a learner restarting an instrument is a legitimate thing to want and the
  alternative silently returns a tree with someone's old progress on it.

### Deferred

1. **How the *compiler* and the catalogue meet.** Goal-first construction selects from the
   catalogue directly, so a goal-built tree's shared skills carry catalogue identity. The
   document compiler still does not: a curriculum compiled from source produces inline
   concepts that are never linked to catalogue skills they duplicate. Whether the compiler
   should propose such links for review, or seed the catalogue from what it extracts, is
   unresolved.
2. **When a shared skill should split.** A catalogue entry that accumulates overrides from
   every instrument that uses it is evidence that it was too broad, but nothing measures that
   drift.
3. **Node granularity is the central quality problem.** Recall below 0.4 is the number to
   move, and title-distinctiveness filtering is the named prerequisite for the change that
   would move it.
2. **The measurement harness and reference tree must be restored** before any published
   accuracy claim can be reproduced from this repository.
3. **The confidence ordering should be stated in one place** and asserted, rather than
   implied by constants in three modules with a comment that no longer matches.
4. **Graph replacement and learner progress need separating.** The cascade that has destroyed
   progress once is currently prevented by test coverage rather than by structure.
5. **Skill split, merge, rename and retirement across versions are unimplemented.** Without
   them a substantive revision cannot preserve progress.
6. **No review surface exists** for a candidate edge's effect on the unlock path, though the
   quote, confidence and provenance are all stored.
7. **No quality gates run before publication** — assessment coverage and a confidence floor
   are both unimplemented.
8. **Two root-level measurement modules reach into private functions of live code** and are
   protected by no test.

## References

- `docs/archive/graph_extraction_contract.md` — the live contract for the ingestion path
- `docs/archive/textbook-product.md` — the measurement history
- `docs/intent/progression/progression-design.md` — consumes the published graph
- `docs/intent/model-gateway/model-gateway-design.md` — the highest-volume model consumer

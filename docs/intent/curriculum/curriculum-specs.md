# Curriculum — EARS Specs

Prefix: `CURR`. Facets: `CAT` (shared skill catalogue), `SOURCE` (acquisition), `PARSE` (structure extraction),
`EDGE` (prerequisite inference), `GRAPH` (persistence), `VERSION` (publication),
`PROJ` (derived stores), `JOB` (background work).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Shared skill catalogue

- [x] **CURR-CAT-001**: The system shall define each shared skill once, in a catalogue keyed by a stable identifier.
- [x] **CURR-CAT-002**: An instrument curriculum shall be able to draw a concept from the catalogue by naming its identifier.
- [x] **CURR-CAT-003**: A concept drawn from the catalogue shall inherit the catalogue skill's title, summary, difficulty and key terms.
- [x] **CURR-CAT-004**: A concept drawn from the catalogue shall be able to restate its slug, title, summary, difficulty and key terms.
- [x] **CURR-CAT-005**: A concept drawn from the catalogue shall not be able to override any field outside that declared set, and the system shall name the permitted fields when refusing.
- [x] **CURR-CAT-006**: When a concept names a catalogue identifier that does not exist, the system shall refuse the curriculum and list the identifiers it knows.
- [x] **CURR-CAT-007**: The system shall record, for each concept, which catalogue skill it realises, or that it was authored inline.
- [x] **CURR-CAT-008**: A concept authored inline shall be unaffected by the catalogue.
- [x] **CURR-CAT-009**: Prerequisite edges shall be declared by the instrument curriculum, and shall not be inherited from the catalogue.
- [x] **CURR-CAT-010**: Two instruments realising the same catalogue skill shall be identifiable as realising the same skill.
- [D] **CURR-CAT-011**: The catalogue shall not define a skill that no instrument can realise physically.

## Goal-first construction

- [x] **CURR-GOAL-001**: The system shall create a playable, published curriculum from a learner's stated goal in a single request, without requiring a document, an ingest, or a background job.
- [x] **CURR-GOAL-002**: The system shall submit the learner's goal text together with the entire shared catalogue to the curriculum-planning role, so that the model selects from a closed vocabulary rather than inventing a syllabus.
- [x] **CURR-GOAL-003**: The system shall resolve the instrument from the goal text rather than requiring the learner to choose from a list.
- [x] **CURR-GOAL-004**: Where the goal names an instrument that has a published curriculum in the project, the system shall assemble that curriculum rather than asking the model for one.
- [x] **CURR-GOAL-005**: Where no instrument can be identified from the goal, the system shall refuse the request and say what was missing, rather than creating an empty or arbitrary tree.
- [x] **CURR-GOAL-006**: The system shall produce a tree for any goal with no model provider configured, drawing the shared skills and their ordering from the catalogue alone.
- [x] **CURR-GOAL-007**: The system shall reject a proposed plan naming a catalogue skill that does not exist.
- [x] **CURR-GOAL-008**: The system shall reject a proposed plan overriding a field outside the declared overridable set.
- [x] **CURR-GOAL-009**: The system shall reject a proposed plan containing duplicate concept slugs, or an edge naming a concept the plan does not define.
- [x] **CURR-GOAL-010**: The system shall reject a proposed plan whose concept count falls outside the bounds a learner can face.
- [x] **CURR-GOAL-011**: When a proposed plan is rejected, the system shall fall back to deterministic assembly and still return a playable tree, rather than failing the request or repairing the plan.
- [x] **CURR-GOAL-012**: The system shall record how each curriculum version was constructed, distinguishing assembly from a shipped curriculum, a validated model proposal, and compilation from source documents.
- [x] **CURR-GOAL-013**: The system shall report a curriculum's construction provenance to the learner who holds it.
- [x] **CURR-GOAL-014**: A goal-built curriculum shall carry catalogue identity on every concept drawn from the catalogue, so that the same skill on two instruments is the same entity.
- [x] **CURR-GOAL-015**: The catalogue shall declare suggested prerequisite edges between catalogue skills, and the system shall treat them as a prior that seeds a tree rather than as an ordering binding on every instrument.
- [x] **CURR-GOAL-017**: An accepted prerequisite edge shall carry a justification — an exact source quote where it was derived from a document, or a recorded rationale where it was not — and shall never be accepted with neither.
- [x] **CURR-GOAL-018**: Where goal-first construction asks a model for a plan, the call shall be recorded against the course it was made for, so a goal-built tree's spend is visible on that course's cost.
- [D] **CURR-GOAL-016**: Goal-first construction shall not consult a research provider, fetch a document, or enqueue background work.

## Course shelving

- [x] **CURR-SHELF-001**: The system shall label every course with the shelf it belongs on, distinguishing a course the learner created from one the project offers ready-made and from one seeded only so the system is developable offline.
- [x] **CURR-SHELF-002**: The learner's own course list shall contain only the courses they created.
- [x] **CURR-SHELF-003**: The learner shall be able to view the courses the project offers ready-made, as a set distinct from their own.
- [x] **CURR-SHELF-004**: A course's shelf shall be declared explicitly, rather than inferred from its title, description or the compiler that built its curriculum.
- [x] **CURR-SHELF-005**: A course seeded only for development shall not be offered to the learner on any shelf.
- [x] **CURR-SHELF-006**: Opening a course the project offers ready-made shall reach the same skill tree, drill loop and progression as a course the learner built.

## Source acquisition

- [x] **CURR-SOURCE-001**: The system shall accept a document upload and store its bytes content-addressed.
- [x] **CURR-SOURCE-002**: The system shall deduplicate an upload on course and content hash, returning the existing document.
- [x] **CURR-SOURCE-003**: The system shall fetch a public URL with an explicit timeout, a size ceiling, and a redirect limit.
- [x] **CURR-SOURCE-004**: The system shall refuse a URL resolving to a private or link-local address.
- [x] **CURR-SOURCE-005**: The system shall respect a site's crawling directives before fetching.
- [x] **CURR-SOURCE-006**: The system shall record the provenance of every source it ingests.
- [x] **CURR-SOURCE-007**: Where a research provider is configured, the system shall propose sources for a stated goal; approval shall be required before any ingest.

## Structure extraction

- [x] **CURR-PARSE-001**: The system shall use a document's own outline when it declares enough entries to be trusted, and shall infer structure otherwise.
- [x] **CURR-PARSE-002**: The system shall fall back to a printed contents page when no embedded outline is present.
- [x] **CURR-PARSE-003**: The system shall chunk content with overlap and record each chunk's position.
- [x] **CURR-PARSE-004**: The system shall treat a heading owning no prose of its own as structural rather than as a skill.
- [x] **CURR-PARSE-005**: The system shall extract concepts from content windows where structure is not usable.
- [x] **CURR-PARSE-006**: The system shall merge near-duplicate concepts by embedding similarity.
- [ ] **CURR-PARSE-007**: The system shall filter outline entries by title distinctiveness before section-level segmentation is enabled.
- [D] **CURR-PARSE-008**: Section-level segmentation shall remain disabled while it improves granularity at the cost of prerequisite precision.

## Prerequisite inference

- [x] **CURR-EDGE-001**: The system shall record an exact source quote as evidence for every inferred edge.
- [x] **CURR-EDGE-002**: The system shall record the extractor, prompt and source hashes that produced each edge.
- [x] **CURR-EDGE-003**: The system shall assign confidence such that agreement between forward and reverse inference outranks a single direction.
- [x] **CURR-EDGE-004**: The system shall emit a containment edge only where the containing heading is itself a skill.
- [x] **CURR-EDGE-005**: The system shall discard an inferred edge below the confidence floor.
- [x] **CURR-EDGE-006**: Given identical input, prerequisite inference shall produce an identical edge set.
- [ ] **CURR-EDGE-007**: The relative confidence ordering between edge kinds shall be declared in one place and asserted, rather than implied by constants in separate modules.

## Graph persistence

- [x] **CURR-GRAPH-001**: Persisting a graph shall replace the course's previous nodes and edges.
- [x] **CURR-GRAPH-002**: Persisting a graph shall preserve every learner's experience, mastery and review history for nodes that survive the replacement.
- [x] **CURR-GRAPH-003**: The system shall map stable skill identifiers across revisions.
- [x] **CURR-GRAPH-004**: The system shall reject a graph containing a cycle.
- [ ] **CURR-GRAPH-005**: Graph replacement shall be incapable of deleting learner progress by cascade, by construction rather than by test coverage.
- [ ] **CURR-GRAPH-006**: The system shall support explicit split, merge, rename and retirement of a skill across versions.

## Versioning and publication

- [x] **CURR-VERSION-001**: A curriculum version shall be immutable once published.
- [x] **CURR-VERSION-002**: A draft version shall not affect any learner's unlocks, experience, scheduling or quests.
- [x] **CURR-VERSION-003**: The system shall present each candidate edge for review with its quote, confidence and provenance.
- [x] **CURR-VERSION-004**: The system shall record every review decision, including rejections and their reasons.
- [x] **CURR-VERSION-009**: A recorded rejection shall carry the confidence, support and rationale the edge was proposed with, so a reviewer can judge whether the compiler or the extractor was wrong.
- [x] **CURR-VERSION-010**: An edge the compiler refused while constructing a curriculum shall appear in that course's rejection record, so refusals are visible whichever construction path built the tree.
- [x] **CURR-VERSION-005**: Publication shall generate an exercise for each node that lacks one.
- [x] **CURR-VERSION-011**: Publication shall generate a graded run of lessons for each playable node, differing in tempo and length rather than in name, so a skill has ground between never attempted and mastered.
- [x] **CURR-VERSION-006**: The system shall compile a curriculum from source data with no instrument-specific code path.
- [ ] **CURR-VERSION-007**: Publication shall be refused where assessment coverage or edge confidence falls below a declared gate.
- [ ] **CURR-VERSION-008**: A reviewer shall be shown which unlock paths a candidate edge would change.

## Derived stores

- [D] **CURR-PROJ-001**: Neither the graph store nor the vector store shall receive an authoritative write.
- [x] **CURR-PROJ-002**: The system shall rebuild both derived stores from the relational store on demand.
- [x] **CURR-PROJ-003**: The system shall report the staleness of each projection.
- [x] **CURR-PROJ-004**: The system shall remain able to serve traversal and retrieval while a projection is stale.
- [x] **CURR-PROJ-005**: The system shall answer questions with citations to the chunks that support them.
- [x] **CURR-PROJ-006**: Where no vector store is reachable, retrieval shall fall back to lexical search rather than failing.

## Background work

- [x] **CURR-JOB-001**: A background task shall carry identifiers and ranges, never document content.
- [x] **CURR-JOB-002**: A background task shall contain no business logic beyond loading, delegating and recording.
- [x] **CURR-JOB-003**: The system shall report ingest progress as a proportion with a stage description.
- [x] **CURR-JOB-004**: The system shall deduplicate a re-submitted ingest on its idempotency key.
- [x] **CURR-JOB-005**: The system shall bound a task's runtime and mark its job failed when the bound is exceeded.
- [ ] **CURR-JOB-006**: A caller shall be able to cancel a running ingest.

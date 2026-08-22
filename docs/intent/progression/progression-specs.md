# Progression — EARS Specs

Prefix: `PROG`. Facets: `DAG` (graph rules), `SRS` (scheduling),
`EXP` (experience and levels), `STATE` (node state), `QUEST` (the daily board),
`META` (character, cohort, sharing).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Graph rules

- [x] **PROG-DAG-001**: The domain layer shall import nothing from the rest of the application.
- [x] **PROG-DAG-002**: The system shall admit candidate edges in descending order of confidence, rejecting any edge that would close a cycle.
- [x] **PROG-DAG-003**: The system shall record every rejected edge with its reason.
- [x] **PROG-DAG-004**: The system shall compute topological depth for every node.
- [x] **PROG-DAG-005**: The system shall present a transitively reduced edge set.
- [x] **PROG-DAG-006**: The system shall reject a graph containing a duplicate slug or an edge naming an unknown node.
- [x] **PROG-DAG-007**: Given identical candidates, graph construction shall produce an identical graph.
- [ ] **PROG-DAG-008**: The prerequisite-satisfaction traversal shall have exactly one implementation.

## Scheduling

- [x] **PROG-SRS-001**: Every scheduling function shall receive the current time as a parameter.
- [x] **PROG-SRS-002**: The scheduler shall accept an injectable jitter source so its output is reproducible under test.
- [x] **PROG-SRS-003**: The system shall lengthen a review interval on success and collapse it on failure.
- [x] **PROG-SRS-004**: The system shall apply jitter to scheduled intervals so a cohort seeded together does not remain synchronised.
- [x] **PROG-SRS-005**: The system shall compute proficiency as a function of elapsed time since the last review.
- [D] **PROG-SRS-006**: No proficiency, mastery or node-state value shall be stored in the database.

## Experience and levels

- [x] **PROG-EXP-001**: The system shall award experience for a graded attempt.
- [x] **PROG-EXP-002**: The system shall award experience for an attempt exactly once, regardless of repeated grading.
- [x] **PROG-EXP-003**: The system shall derive node level and account level from accumulated experience on a published curve.
- [x] **PROG-EXP-004**: The system shall cap node level at the defined maximum.
- [x] **PROG-EXP-005**: The system shall award a bonus for recovering a decayed skill.
- [ ] **PROG-EXP-006**: The documented level thresholds shall match those the implementation produces.
- [ ] **PROG-EXP-007**: Per-node and account-wide experience shall be reconcilable from stored data.

## Node state

- [x] **PROG-STATE-001**: The system shall derive node state on read from the last review time, interval and ease.
- [x] **PROG-STATE-002**: While any prerequisite sits below the prerequisite mastery threshold, the system shall report a node as locked.
- [x] **PROG-STATE-003**: When a node reaches both the mastery threshold and the level cap, the system shall report it as mastered.
- [x] **PROG-STATE-004**: As proficiency falls with elapsed time, the system shall report a node as decaying.
- [x] **PROG-STATE-005**: The system shall treat a structural heading as transparent for gating and as not assessable.
- [x] **PROG-STATE-006**: The system shall report why a node is locked, naming the prerequisites responsible.
- [ ] **PROG-STATE-007**: The mastery threshold shall be 0.85, defined once and used by every surface that reports mastery.

## Opening a lesson

- [x] **PROG-DRILL-001**: A learner shall be able to open a skill's lesson directly from the skill tree, without first selecting the skill and then operating a separate control.
- [x] **PROG-DRILL-002**: Opening a lesson from the tree shall also select that skill, so the tree, the inspector and the lesson never show different skills.
- [x] **PROG-DRILL-003**: The system shall not open a lesson for a structural heading, which owns no skill to drill.
- [x] **PROG-DRILL-004**: The system shall not open a lesson for a skill whose prerequisites are unmet; selecting such a skill shall still report what is blocking it.
- [x] **PROG-DRILL-005**: Opening a lesson for the skill whose lesson is already open shall not discard an answer in progress.

## The daily board

- [x] **PROG-QUEST-001**: The system shall partition the board into decayed work and new ground at the unlocked frontier.
- [x] **PROG-QUEST-002**: The system shall order each partition by a total order, so that repeated reads of unchanged data return the same board.
- [x] **PROG-QUEST-003**: The system shall weight an overdue quest above a fresh one.
- [x] **PROG-QUEST-004**: The system shall bound the board's size.
- [x] **PROG-QUEST-005**: The system shall state a reason for each quest it offers.
- [x] **PROG-QUEST-006**: The system shall compute the board on read rather than from a stored table.

## Character, cohort and sharing

- [x] **PROG-META-001**: The system shall report a character sheet of stats, perks and achievements derived from progression.
- [x] **PROG-META-002**: The system shall award perk points on level gain and shall not award them twice for the same level.
- [x] **PROG-META-003**: The system shall report a cohort leaderboard for a shared course.
- [x] **PROG-META-004**: Copying a shared course shall be idempotent per learner.
- [x] **PROG-META-005**: A copied course shall carry its own progression, independent of the original.
- [ ] **PROG-META-006**: A day on which the learner completed a graded instrument take shall continue their streak, equally with a drill attempt.
- [ ] **PROG-META-007**: The system shall compute a learner's streak in exactly one place.

## Skill realms

- [x] **PROG-REALM-001**: A skill's lesson run and the learner's progress on it shall be readable in a single request for a whole course.
- [x] **PROG-REALM-002**: A lesson shall be cleared at the same score the rest of the system treats as a pass, shall be judged on the learner's best take rather than their latest, and shall remain replayable once cleared.
- [x] **PROG-REALM-003**: A skill's test shall open only when every lesson in its run is cleared, and a skill with no lessons shall not have an open test.
- [x] **PROG-REALM-004**: Opening a skill shall enter its realm, and the realm shall show the run as a chain ending in that test.
- [ ] **PROG-REALM-005**: Passing a skill's test shall be the moment the skill reads as complete in the tree, without the realm keeping its own record of that.
- [x] **PROG-REALM-006**: A lesson shall be playable from inside the realm, rather than from a panel beside the tree.

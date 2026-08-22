---
parent: high-level-design
prefix: PROG
---

# Progression

## Context and Design Philosophy

Progression is the reason a learner returns tomorrow. It owns the skill graph's traversal
rules, the spaced-repetition schedule, experience and levels, node state, daily quests, and
the character layer that sits on top of them.

**Nothing time-derived is stored.** Mastery, proficiency and node state are computed on read
from the last review time, the interval and the ease factor. Storing them would guarantee
drift the moment a threshold changed, and would require a scheduled job to keep rows honest
as the clock moves. The consequence is a hard rule: no column in this segment holds a value
that time alone can change.

**The domain layer imports nothing.** The graph algorithms, the scheduler, the experience
curve and the state machine depend on no framework, no database and no configuration. This
is what lets the rules that matter most be tested in milliseconds with nothing running.

**Time enters as a parameter.** Every function that depends on the clock receives `now` from
its caller, and the scheduler's jitter is an injectable callable. A schedule that reads the
clock itself can only be tested by waiting.

**One progression system.** Anything that awards, unlocks or schedules goes through this
segment. A second one would mean two answers to what a learner knows.

## Graph rules

`domain/dag.py` builds an acyclic edge set from candidates by admitting greedily in
descending confidence, rejecting any edge that would close a cycle and recording why.
Rejections stay auditable rather than disappearing. It also computes topological depth and a
transitive reduction, so a tree shows the edges that carry information rather than every
edge implied by transitivity.

## Scheduling and state

`domain/srs.py` implements SM-2 style scheduling: an ease factor adjusted by grade, an
interval that grows with successful reviews and collapses on failure, and jitter so a cohort
seeded together does not come due together forever.

`domain/states.py` derives node state on read. A node is locked while its prerequisites sit
below the prerequisite mastery threshold; mastered once it reaches both the mastery
threshold and the level cap; decaying as proficiency falls with elapsed time.

`domain/exp.py` maps experience to level on a power curve, both per node and per account.

## Quests

The daily board partitions into overdue work — nodes whose proficiency has decayed — and new
ground at the frontier of what is unlocked. Both partitions sort to a **total** order: an
ordering with ties is unstable under an unordered query, so a capped board would silently
reshuffle between two reads of identical data.

## Structural nodes

A heading that owns no prose of its own is transparent rather than free: it does not gate
its children, and it is not assessable. Otherwise a table of contents becomes a prerequisite
chain and every chapter becomes a root.

## Current state versus intent

**Two attempt lineages exist and never join.** `Attempt` drives drill grading, account
progress and leaderboard streaks. `PerformanceAttempt` drives instrument practice, its
metric bundles and its webhooks. They share the `schemas.progress` namespace and no join.
The visible consequence: **leaderboard streaks count only drill attempts, so a learner who
practises an instrument daily has a streak of zero.**

**Three streak computations are reachable** — one inline over `Attempt` in the social
service, one in the auth service consumed by the quest board, and one in the interface
header. Nothing reconciles them.

**Two definitions of "mastered" disagree.** `domain/states.py:31` sets the mastery threshold
at 0.85 and the course service imports it. `character_service.py:34` hardcodes `0.8`. A
learner at mastery 0.82 and level 5 is mastered on their character sheet and not mastered on
their skill tree at the same instant.

**Three prerequisite walks disagree on a default.** The graph read service, the campaign
service and the domain state module each implement the "are this node's prerequisites
satisfied?" traversal independently, and they differ on what to assume when a node's
assessability is unknown. Note that the *pure* module owns graph construction; the traversal
that decides unlocking lives in the service layer, in triplicate.

**Two experience counters have no database linkage.** Per-node experience and account-wide
total are kept consistent entirely by service code.

**Read endpoints write.** `ensure_progress_rows` is called on the path and quest read paths,
so two GET-shaped endpoints create rows.

**The documented level curve is wrong.** `exp.py:58` states thresholds of 0, 100, 303, 623,
1057; the implementation yields 0, 100, 303, 580, 919.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Time-derived values | Computed on read | Stored and refreshed by a job | Storage guarantees drift when a threshold changes, and needs a cron to stay honest. |
| Domain dependencies | None | Import config and models | Dependency-free is what makes the core rules testable with nothing running. |
| Clock access | `now` passed in; jitter injectable | Read the clock internally | Otherwise the only way to test decay is to wait days. |
| Cycle resolution | Greedy by descending confidence, rejections recorded | Reject the whole graph; drop silently | A partial graph is useful; a silent drop is unauditable. |
| Tree edges | Transitive reduction | Every implied edge | A reduced graph shows the edges that carry information. |
| Structural headings | Transparent, non-assessable | Gate children; or omit entirely | Otherwise a contents page becomes a dependency chain. |
| Review scheduling | SM-2 with jitter | Fixed intervals | Without jitter a cohort seeded together comes due together forever. |
| Quest ordering | Total order | Sort by primary key only | A tie under an unordered query reshuffles a capped board between identical reads. |
| Award idempotency | Grading a graded attempt returns the stored result | Award on every call | Otherwise a retry pays twice. |
| System count | Exactly one progression system | Separate instrument progression | Two systems mean two answers to what a learner knows. |
| Mastery threshold | 0.85, defined once in the domain layer | 0.80; per-surface thresholds | One definition, or two surfaces answer the same question differently for the same learner. |
| What continues a streak | Any practice, instrument or drill | Drill attempts only | Practising the instrument is the product's primary activity; a streak that ignores it measures the wrong thing. |

## Open Questions & Future Decisions

### Deferred

1. **How** streaks and account progress come to count instrument practice — unify the two
   attempt lineages, or read both. *Decided:* a day on which the learner practised their
   instrument continues their streak. Today it does not, which makes the streak actively
   misleading for the product's primary activity.
2. **How** a single mastery definition is enforced so a third copy cannot appear. *Decided:*
   the threshold is 0.85, the value the domain layer already holds; the hardcoded 0.8 in the
   character service is the defect.
3. **Should the prerequisite walk move into the domain layer?** It is the product's central
   rule and the one piece of graph logic that is not in the dependency-free module.
4. **No retention validation exists.** The decay curve, the experience economy and the quest
   board have never been measured against whether learners actually retain. The time-travel
   script exists to make that measurable.
5. **The meta-game is thin.** Perks, achievements, campaigns and cohort leaderboards all ship
   and none are tuned.
6. **Read-path writes** should either be acknowledged as a documented behaviour or moved.

## References

- `docs/srs_and_exp.md` — the scheduling and experience rationale
- `docs/intent/evaluation/evaluation-design.md` — supplies graded outcomes
- `docs/intent/curriculum/curriculum-design.md` — supplies the graph this segment traverses

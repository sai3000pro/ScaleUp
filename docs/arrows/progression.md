# Arrow: progression

Graph traversal, spaced repetition, experience, node state, the daily board, and the
character layer above them. The reason a learner returns tomorrow.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). The domain layer is
dependency-free and time-injected throughout. Two attempt lineages exist and never join, and
two surfaces disagree on what "mastered" means.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/progression/progression-design.md`

### EARS
- `docs/intent/progression/progression-specs.md` (52 specs)

### Tests
- `backend/tests/unit/test_realm.py` — walking a lesson run and earning its test
- `backend/tests/unit/test_dag.py`, `test_srs.py`, `test_exp.py`, `test_states.py`, `test_character.py`, `test_trend.py`
- `backend/tests/integration/test_quests.py`, `test_drill_flow.py`, `test_leaderboard.py`, `test_course_sharing.py`
- `frontend/lib/lesson.test.ts` — when a skill can be worked on

### Code
- `frontend/components/skill-tree/SkillRealm3D.tsx` — the lesson chain and its test
- `backend/app/domain/realm.py` — when a lesson clears and when a test opens
- `frontend/lib/lesson.ts` — the lesson-opening rule, pure
- `frontend/components/drill/DrillPanel.tsx` — the lesson itself, and its auto-start
- `backend/app/domain/` — `dag.py`, `srs.py`, `exp.py`, `states.py`, `character.py`, `trend.py`
- `backend/app/services/` — `quest_service.py`, `progress_service.py`, `path_service.py`, `drill_service.py`, `character_service.py`, `campaign_service.py`, `social_service.py`
- `frontend/components/skill-tree/`, `frontend/app/quests/`, `frontend/app/character/`

## Architecture

**Purpose:** Decide what is unlocked, what has decayed, what is worth doing today, and what
it was worth — computing every time-derived value on read.

**Key Components:**
1. `domain/dag.py` — acyclic construction, topological depth, transitive reduction, recorded rejections.
2. `domain/srs.py` — SM-2 style scheduling with injectable jitter.
3. `domain/states.py` — node state derived on read from last review, interval and ease.
4. `domain/exp.py` — experience to level, per node and per account.
5. `quest_service.py` — the daily board, totally ordered.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Graph rules | `PROG-DAG-001` – `008` | 7 | 0 | 1 |
| Scheduling | `PROG-SRS-001` – `006` | 5 | 1 | 0 |
| Experience | `PROG-EXP-001` – `007` | 5 | 0 | 2 |
| Node state | `PROG-STATE-001` – `007` | 6 | 0 | 1 |
| Daily board | `PROG-QUEST-001` – `006` | 6 | 0 | 0 |
| Character and cohort | `PROG-META-001` – `007` | 5 | 0 | 2 |
| Opening a lesson | `PROG-DRILL-001` – `005` | 5 | 0 | 0 |
| Skill realms | `PROG-REALM-001` – `006` | 4 | 0 | 2 |

**Summary:** 43 of 52 implemented; 1 deliberate non-want; 8 active gaps.

## Key Findings

1. **Two attempt lineages never join.** `Attempt` drives drill grading, account progress and
   leaderboard streaks; `PerformanceAttempt` drives instrument practice, its metric bundles and
   its webhooks. They share the `schemas.progress` namespace and no join. **A learner who
   practises their instrument daily has a streak of zero** (`PROG-META-006`).

2. **Three streak computations are reachable** — one inline over `Attempt` in the social
   service, one in the auth service consumed by the quest board, and one in the interface
   header. Nothing reconciles them (`PROG-META-007`).

3. **Two definitions of "mastered" disagree.** `domain/states.py:31` sets the mastery
   threshold at 0.85 and the course service imports it; `character_service.py:34` hardcodes
   `0.8`. A learner at mastery 0.82 and level 5 is mastered on their character sheet and not
   mastered on their skill tree at the same instant (`PROG-STATE-007`).

4. **Three prerequisite walks disagree on a default.** The graph read service, the campaign
   service and the domain state module each implement the unlock traversal independently and
   differ on what to assume when a node's assessability is unknown. The *pure* module owns
   graph construction; the traversal that decides unlocking lives in the service layer, in
   triplicate (`PROG-DAG-008`).

5. **The documented level curve is wrong.** `exp.py:58` states thresholds of 0, 100, 303,
   623, 1057; the implementation yields 0, 100, 303, 580, 919 (`PROG-EXP-006`).

6. **The domain layer is genuinely dependency-free** — verified: all seven modules import only
   the standard library, with one intra-package import. Time is a parameter everywhere,
   including injectable jitter. This is the segment's strongest property and the reason its
   rules test in milliseconds.

7. **The daily board is totally ordered**, so repeated reads of unchanged data return the same
   board — a property that was not previously true and is now asserted.

## Work Required

### Must Fix
1. Make 0.85 the single mastery definition (`PROG-STATE-007`). `character_service.py:34`'s
   hardcoded `0.8` is the defect; the domain value is correct.
2. Count a graded instrument take toward the streak (`PROG-META-006`). A learner practising
   their instrument daily currently has a streak of zero, which makes the streak actively
   misleading about the product's primary activity.

### Should Fix
3. Choose the mechanism for the above — unify the two attempt lineages, or read both — and
   collapse the three streak computations to one (`PROG-META-007`).
4. Reduce the prerequisite walk to one implementation, ideally in the domain layer
   (`PROG-DAG-008`).
5. Correct the documented level curve (`PROG-EXP-006`).

### Consider
6. Validate the decay curve and experience economy against real retention, using the
   time-travel script.
7. Make per-node and account-wide experience reconcilable from stored data (`PROG-EXP-007`).

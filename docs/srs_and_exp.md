# Spaced Repetition, Decay, and EXP

**Owner:** `backend/app/domain/srs.py`, `backend/app/domain/exp.py`, `backend/app/domain/states.py`
**Consumer:** `grading_service`, `GET /api/courses/{id}/graph`, `GET /api/quests/daily`,
and `frontend/lib/skill-tree/nodeState.ts` (which mirrors `states.py`)

Everything here is a pure function. No database, no clock reads inside the
functions themselves — `now` is always a parameter, which is what makes the
whole system testable without a time machine.

---

## The central design decision: nothing time-derived is stored

`node_progress` stores only facts about the **last review**: `ease`,
`interval_days`, `reps`, `lapses`, `last_reviewed_at`, `due_at`, `mastery`, `exp`,
`level`.

`proficiency` and `state` are computed on read, every time. This means:

- Decay is continuous. A node fades smoothly as the clock moves rather than
  stepping only when something touches its row.
- No nightly cron job exists to keep rows fresh, and none can fall behind.
- Changing a threshold changes the whole app instantly, with no backfill and no
  risk of stored values disagreeing with the new rule.

---

## Score → SM-2 quality

The grader returns `score ∈ [0, 1]`. SM-2 wants a 0–5 quality:

```
q = floor(5 * score + 0.5)     # half UP, not Python's round()
pass = q >= 3                  # i.e. score >= 0.5
```

**Round half up, deliberately.** Python's built-in `round` is banker's rounding,
so `round(2.5) == 2` — using it would put the real pass boundary at 0.6 while
every document here says 0.5. A learner scoring exactly half marks would fail and
nothing in the code would look wrong.

## Scheduling (`domain/srs.py`)

Ease is updated **before** it is applied, so a strong answer widens its own next
gap rather than the one after it. SM-2's original write-up is ambiguous about the
ordering; this matches Anki and is the more intuitive reading of "you did well,
so wait longer".

```
PASS (q >= 3):
    reps          += 1
    ease           = clamp(ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02), 1.3, 2.8)
    interval_days  = 1                      if reps == 1
                     6                      if reps == 2
                     interval_days * ease   otherwise   (the NEW ease)

FAIL (q < 3):
    reps           = 0
    lapses        += 1
    interval_days  = 0.5                    # back tomorrow morning
    ease           = max(1.3, ease - 0.20)

BOTH:
    interval_days  = min(interval_days, 180)          # nothing sleeps for two years
    jitter         = uniform(0.9, 1.1)
    due_at         = now + timedelta(days=interval_days * jitter)
    last_reviewed_at = now
```

**The jitter is not cosmetic.** Without it, a user who ingests a course and
drills thirty nodes on day one gets all thirty back on day two, then all thirty
on day eight, then all thirty on day twenty — a lumpy, punishing board. ±10%
spreads them out. It is the difference between a quest board that feels like a
daily habit and one that feels like a wall.

`jitter` is injected as a parameter so tests can pass `lambda: 1.0`.

## Mastery and proficiency

Scheduling and *displayed* proficiency are deliberately separate concerns:

```
mastery = clamp(0.6 * mastery_prev + 0.4 * score, 0, 1)     # EMA. Does not decay.

proficiency(now) = mastery * 2 ** (-elapsed_days / half_life)
half_life        = max(interval_days, 0.5)
```

One teachable invariant falls out: **proficiency halves every review interval.**
At the exact moment a node comes due, its ring is half full. That is legible to
the user ("this is fading"), trivially computable, and needs no maintenance job.

`mastery` is what the scheduler and the unlock rules reason about; `proficiency`
is what the UI draws. Keeping them separate means a long interval doesn't
retroactively make a well-learned node look unlearned.

---

## Node states (`domain/states.py`)

Evaluated in order; first match wins.

| State | Condition |
|---|---|
| `locked` | any prerequisite has `mastery < 0.5` (or has no progress row at all) |
| `decaying` | `due_at` is in the past |
| `mastered` | `level >= 5` and `mastery >= 0.85` |
| `learning` | `reps > 0` |
| `available` | otherwise (prerequisites met, never drilled) |

`decaying` is checked before `mastered` on purpose: a mastered node that has gone
overdue *should* read as decaying. That urgency is the entire retention mechanic —
if mastery were permanent the Daily Quest board would have nothing to say.

The frontend mirrors this function in `lib/skill-tree/nodeState.ts` rather than
trusting a server-sent string alone, so optimistic updates after a grade can
recolour a node before the next fetch. The server's value is authoritative on
reconcile.

---

## EXP and levels (`domain/exp.py`)

```
DIFFICULTY_MULT = {1: 0.7, 2: 0.85, 3: 1.0, 4: 1.2, 5: 1.4}

rescue_bonus = 1 + 0.5 * min(1.0, overdue_days / max(interval_days, 0.5))
first_pass   = 50 if this is the first ever passing attempt on this node else 0

exp_awarded  = round(100 * score * DIFFICULTY_MULT[difficulty] * rescue_bonus) + first_pass
```

**The rescue bonus is the mechanic that makes the Daily Quest board worth
clearing.** Rescuing a badly decayed node pays up to 1.5×, so the board is not a
chore list competing with new content — it is the highest-EXP thing on screen.
Without it, players rationally ignore review, which defeats the product.

Node levels cap at 5:

```
exp_for_node_level(L) = round(100 * L ** 1.6)     # 0, 100, 303, 623, 1057
NODE_LEVEL_CAP = 5
```

Account level uses the same curve at 10× scale over `users.total_exp`, which is
maintained incrementally in the same transaction as the attempt.

**The client never computes EXP.** It *displays* what the server awarded, and
`applyGrade` in the progress store is an optimistic echo of the response, not an
independent calculation.

---

## Daily Quests

Computed per request; there is no `quests` table in stage 1.

1. **Overdue** (up to 8): every node across all the user's courses with
   `due_at < now`, ranked by how badly overdue it is *relative to its own
   interval* — `overdue_days / max(interval_days, 0.5)` descending, then by
   `depth` ascending. Ranking by absolute overdue days would let one ancient
   90-day node permanently outrank ten freshly-lapsed ones.
2. **Frontier** top-up (up to 3, only if fewer than 3 overdue): nodes in state
   `available` with `reps == 0`, shallowest `depth` first.

A new user must never open an empty quest board, which is why the top-up exists.

`streak_days` counts distinct dates with at least one attempt, walking backwards
from today until a gap.

---

## Testing this

`scripts/timewarp.py` rewinds `last_reviewed_at` and `due_at` for a user:

```powershell
cd backend
.\.venv\Scripts\python.exe ..\scripts\timewarp.py --email dev@local --days 30
```

**You cannot test spaced repetition without a time machine.** Build this script
before the SRS milestone, not after. The end-to-end assertion for the whole
retention system is: drill a node to `mastered`, rewind 30 days, reload the tree,
and watch it read `decaying` and appear at the top of the quest board with a
rescue bonus attached.

Unit tests worth writing (all pure, all fast, no Docker):

- SM-2 transitions across pass/lapse sequences, including the `ease` floor at 1.3
  and the 180-day interval cap.
- `proficiency(t = interval_days) == mastery / 2` within 1e-9 — the invariant.
- The node-state truth table, including the case that catches people: a
  `mastered` node that has gone overdue must report `decaying`, not `mastered`.
- `rescue_bonus` is exactly 1.0 at zero overdue and clamps at 1.5.

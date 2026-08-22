# Arrow: coaching

Metrics become language: an examiner's written assessment after a take, and short spoken
corrections during one.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). The live socket, the turn policy,
the examiner and the voice seam all ship and are reachable from the interface. One cue kind
is unreachable; a live take is pinned to one process.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/coaching/coaching-design.md`

### EARS
- `docs/intent/coaching/coaching-specs.md` (48 specs)

### Tests
- `backend/tests/unit/test_coach_policy.py`, `test_feedback.py`, `test_voice.py`
- `backend/tests/integration/test_coach_stream.py`

### Code
- `backend/app/domain/coach_policy.py` — pure, time-injected turn policy
- `backend/app/services/coach_service.py` — WebSocket session
- `backend/app/evaluation/feedback.py` — deterministic examiner and metric interpretation
- `backend/app/services/voice.py` — synthesis, batch and streaming
- `backend/app/prompts/performance_feedback/v2.md`
- `frontend/lib/coachSocket.ts`, `frontend/components/course/LiveCoachPanel.tsx`

## Architecture

**Purpose:** Say the one useful thing, at a moment the learner can hear it, in an examiner's
voice — and never change a number while doing it.

**Key Components:**
1. `coach_policy.py` — whether to speak, about what, how insistently; pure, time as a parameter.
2. `feedback.py` — metric interpretation to words, polarity table, deterministic examiner.
3. `coach_service.py` — protocol, session state, streaming, finalisation through the standard attempt path.
4. `voice.py` — ElevenLabs behind a seam; content-addressed for batch, sentence-at-a-time for live.
5. `LiveCoachPanel.tsx` — rendered at `courses/[courseId]/page.tsx:287`.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Turn policy | `COACH-POLICY-001` – `011` | 10 | 1 | 0 |
| Cue selection | `COACH-CUE-001` – `008` | 8 | 0 | 0 |
| Examiner | `COACH-EXAM-001` – `009` | 8 | 1 | 0 |
| Voice | `COACH-VOICE-001` – `008` | 8 | 0 | 0 |
| Live session | `COACH-SESSION-001` – `012` | 11 | 1 | 0 |

**Summary:** 45 of 48 implemented; 3 deliberate non-wants; 0 active gaps.

## Key Findings

1. **A learner can never be told they are flat.** `coach_policy.py:193` selects between sharp
   and flat with `pitch_error > 0`, but reaches that line only when `pitch_error >= 0.45`, and
   the underlying metric is a magnitude that is never negative. `CueKind.FLAT_PITCH` is
   unreachable, so every pitch cue says sharp — including when the learner is flat. The timing
   branch four lines below reads a *signed* value and separates rushing from dragging
   correctly, so the distinction was understood on one axis and lost on the other
   (`COACH-CUE-006`).

2. **Fixing that is a cross-segment cascade.** Signed pitch error is a change in `evaluation`,
   not here. Flagged rather than propagated.

3. **The intonation ladder is decided at 20 to coach, 30 to fail** — warning before penalty
   is deliberate. The remaining defect is the spoken sentence, which says "a quarter-tone"
   (50 cents) while triggering at 20, and so overstates what it measured
   (`COACH-CUE-007`, `COACH-CUE-008`).

4. **A live take is pinned to one process.** The cross-instance guard in `coach_service.py` is
   a process-local dictionary and cannot see a take held by another replica
   (`COACH-SESSION-012`).

5. **The policy is the best-specified pure module in the system.** Imports nothing outside the
   standard library, takes time and silence as parameters, returns an explicit suppression
   reason when it declines. Ten of eleven specs implemented, and every constant in it is
   trivially testable — and none have been tuned against a real learner.

6. **The one-grading-path property holds and is tested.** Finalisation submits through the
   standard attempt path under a take-derived idempotency key, and an integration test pins
   the streamed take and the clip path to identical metric bundles.

7. **No evaluation harness reads the prompt ledger.** Every call records prompt identifier,
   version and hash specifically so prompt changes are measurable. Nothing measures them.

## Work Required

### Must Fix
1. Distinguish flat from sharp (`COACH-CUE-006`) — requires signed pitch error from
   `evaluation`. Until then the coach is confidently wrong half the time it mentions pitch.

### Should Fix
2. Correct the spoken intonation sentence to describe the deviation actually detected
   (`COACH-CUE-008`), and assert the coach-before-fail ordering (`COACH-CUE-007`).
3. Sticky sessions, or a shared take store, so live coaching survives a second replica
   (`COACH-SESSION-012`).

### Consider
4. Tune the policy constants against real takes — silence minimum, spacing, per-take cap,
   cooldown, rushing and dragging thresholds. All are estimates.
5. Build a prompt evaluation harness over the existing ledger.
6. Ask how often learners talk over the coach; barge-in is already recorded distinctly.

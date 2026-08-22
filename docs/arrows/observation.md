# Arrow: observation

Reduction of raw sensor streams — pitch frames and pose/hand landmarks — into typed,
explainable observations that the grader is permitted to see.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). Reverse-engineered from code
during brownfield bootstrap. Design and specs describe current reality; two of the three
reducers in this segment have no production caller.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/observation/observation-design.md`

### EARS
- `docs/intent/observation/observation-specs.md` (35 specs)

### Tests
- `frontend/lib/noteSegmentation.test.ts`
- `frontend/lib/posture.test.ts`

### Code
- `frontend/lib/noteSegmentation.ts` (334 lines)
- `frontend/lib/posture.ts` (599 lines)
- `frontend/lib/technique.ts` (223 lines)
- `frontend/stores/usePostureStore.ts` (102 lines)
- `backend/app/evaluation/posture.py` (93 lines)

## Architecture

**Purpose:** Turn sensor streams into observations that carry their own confidence, so an
unreliable measurement can never reach the grader as a confident number.

**Key Components:**
1. `noteSegmentation.ts` — pure fold from pitch frames to note segments; hysteresis on both
   confidence and level, re-attack detection, median pitch with a separate cents residual.
2. `posture.ts` — pure reducer from 33 body landmarks to per-instrument metrics; scale
   normalisation, visibility and coverage gating, versioned thresholds, clamped calibration.
3. `technique.ts` — the same shape for 21 hand landmarks; wrist elevation and hand stability.
4. `usePostureStore.ts` — take-scoped accumulation; median per key, worst status, bounded.
5. `evaluation/posture.py` — server-side reduction to one accuracy, or to unmeasured.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Note segmentation | `OBS-NOTE-001` – `011` | 10 | 1 | 0 |
| Posture | `OBS-POSE-001` – `012` | 10 | 1 | 1 |
| Hand technique | `OBS-HAND-001` – `004` | 3 | 1 | 0 |
| Take reduction | `OBS-RED-001` – `008` | 7 | 0 | 1 |

**Summary:** 30 of 35 specs observed working; 3 deliberate non-wants; 2 active gaps.

The reducers here are almost entirely correct and almost entirely unreachable — but that is
a *producer* problem, so it is tracked in `capture` (`CAP-MIC-008`, `CAP-CAM-006`,
`CAP-CAM-008`) rather than counted against this segment.

## Key Findings

0. **A rule set reached by omission is not a rule set.** An instrument with no entry in the
   posture table silently received the three shared rules and none of the ones that make its
   technique its own — which is what happened to banjo, an instrument that routes to the
   guitar *evaluator* and so looks fully supported from every other angle. `OBS-POSE-013`
   makes the declaration mandatory and a test enforces it against the shipped curricula.


1. **The tested segmenter is not the running segmenter.** `noteSegmentation.ts` is imported
   only by its own test. The live path uses an inline reimplementation in
   `frontend/lib/pitchDetection.ts:246-291`, which declares a second `NoteSegment` interface
   at line 23 with a different shape (no `cents_deviation`, `peak_level_db`, `mean_level_db`)
   and restates three constants as literals. Test coverage here measures code nobody runs.

2. **The posture engine has no producer.** No MediaPipe Pose landmarker is constructed
   anywhere in `frontend/`. `usePostureStore.ts:3` imports two version strings from
   `posture.ts` and nothing else; `reducePosture`, `POSTURE_RULES`, `calibrateThresholds`
   and all 16 rules have no production caller.

3. **Even the hand path is fed from fixtures.** `TechniquePanel` writes to the posture store
   only from its mock branch, never from the live camera stream.

4. **`grip_openness` is a threshold with no rule.** `posture.ts:86` declares the band; no
   rule computes the metric.

5. **`threshold_version` is accepted and discarded.** `PostureObservationIn.threshold_version`
   has no destination column in `performance_metric_bundles`, which persists only
   `posture_version` — defeating the versioning the retune story depends on.

6. **The honesty discipline holds throughout.** Visibility gating, coverage gating,
   `None`-not-zero, and weight redistribution are consistent across both the client
   reducers and the server reduction. This is the segment's strongest property.

## Work Required

### Must Fix
1. Persist `threshold_version` (`OBS-RED-008`) or withdraw it from the wire contract.

### Blocked on `capture`
2. Every reducer here is correct and unreachable until `capture` supplies producers:
   `CAP-MIC-008` (route the recorder through this segmenter), `CAP-CAM-006` (body-pose
   landmarker), `CAP-CAM-008` (live technique sampling). Until then the tests in this segment
   measure code nobody runs.

### Should Fix
3. Implement `grip_openness` or withdraw its threshold (`OBS-POSE-012`).
4. Calibrate the 16 posture bands and the seven estimated segmenter constants against real
   takes. Every one is currently an initial guess.

### Consider
5. Name the bare `0.7` good-cutoff, repeated as a literal in twelve places.
6. Name or explain the `.slice(-4)` frame-history bound at `noteSegmentation.ts:203`.
7. Explain or remove the 12-key wire cap at `usePostureStore.ts:97`.

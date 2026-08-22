# Arrow: observation

Reduction of raw sensor streams — pitch frames and pose/hand landmarks — into typed,
explainable observations that the grader is permitted to see.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). Reverse-engineered from code
during brownfield bootstrap. Design and specs describe current reality; two of the three
reducers in this segment have no production caller.

Since that audit the selected-video path landed and has not been audited here. The note
segmenter still lacks a production caller. The hand and body-pose reducers share production
callers for live-camera and selected-video analysis; selected-video skill profiles and
full-window aggregation are implemented and tested.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/observation/observation-design.md`

### EARS
- `docs/intent/observation/observation-specs.md` (55 specs)

### Tests
- `frontend/lib/noteSegmentation.test.ts`
- `frontend/lib/posture.test.ts`
- `frontend/lib/videoAnalysis.test.ts`
- `frontend/lib/visualAssessment.test.ts`

### Code
- `frontend/lib/noteSegmentation.ts` (334 lines)
- `frontend/lib/posture.ts` (599 lines)
- `frontend/lib/technique.ts` (223 lines)
- `frontend/lib/videoAnalysis.ts`
- `frontend/lib/visualAssessment.ts`
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
6. `videoAnalysis.ts` — pure bounded timeline summary, highlight grouping, and privacy-safe export.
7. `visualAssessment.ts` — six versioned skill profiles and a pure reducer from the visual
   timeline to pass, retry, or insufficient evidence.

## Edge Audit — Skill-Aware Selected Video

The implementation impact is contained within the observation-owned selected-video consumer:

| Edge | Impact |
|---|---|
| `capture -> observation` | None. The existing `VisualTracker` frame contract already supplies every required timestamped metric. |
| `observation -> evaluation` | None. The local verdict does not change `PostureObservation`, `posture_accuracy`, or the canonical performance grader. |
| `evaluation -> progression` | None. The local verdict cannot award EXP, update mastery or SRS, or unlock a node. |
| `curriculum -> observation` | Identity reference only. All six profile skill slugs exist in shipped curriculum fixtures; no curriculum record is changed. |
| `observation -> interface` | The observation-owned video workspace renders the result using existing interface tokens; no interface-system behavior changes. |
| `observation -> API` | None. Export remains a local file; there is no request, persistence schema, or API-contract change. |
| `audio -> observation` | None. Audio fields and modules remain outside the result by type and spec. |

Search of the consumer graph finds `summarizeVisualFrames`, `assessVisualFrames`, and
`createVisualAssessmentExport` only in their observation modules, unit tests, and
`VideoAnalysisWorkspace`. The six skill slugs and every named metric key are present in the
current curriculum fixtures and reducer registries.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Note segmentation | `OBS-NOTE-001` – `011` | 10 | 1 | 0 |
| Posture | `OBS-POSE-001` – `013` | 10 | 1 | 1 |
| Hand technique | `OBS-HAND-001` – `004` | 3 | 1 | 0 |
| Take reduction | `OBS-RED-001` – `008` | 7 | 0 | 1 |
| Visual timeline | `OBS-TIME-001` – `006` | 5 | 1 | 0 |
| Skill-aware assessment | `OBS-ASSESS-001` – `014` | 14 | 0 | 0 |

**Summary:** 49 of 55 implemented; 4 deliberate non-wants; 2 active gaps.
The visual reducers and timeline are reachable. The tested note segmenter remains unreachable
until capture routes the microphone through it (`CAP-MIC-008`).

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

2. **The posture engine now has one shared production adapter.** `VisualTracker` constructs
   MediaPipe hand and body models, feeds both pure reducers, and is used by the live technique
   panel and selected-video workspace.

3. **Selected-video feedback remains visual-only by construction.** Its typed result has no
   field for notes, pitch, rhythm, score alignment, landmarks, video, or audio, and it retains
   media timestamps plus reducer versions.

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
2. The note reducer remains unreachable until capture routes the recorder through the shared
   segmenter (`CAP-MIC-008`). The visual reducers are no longer blocked.

### Should Fix
3. Implement `grip_openness` or withdraw its threshold (`OBS-POSE-012`).
4. Calibrate the 16 posture bands and the seven estimated segmenter constants against real
   takes. Every one is currently an initial guess.

### Consider
5. Name the bare `0.7` good-cutoff, repeated as a literal in twelve places.
6. Name or explain the `.slice(-4)` frame-history bound at `noteSegmentation.ts:203`.
7. Explain or remove the 12-key wire cap at `usePostureStore.ts:97`.

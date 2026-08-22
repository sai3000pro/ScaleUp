---
parent: high-level-design
prefix: OBS
---

# Observation

## Context and Design Philosophy

Observation is the stage between raw sensor data and anything the grader is allowed to
see. It takes what the browser's hardware adapters produce — a stream of pitch/confidence
frames, a stream of landmark arrays — and reduces each to a typed, explainable
observation: `PerformedNote[]` and `PostureObservation`.

Three principles govern everything in this segment.

**Reduction is pure.** Every module here is a fold over data: `(state, frame) -> state`,
or `(landmarks, history) -> metrics`. No module opens a microphone, reads a clock, or
touches the network. This is what makes the thresholds testable at all — a segmenter that
owns its own `AudioContext` can only be tested by making noise at it.

**An unreliable measurement never becomes a confident number.** A landmark the camera did
not see, a frame below the confidence floor, a metric whose supporting joints were visible
in a third of recent frames — each is reported as `not_detected` or `low_confidence` with
a confidence of 0, never as a value. Occlusion is the common case rather than the edge
case: a laptop webcam at a piano usually cannot see the player's hips.

**Thresholds are guesses, and are structured so they can be discovered to be wrong.**
Every band in this segment is an initial estimate. They are versioned, the raw geometry
and unit are persisted beside the derived score, and a per-learner calibration can shift
them. A threshold that cannot be retuned is a threshold nobody can ever find out is wrong.

## Note segmentation

`frontend/lib/noteSegmentation.ts` folds a stream of `PitchFrame` values into discrete
`NoteSegment`s. The interesting behaviour is all in the gating.

**Hysteresis on confidence.** A note must be *more* convincing to start (`confidenceOn`,
0.55) than to continue (`confidenceOff`, 0.4). A single threshold makes a decaying piano
note chatter into several spurious short notes as its confidence oscillates across the
line.

**Hysteresis on level.** Note-on at `-45 dBFS`, note-off at `-52 dBFS`, with a
`noteOffFrames` debounce of 3, for the same reason on the amplitude axis.

**Re-attack detection.** Without a level-jump trigger, two identical repeated notes merge
into one long note — the pitch never changes, so no pitch-change boundary fires. A rise of
`reattackRiseDb` (6 dB) within `reattackWindowFrames` (4) forces a boundary.

**Cents are separated from pitch.** The aggregate of a note's frames is a median exact
MIDI value. That value is rounded to `pitch_midi`, and the residual is reported separately
as `cents_deviation`. Sending a fractional MIDI number instead would corrupt every
instrument's pitch quality curve, since those curves divide by fractions of a semitone;
routing the residual to its own field gives intonation scoring a real signal and changes
nothing else.

| Parameter | Value | Origin |
|---|---|---|
| `minNoteDurationSeconds` | 0.12 | tuned against real takes |
| `pitchChangeFrames` | 6 | tuned against real takes |
| `confidenceOn` / `confidenceOff` | 0.55 / 0.4 | tuned against real takes |
| `pitchMedianWindow` | 5 | estimate |
| `noteOnRmsDb` / `noteOffRmsDb` | −45 / −52 | estimate |
| `noteOffFrames` | 3 | estimate |
| `reattackRiseDb` / `reattackWindowFrames` | 6 / 4 | estimate |

## Posture

`frontend/lib/posture.ts` reduces MediaPipe Pose's 33 landmarks to per-instrument metrics.
`frontend/lib/technique.ts` does the same for the 21-point hand model.

**Every distance is scale-normalised.** Measurements divide by a `bodyScale` derived from
shoulder-to-hip distance, falling back to shoulder width × 1.5. Without this, leaning
toward the camera changes every metric.

**Visibility is read, not assumed.** Each rule declares the landmarks it requires; every
one must clear `MIN_VISIBILITY` (0.5) or the rule returns `not_detected`. Coverage is then
measured over recent history rather than asserted — a rule whose landmarks were visible in
under `MIN_METRIC_COVERAGE` (0.6) of recent frames reports `low_confidence` rather than a
number, because a posture judgement from a glimpse is a guess wearing a number.

**Depth is not used.** No rule reads MediaPipe's `z`; it is a weak relative estimate rather
than metric depth. Trumpet chin angle, piano bench distance, and violin bow straightness are
depth-dominated, so they are omitted rather than approximated.

**One target is deliberately non-zero.** `chin_tilt` targets 12°, not 0: a violinist's head
is supposed to tilt toward the chin rest. Every other angular rule targets its natural
neutral.

**Calibration is clamped.** A per-learner baseline shifts each band, but never by more than
half the band's width, so a baseline captured while slouching cannot quietly make
everything pass.

## Reduction to a take

A take is minutes long and sampled several times a second, so a single frame at the moment
of submission is a snapshot rather than a measurement. `frontend/stores/usePostureStore.ts`
accumulates samples during a take and reduces them once at the end: the median value per
metric key, the mean confidence, and the worst status seen. Median rather than mean,
because one frame where the learner reached to turn a page should not become the take's
posture.

`backend/app/evaluation/posture.py` performs the final reduction to a single
`posture_accuracy`. Only metrics whose status is in `COUNTABLE_STATUSES`
(`good`, `needs_attention`) and whose confidence clears `MIN_POSTURE_CONFIDENCE` (0.5)
contribute. When nothing qualifies, the result is `None` — and the evaluator's weighting
redistributes across the dimensions that remain, so a take with no usable camera data
scores exactly as it would have if posture had never been measured.

## Visual feedback timeline

Live and selected-video capture both supply the same pair of landmark streams to observation:
21-point hands and 33-point body pose. Their reduced metrics are merged per frame without
merging meaning: each metric retains its key, value, confidence, status, explanation, raw
geometry, unit, and evaluator version. Media time is attached by capture and is never inferred
from frame count.

The selected-video surface retains a bounded sequence of these derived frames. Its summary is a
pure reduction: median value, mean confidence, good-frame ratio, measured-frame count, and the
timestamps of actionable observations. Repeated adjacent observations for the same metric collapse
into one highlight so a five-second wrist problem is feedback, not twenty-five copies of the same
warning. The timeline may show every observed metric; progression uses only the requirements in the
selected skill-assessment profile.

An empty or low-confidence analysis remains a valid result. The interface explains that the
learner or required joints were not visible; it does not turn missing evidence into a technique
failure. Export contains metadata and derived observations only, never landmarks, video frames,
or audio-derived fields.

## Skill-aware visual assessment

An instrument selects the available geometry rules; a skill selects which of those observations
matter to progression. The visual analyser therefore grades against a versioned
`VisualAssessmentProfile`, not against every metric MediaPipe happened to produce. A profile
contains:

- a stable profile ID, version, instrument, curriculum skill slug, and learner-facing title;
- requirements naming one observable metric each, with a positive weight and a `critical` flag;
- a minimum measured-coverage ratio for every requirement;
- a minimum per-requirement score for critical requirements; and
- a minimum weighted overall score.

The first profile set deliberately promises only what the present landmark rules can observe:

| Instrument | Curriculum skill | Verdict metrics |
|---|---|---|
| Piano | `five-finger-pattern` | wrist elevation (critical), torso lean, shoulder level |
| Guitar | `basic-strumming` | neck angle (critical), strumming-arm angle (critical), torso lean |
| Violin | `open-string-bow` | scroll height (critical), bow-arm elbow (critical), chin tilt, torso lean, shoulder level |
| Trumpet | `trumpet-orientation` | head tilt (critical), elbow lift (critical), elbow symmetry, torso lean, shoulder level |
| Drums | `basic-strokes` | wrist-height symmetry (critical), seated posture (critical), shoulder level |
| Banjo | `banjo-strumming` | neck angle (critical), strumming-arm angle (critical), torso lean |

Generic hand observations may still appear in the feedback timeline, but they do not affect an
instrument's verdict unless its selected profile names them. This prevents a piano-oriented wrist
heuristic from failing a trumpet or drum skill. Instrument-object interactions that the landmark
model cannot see — key contact, valve fingering, bow/string contact, drumstick grip, and pick or
finger contact — cannot be requirements in a profile.

Movement-stability heuristics remain diagnostic until exercise-specific calibration exists.
`hand_stability` and `strum_shoulder_stability` can mistake intentional musical movement for poor
form, so the initial progression profiles exclude them even though the timeline may still report
them.

### Temporal aggregation

Aggregation is a pure deterministic reduction over the full timestamped frame sequence. For each
profile requirement:

1. A reading is countable only when its status is `good` or `needs_attention` and its confidence
   is at least 0.5.
2. `coverage` is countable readings divided by total sampled frames. Missing and low-confidence
   readings remain in the evidence denominator; they never become zero-valued technique.
3. `medianValue` is the median value of countable readings and `goodFrameRatio` is the share of
   countable readings whose status is `good`.
4. `requirementScore` is 80% `medianValue` and 20% `goodFrameRatio`. The frame status is derived
   from the same underlying metric value, so equal weighting would punish a borderline reading
   twice. The smaller temporal term still makes a sustained problem matter while allowing a brief
   outlier to wash out of a good take.
5. Adjacent needs-attention readings retain their collapsed timestamp ranges for explanation, but
   one range does not independently override the aggregate.

The profile's `evidenceCoverage` is the minimum coverage among its requirements: the verdict is
only as observable as its least-observed required fact. If there are no frames, a required metric
is absent, or any requirement has coverage below 0.6, the outcome is `insufficient_evidence` and
the overall score is `null`.

With sufficient evidence, `overallScore` is the weighted mean of requirement scores. The outcome
is `pass` when `overallScore` is at least 0.65 and every critical requirement score is at least
0.55; otherwise it is `retry`. All ratios and thresholds are stored in the result through the
profile version so an exported outcome remains reproducible after calibration changes.

The initial 0.5 confidence floor, 0.6 coverage floor, 0.65 overall floor, and 0.55 requirement
floor are product defaults, not teacher-validated facts. They belong to the versioned profile
contract and must be replaced or specialised using a labelled corpus without changing the
aggregation algorithm in place.

### Result contract

`VisualAssessmentResult` carries the profile identity and version, instrument, skill slug,
outcome, nullable overall score, evidence coverage, and one result per requirement. Each
requirement result carries its weight, criticality, coverage, countable and total frame counts,
median value, good-frame ratio, nullable score, pass state, and the relevant timestamped
corrections. The result contains only derived visual observations. It cannot carry raw video,
frames, landmarks, audio observations, or musical-quality claims.

## Boundary and downstream edges

The selected-video surface is a local validation harness for this result contract. It does not
award EXP, update mastery, schedule review, or unlock a curriculum node. Allowing an uncalibrated
browser-only threshold to mutate progression would turn a demonstrator into a second grading
authority. Promoting a visual assessment result into the canonical attempt grade is a later
cross-segment change through `evaluation` and `progression`, after teacher-labelled validation and
server-side persistence of the profile version.

The six initial profile skill slugs already exist in the published curriculum fixtures. The
frontend registry mirrors those identities for the local harness but does not alter curriculum
data or claim ownership of skill definitions. A future server-delivered profile belongs to the
curriculum contract; this MVP does not add an API or database schema for it.

The edge impact is intentionally narrow:

- `capture -> observation` is unchanged: `VisualTracker` continues to supply timestamped derived
  hand and pose metrics from either live camera or local MP4 playback.
- `observation -> evaluation` is unchanged: the existing server posture observation and canonical
  performance score retain their current wire shapes and authority.
- `evaluation -> progression` is unchanged: only the canonical graded-attempt path may mutate EXP,
  mastery, SRS state, or unlocks.
- `observation -> selected-video interface/export` gains the profile registry, aggregate result,
  verdict card, and local JSON fields specified here.
- The audio observation and alignment paths are untouched; neither the profile nor its result can
  contain an audio-derived fact.

## Current state versus intent

This section records divergence rather than pretending the code matches the design above.

**The note segmenter has no production caller.** `noteSegmentation.ts` is imported only by
`noteSegmentation.test.ts`. The live audio path uses a second, untested segmenter written
inline inside `MicRecorder` (`frontend/lib/pitchDetection.ts:246-291`), which declares its
own `NoteSegment` interface at line 23 with a different shape — it lacks
`cents_deviation`, `peak_level_db`, and `mean_level_db` — and restates three of the
constants above as its own literals. The tested reducer and the running reducer are
different code.

**The visual reducers have production callers but uncalibrated thresholds.** `VisualTracker`
constructs both MediaPipe landmarkers and drives the same hand/posture reducers from the live
camera and from selected MP4 playback. The technique panel samples live results into the take
store, and the selected-video surface reduces them into a bounded timeline and a versioned
skill-aware outcome. This proves the signal path and aggregation behavior, not the pedagogical
correctness of the initial threshold bands.

**`grip_openness` is a band with no rule.** A threshold is declared for it; no rule computes
it. The drums rule set names three rules, and this is not one of them.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Reducer purity | Pure folds; hardware stays in adapters | Reducer owns its own `AudioContext` / landmarker | Thresholds are only testable if the reducer can be driven from fixture data. `vitest.config.ts` states the rule directly: `environment: "node"`, and the audio and camera plumbing is deliberately kept thin and untested. |
| Confidence gating | Two thresholds with hysteresis | One threshold | A single threshold makes a decaying note chatter into spurious extra notes as confidence oscillates. |
| Repeated-note boundary | RMS re-attack trigger | Pitch-change boundary only | Two identical repeated notes never change pitch, so nothing else can separate them. |
| Sub-semitone pitch | Round to `pitch_midi`, residual to `cents_deviation` | Fractional `pitch_midi` | `[inferred]` — the split is implemented at `noteSegmentation.ts:125-128` but no comment states why. Pitch-quality curves in the evaluators divide by fractions of a semitone, so a fractional MIDI value would degrade every instrument's pitch score while intending to improve it. Confirm or refute. |
| Unseen landmarks | `not_detected`, confidence 0 | Interpolate, or score anyway | A confident wrong correction is worse than silence. Occlusion is the common case. |
| Depth-dependent rules | Omitted | Approximate from MediaPipe `z` | `z` is a weak relative estimate; the rules it would support are precisely the ones a learner would most trust. |
| Scale normalisation | Divide by `bodyScale` | Raw pixel distances | Otherwise leaning toward the camera changes every metric. |
| Threshold ownership | Versioned constants + persisted raw value and unit | Bake thresholds into the score | A threshold you cannot retune is one you can never discover is wrong. |
| Skill-aware visual reduction | 80% median value plus 20% good-frame ratio per declared requirement; weighted take result after evidence gating | Equal-weight the correlated signals; worst frame; mean alone; last frame; one instrument-wide score | Median resists tracking outliers, the smaller temporal term exposes sustained form without double-penalising the same geometry, and a profile keeps unrelated observations out of progression. |
| Visual outcomes | Pass, retry, or insufficient evidence | Binary pass/fail | A binary result must mislabel occlusion as either success or learner failure. |
| Progression during local validation | No progression mutation; result remains local/exportable | Award EXP or unlock the named skill directly from the browser verdict | The thresholds are not teacher-validated, and bypassing the canonical attempt grade would create a second authority for mastery. |
| Calibration bound | Clamp to half a band width | Unbounded per-learner shift | An unbounded baseline captured while slouching makes everything pass. |
| Posture absent | Return `None`; weights redistribute | Score 0, or a neutral 0.5 | A take with no camera must score exactly as it would if posture had never existed. |

## Open Questions & Future Decisions

### Deferred

1. **No threshold in this segment has been calibrated against real takes.** All 16 posture
   bands, and every segmenter constant except the first three, are estimates. The
   persistence of raw values and `POSTURE_THRESHOLD_VERSION` exist to make the correction
   possible; the correction has not happened.
2. **`noteSegmentation.ts:203` caps frame history at 4** with a bare `.slice(-4)` — no named
   constant, no comment. Whether 4 is a considered window or an arbitrary bound is not
   recorded, and `reattackWindowFrames` is also 4, which may or may not be the reason.
3. **The `good` cutoff of 0.7 is a bare literal in twelve places** across `posture.ts` and
   `technique.ts` rather than a named constant.
4. **`grip_openness` is unimplemented by design or by omission — unknown.** A drumstick
   occludes exactly the fingers the metric would measure, so a deliberate decision not to
   ship it would be defensible, but no comment records one.
5. **`PostureObservationIn.threshold_version` has no destination column.** The wire schema
   accepts it; `performance_metric_bundles` persists only `posture_version`. As declared,
   it is inbound data that goes nowhere traceable — which defeats the versioning that the
   retune story depends on.
6. **`usePostureStore` caps the wire payload at 12 metric keys** (`metrics.slice(0, 12)`)
   with no stated rationale. The violin rule set has 6 rules and the shared set has 3, so
   the cap is not currently reached — but it is unexplained and would silently truncate a
   richer instrument.

## References

- `docs/api_contract.md` — `PerformedNote`, `PostureObservation`, `PostureMetricIn`
- `docs/intent/capture/capture-design.md` — produces the frames this segment consumes
- `docs/intent/evaluation/evaluation-design.md` — consumes this segment's output

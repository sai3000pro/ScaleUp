# Selected-video technique analysis

The video-analysis surface turns a learner-selected MP4 into timestamped hand and body
observations without sending the file, its frames, or its audio track to the backend. It is a
video-only workstream: pitch detection, note segmentation, MusicXML, DTW, and audio scoring are
not imported or invoked.

## Run it in the morning

Start the application using the normal development setup in `README.md`. With the frontend
running, sign in and open **Video** in the persistent navigation, or go directly to:

```text
http://localhost:3000/video-analysis
```

Then:

1. Choose the instrument skill whose visual requirements should be assessed.
2. Select an `.mp4` file. The browser creates a local object URL; this is not a network upload.
3. Press **Analyze video**. The video plays muted while the shared visual adapter samples it at
   five frames per second.
4. Pause, resume, or cancel as needed. Current hand/body feedback appears with confidence while
   the video plays.
5. At completion, review the **Pass**, **Retry**, or **Insufficient evidence** verdict, overall
   score when measurable, evidence coverage, per-requirement results, and correction timeline.
6. Press **Export visual JSON** to save the selected profile, aggregate result, derived
   observations, and evaluator versions. The
   export contains no raw landmarks, image buffers, video bytes, or audio-derived fields.

An MP4 with no visible person is a useful pipeline smoke test: analysis should complete as
**Insufficient evidence** with no overall score, not as a failed skill. An instrument performance
with the required joints in frame is necessary to receive Pass or Retry.

The initial skill profiles are Five-Finger Pattern (piano), Basic Strumming (guitar), Open-String
Bow (violin), Trumpet Orientation, Basic Strokes (drums), and Banjo Strumming. A profile names the
only metrics allowed to affect its verdict; unrelated diagnostics may appear in the timeline but
cannot lower the result.

The MVP verdict requires 60% evidence coverage for every declared metric, a 65% weighted overall
score, and 55% for each critical metric. A requirement score uses 80% median geometry and 20%
good-frame ratio. Movement-stability heuristics remain timeline feedback rather than verdict
requirements until exercise-specific calibration can distinguish intentional playing motion.

## Runtime dependencies

The first model load needs network access to two public hosts:

- `cdn.jsdelivr.net` for the pinned MediaPipe Tasks Vision WebAssembly runtime;
- `storage.googleapis.com` for the pinned hand-landmarker and pose-landmarker model assets.

Model-loading failure is rendered as a normal failed state and does not affect audio practice.
The selected MP4 is never sent to either host. Browser developer tools should show requests for
the runtime and model assets only, never a request whose body or URL contains the selected file.

## Responsibility boundary

```text
selected MP4 or webcam
  -> browser video frames
  -> shared VisualTracker
  -> MediaPipe hand + body landmarks (browser memory only)
  -> pure technique/posture reducers
  -> timestamped derived observations
  -> versioned skill profile + full-window aggregate
  -> pass / retry / insufficient evidence + correction timeline + visual JSON export
```

The only integration coordinate available to another workstream is `timestampMs`. The visual
result contains no played notes, pitch/rhythm accuracy, score alignment, or combined grade.

## What is and is not validated

The pipeline mechanics are deterministic and test-covered: MP4 validation, timestamp retention,
bounded memory, confidence and coverage gating, insufficient-evidence handling, median plus
good-frame-ratio aggregation, critical requirements, adjacent-correction grouping, six profile
definitions, deterministic outcomes, and privacy-safe export.

The pedagogical thresholds are **not validated against an instrument dataset yet**. Current
limitations are intentional and visible:

- MediaPipe produces markerless image-space estimates, not clinical or motion-capture ground
  truth.
- Posture distances are scale-normalised and the weak relative depth coordinate is not used.
- Occluded joints become `not_detected` or `low_confidence`; they are never guessed.
- Exact finger-to-key contact, violin bow/string contact, embouchure, breath support, and other
  instrument-object interactions are outside the current landmark rules.
- A teacher-labelled corpus of correct and incorrect performances is still required to calibrate
  and validate each instrument's thresholds.

Until that calibration exists, feedback demonstrates and tests the complete visual pipeline but
must not be presented as a teacher-validated assessment of technique.

## Verification

```powershell
cd frontend
npm test
npm run typecheck
npm run lint
npm run build
```

The timeline and assessment tests run in `frontend/lib/videoAnalysis.test.ts` and
`frontend/lib/visualAssessment.test.ts`. The shared live and
selected-video adapter is `frontend/lib/visualTracking.ts`; the upload surface is
`frontend/app/video-analysis/page.tsx`; the versioned profile registry and aggregate reducer are
`frontend/lib/visualAssessment.ts`.

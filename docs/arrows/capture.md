# Arrow: capture

Everything that touches hardware — microphone, camera, and the persistence of a take's
audio — turned into the frame streams that `observation` reduces.

## Status

**AUDITED** — last audited 2026-08-21 (git SHA `2006ff8`). Reverse-engineered during
brownfield bootstrap. The audio path is live; the camera path emits hand landmarks only and
is fed to the interface from a fixture.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/capture/capture-design.md`

### EARS
- `docs/intent/capture/capture-specs.md` (34 specs)

### Tests
- `backend/tests/integration/test_recordings.py`

### Code
- `frontend/lib/pitchDetection.ts` — `MicRecorder`, autocorrelation detection
- `frontend/lib/handTracking.ts` — MediaPipe hand landmarker
- `frontend/components/course/PracticePanel.tsx`
- `frontend/components/course/TechniquePanel.tsx`
- `backend/app/services/recording_service.py`
- `backend/app/api/routers/recordings.py`

## Architecture

**Purpose:** Acquire hardware, emit frames, and preserve a take — holding no thresholds and
making no judgements, because this layer is deliberately untested.

**Key Components:**
1. `MicRecorder` — microphone acquisition, analyser configuration, pitch frames, parallel audio capture.
2. `detectPitch` — pure normalised autocorrelation over a time-domain window.
3. `HandTracker` — MediaPipe hand landmarker over a shared video element and stream.
4. `recording_service` — content-addressed take storage, owner-only read and delete.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Audio | `CAP-MIC-001` – `008` | 6 | 0 | 2 |
| Pitch detection | `CAP-PITCH-001` – `008` | 6 | 0 | 2 |
| Camera | `CAP-CAM-001` – `008` | 4 | 1 | 3 |
| Take persistence | `CAP-TAKE-001` – `006` | 6 | 0 | 0 |
| Permission | `CAP-PERM-001` – `004` | 4 | 0 | 0 |

**Summary:** 26 of 34 implemented; 1 deliberate non-want; 7 active gaps — the most of any segment relative to its size, and all of them producers that never got built.

## Key Findings

1. **Audio is captured through the browser's automatic gain control.** The stream is
   acquired as `getUserMedia({ audio: true })` with no constraints
   (`frontend/lib/pitchDetection.ts:191`). AGC continuously normalises level, so the loudness
   the system measures is substantially the browser's correction rather than the learner's
   playing — and `evaluation` scores dynamics from that signal (`CAP-MIC-007`).

2. **The intended detector was never adopted.** `noteSegmentation.ts` names CREPE four times
   as the target detector and was written detector-agnostic for the swap. The live path still
   runs monophonic autocorrelation, so any polyphonic exercise is scored from its fixture note
   path rather than from audio (`CAP-PITCH-007`).

3. **Two external hosts are undeclared.** `handTracking.ts:21,23` fetches the MediaPipe
   runtime from `cdn.jsdelivr.net` and the model from `storage.googleapis.com`. Neither
   appears in `app/integrations.py`, `.env.example`, or `docs/integrations.md` — all of which
   enumerate the system's external dependencies — while the product's stated position is that
   it runs with no network (`CAP-CAM-007`).

4. **No body-pose landmarker exists.** `observation` implements a 33-landmark posture engine
   for five instruments and this segment constructs no producer for it (`CAP-CAM-006`).

5. **Take persistence is the strongest part of the segment.** Content-addressed dedupe,
   a size ceiling, owner-only read and delete, and not-found rather than forbidden — all six
   specs implemented.

## Work Required

### Must Fix
1. Disable automatic gain control, echo cancellation and noise suppression on the audio
   stream (`CAP-MIC-007`). One constraint object; every dynamics measurement depends on it.
2. Declare or vendor the MediaPipe CDN dependency (`CAP-CAM-007`).

### Should Fix
3. Construct a body-pose landmarker (`CAP-CAM-006`) and feed the technique panel from the
   live stream rather than its fixture (`CAP-CAM-008`). `observation` implements the rules
   for both and has no producer for either.
4. Route the recorder through the shared segmenter and delete the inline duplicate
   (`CAP-MIC-008`) — this blocks the detector swap below.
5. Adopt a polyphony-capable detector (`CAP-PITCH-007`, `CAP-PITCH-008`) — after
   `CAP-MIC-008`, since the segmenter built to receive it is not the one in the live path.

### Consider
6. Sample audio at a fixed hop rather than at display refresh rate.

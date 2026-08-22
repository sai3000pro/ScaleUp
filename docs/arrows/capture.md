# Arrow: capture

Everything that touches a raw sensor or media source — microphone, camera, selected video, and
the persistence of a take's audio — turned into the frame streams that `observation` reduces.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). Reverse-engineered during
brownfield bootstrap. The audio path is live; the camera path emits hand landmarks only and
is fed to the interface from a fixture.

Since that audit, the selected-video path landed. The audio path is unchanged. A shared visual adapter
now emits hand and body-pose observations from both the live camera and a locally decoded MP4;
the fixture path remains available.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/capture/capture-design.md`

### EARS
- `docs/intent/capture/capture-specs.md` (41 specs)

### Tests
- `backend/tests/integration/test_recordings.py`
- `frontend/lib/videoAnalysis.test.ts`

### Code
- `frontend/lib/pitchDetection.ts` — `MicRecorder`, autocorrelation detection
- `frontend/lib/visualTracking.ts` — shared MediaPipe hand/body adapter
- `frontend/components/video/VideoAnalysisWorkspace.tsx` — local MP4 source and states
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
3. `VisualTracker` — MediaPipe hand and body-pose landmarkers over either a webcam or selected video element.
4. `VideoAnalysisWorkspace` — explicit MP4 selection, local object URL, playback controls, and cleanup.
5. `recording_service` — content-addressed take storage, owner-only read and delete.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Audio | `CAP-MIC-001` – `008` | 6 | 0 | 2 |
| Pitch detection | `CAP-PITCH-001` – `008` | 6 | 0 | 2 |
| Camera | `CAP-CAM-001` – `008` | 6 | 1 | 1 |
| Selected video | `CAP-VID-001` – `007` | 6 | 1 | 0 |
| Take persistence | `CAP-TAKE-001` – `006` | 6 | 0 | 0 |
| Permission | `CAP-PERM-001` – `004` | 4 | 0 | 0 |

**Summary:** 34 of 41 implemented; 2 deliberate non-wants; 5 active gaps. The selected-video
path is complete; the remaining gaps are two audio-capture issues, two pitch-detector issues,
and registering the browser model hosts in the backend integration report.

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

3. **Two external hosts are documented but absent from the backend register.**
   `visualTracking.ts` fetches the pinned MediaPipe runtime from `cdn.jsdelivr.net` and two
   model assets from `storage.googleapis.com`. `docs/integrations.md` and
   `docs/video-analysis.md` name them and the failure state; `app/integrations.py` still does
   not (`CAP-CAM-007`).

4. **One adapter owns both live and selected-video vision.** Hand and body models feed the
   same pure reducers at five hertz. Media time labels feedback while a monotonic processing
   clock satisfies MediaPipe's video contract (`CAP-CAM-006`, `CAP-CAM-008`, `CAP-VID-003`).

5. **Take persistence is the strongest part of the segment.** Content-addressed dedupe,
   a size ceiling, owner-only read and delete, and not-found rather than forbidden — all six
   specs implemented.

## Work Required

### Must Fix
1. Disable automatic gain control, echo cancellation and noise suppression on the audio
   stream (`CAP-MIC-007`). One constraint object; every dynamics measurement depends on it.
2. Declare or vendor the MediaPipe CDN dependency (`CAP-CAM-007`).

### Should Fix
3. Route the recorder through the shared segmenter and delete the inline duplicate
   (`CAP-MIC-008`) — this blocks the detector swap below.
4. Adopt a polyphony-capable detector (`CAP-PITCH-007`, `CAP-PITCH-008`) — after
   `CAP-MIC-008`, since the segmenter built to receive it is not the one in the live path.

### Consider
5. Vendor the MediaPipe runtime/models if offline visual analysis becomes a hard requirement.
6. Sample audio at a fixed hop rather than at display refresh rate.

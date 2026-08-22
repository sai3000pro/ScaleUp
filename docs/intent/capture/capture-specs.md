# Capture — EARS Specs

Prefix: `CAP`. Facets: `MIC` (audio), `PITCH` (detection), `CAM` (camera),
`VID` (selected video), `TAKE` (recording persistence), `PERM` (permission and absence).

**Reducers live in `observation`.** This segment owns the hardware and the code paths;
the folds that turn its frames into typed observations are `observation`'s.

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Audio capture

- [x] **CAP-MIC-001**: The recorder shall acquire the microphone only after an explicit user action.
- [x] **CAP-MIC-002**: The recorder shall configure its analyser with smoothing disabled, so frame-to-frame transitions are preserved for onset detection.
- [x] **CAP-MIC-003**: The recorder shall emit a level reading in decibels alongside every pitch frame.
- [x] **CAP-MIC-004**: The recorder shall classify a frame below the silence level threshold as a rest.
- [x] **CAP-MIC-005**: The recorder shall capture the take's audio in parallel with analysis, so the preserved recording is independent of the analysis path.
- [x] **CAP-MIC-006**: When the recorder is stopped, it shall return the take's completed notes and its recorded audio together.
- [ ] **CAP-MIC-007**: The recorder shall request the microphone with automatic gain control, echo cancellation, and noise suppression disabled, so that measured loudness reflects the learner's playing rather than the browser's correction.
- [ ] **CAP-MIC-008**: The recorder shall obtain note segments from the shared segmenter rather than reimplementing segmentation inline.

## Pitch detection

- [x] **CAP-PITCH-001**: The detector shall report a pitch estimate and a confidence for each analysed window.
- [x] **CAP-PITCH-002**: The detector shall reject a window whose signal energy falls below the silence floor rather than reporting a pitch for it.
- [x] **CAP-PITCH-003**: The detector shall reject a window whose clarity falls below the clarity threshold rather than reporting a low-quality pitch.
- [x] **CAP-PITCH-004**: The detector shall search only within a bounded frequency band appropriate to the instruments in scope.
- [x] **CAP-PITCH-005**: The detector shall refine its estimate by interpolation, guarded against a degenerate denominator.
- [x] **CAP-PITCH-006**: The detector's pure functions shall be callable without acquiring an audio device.
- [ ] **CAP-PITCH-007**: The detector shall resolve simultaneously sounding pitches, so that a chord is scored from what was played rather than from a fixture.
- [ ] **CAP-PITCH-008**: The detector shall report each note's deviation in cents from equal temperament.

## Camera capture

- [x] **CAP-CAM-001**: The camera path shall begin only after explicit consent, and shall report a capability check before requesting access.
- [x] **CAP-CAM-002**: The camera path shall expose a distinct status for unavailable, loading, and tracking, so the interface can distinguish no camera from a camera that is starting.
- [x] **CAP-CAM-003**: The camera path shall emit hand landmark arrays for reduction, and shall itself apply no thresholds or judgement.
- [x] **CAP-CAM-004**: The camera path shall share one video element and one media stream across all landmark models.
- [D] **CAP-CAM-005**: No video frame or image buffer shall leave the browser.
- [x] **CAP-CAM-006**: The camera path shall construct a body-pose landmarker and emit its landmark arrays.
- [ ] **CAP-CAM-007**: Where the landmark model and its runtime are fetched from an external host, that dependency shall be declared in the integration register alongside every other external service.
- [x] **CAP-CAM-008**: The technique panel shall sample metrics from the live camera stream, not only from its fixture source.

## Take persistence

- [x] **CAP-TAKE-001**: The system shall store a take's audio once per owner and content hash, returning the existing recording when the same bytes are submitted again.
- [x] **CAP-TAKE-002**: The system shall reject a recording that exceeds the maximum upload size.
- [x] **CAP-TAKE-003**: The system shall permit only a recording's owner to read it.
- [x] **CAP-TAKE-004**: The system shall permit only a recording's owner to delete it, and deletion shall be permanent.
- [x] **CAP-TAKE-005**: When a submission names a recording, the system shall link that recording to the resulting attempt.
- [x] **CAP-TAKE-006**: When a caller requests a recording they do not own, the system shall answer as though it does not exist.

## Selected video

- [x] **CAP-VID-001**: The visual-analysis surface shall accept an MP4 only after an explicit file-selection action.
- [x] **CAP-VID-002**: The browser shall decode a selected MP4 locally and shall not upload its bytes, frames, or audio track.
- [x] **CAP-VID-003**: The selected-video path and live-camera path shall use the same visual landmarker adapter and observation reducers.
- [x] **CAP-VID-004**: Every emitted visual frame shall carry the selected video's media timestamp independently of processing time.
- [x] **CAP-VID-005**: The selected-video path shall expose ready, loading-model, analysing, paused, completed, cancelled, unsupported, and failed outcomes as renderable states.
- [x] **CAP-VID-006**: The selected-video path shall release object URLs, animation callbacks, and landmarker resources when analysis stops, the file changes, or the surface unmounts.
- [D] **CAP-VID-007**: Selected-video analysis shall not read or evaluate the video's audio track.

## Permission and absence

- [x] **CAP-PERM-001**: When microphone access is denied or unavailable, the system shall report it as a normal outcome the interface can render, not as an unhandled failure.
- [x] **CAP-PERM-002**: The system shall provide a fixture path that submits known notes with no microphone present.
- [x] **CAP-PERM-003**: The system shall provide a fixture landmark source so the camera path is exercisable with no camera present.
- [x] **CAP-PERM-004**: While the camera is unavailable, the practice loop shall remain fully usable.

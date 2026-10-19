---
parent: high-level-design
prefix: CAP
---

# Capture

## Context and Design Philosophy

Capture owns every piece of code that touches hardware: the microphone, the camera, and
the persistence of a take's audio. It is the only segment permitted to hold a
`MediaStream`, an `AudioContext`, or a landmarker, and its job is to turn those into the
frame streams that `observation` reduces.

**Raw media stays in the browser.** The camera path sends derived landmarks and metrics —
never video, never a frame buffer. Audio is the one exception, and a deliberate one: a take
is preserved as a content-addressed recording so a learner can hear what they played, and
that recording belongs to them and is deletable by them.

**Adapters stay thin, because they are not tested.** The project's testing rule is stated
directly in `frontend/vitest.config.ts`: the suite runs in a `node` environment over
`lib/**/*.test.ts`, and the audio and camera plumbing is deliberately kept thin and
untested. That is only a safe trade while the adapters contain no decisions. Every
threshold, every gate, every piece of judgement belongs one layer up, in `observation`.

**Permission is a first-class state.** Microphone and camera access can be denied,
revoked, or simply absent. Denial is a normal outcome that the UI must render, not an
error path — and a fixture path exists so the whole loop is exercisable with no hardware
at all.

## Audio capture

`MicRecorder` in `frontend/lib/pitchDetection.ts` acquires the microphone, builds an
`AudioContext` and `AnalyserNode`, and drives a `requestAnimationFrame` loop that reads
time-domain samples and emits pitch frames.

Pitch is detected per window by harmonic-salience peak picking over a Hann-windowed
spectrum (`frontend/lib/polyphonicPitch.ts`). Every candidate fundamental on the MIDI grid
between 36 and 96 is scored by the magnitude found at its first six harmonics; the strongest
candidate becomes a voice, its expected `1/h` harmonic series is subtracted from the
spectrum, and the search repeats until the next candidate falls below a fraction of the
first or six voices are found. A candidate only qualifies if its fundamental is an audible
local spectral peak that refines back onto the candidate and carries a minimum share of its
own salience — which is what stops a sub-octave, or a coincidence of other notes'
harmonics, from being heard as a note. Each voice's frequency is refined by parabolic
interpolation on the log spectrum, guarded against a degenerate denominator, and reported
with a clarity equal to the fraction of its harmonics present. A chord is therefore scored
from what was played. The monophonic autocorrelation detector remains available for callers
that want one dominant pitch.

Polyphonic segmentation (`frontend/lib/voiceTracking.ts`) keeps one shared note segmenter
per sounding voice: a detected voice continues the track within three-quarters of a
semitone of it, an unmatched voice opens a new track, and a track that hears nothing in a
frame receives a silent frame so its note closes on the same terms as a monophonic rest.
Notes from all tracks are rebased to the earliest onset and ordered by onset, then pitch.
What counts as a note is decided only in the segmenter; the tracker decides only which
stream a voice belongs to.

The analyser is configured with an FFT size of 4096 and a smoothing time constant of zero.
Smoothing is disabled deliberately: the analyser's built-in smoothing would blur exactly
the frame-to-frame transitions that note onset detection depends on.

`SILENCE_LEVEL_DB` (−50) is the threshold that separates a rest from playing. Its comment
names what it is for: the coach only speaks at a rest, so this is the line between coaching
and talking over someone.

The recorder also runs a `MediaRecorder` in parallel, so the take's audio can be preserved
independently of the analysis.

## Camera capture

`frontend/lib/visualTracking.ts` wraps MediaPipe's hand and pose landmarkers over one `<video>`
element. A live source binds one `getUserMedia` stream; a selected-video source binds one local
object URL. The adapter emits 21-point hand and 33-point body landmark arrays through a bounded
`requestAnimationFrame` sampling loop.

A tracking status — `idle`, `loading`, `tracking`, `unavailable` — is exposed so the UI can
distinguish "no camera" from "camera starting" from "camera running but seeing nothing".

## Selected-video capture

A learner-selected MP4 is a local visual frame source, not an upload. The browser binds an
object URL to a video element, decodes it locally, and supplies its frames to the same thin
MediaPipe adapter used by the live camera. The analyser uses media time for feedback labels,
while MediaPipe receives a monotonic processing timestamp so pausing or seeking cannot violate
the landmarker contract.

File selection is explicit and accepts MP4 only for the first release. Unsupported files,
decode failures, model failures, cancellation, and an empty result are normal interface states.
Starting analysis never reads the file's audio track and never invokes the audio observation or
evaluation modules. Object URLs and model resources are released when the file changes or the
surface unmounts.

Analysis is sampled at a bounded cadence rather than on every decoded frame. Technique feedback
does not need cinema frame rate, and a bounded cadence keeps local analysis responsive on a
laptop while preserving media timestamps for the observation timeline.

## Take persistence

`backend/app/services/recording_service.py` stores a take's audio once per
`(user, content_sha256)`. The hash is the dedupe mechanism, so re-submitting the same
bytes returns the existing recording rather than creating a second row. Uploads are capped
at `MAX_RECORDING_BYTES` (20 MB) — this is a practice-clip store, not a media library.
Read and delete are owner-only.

## Current state versus intent

**Audio is captured through the browser's automatic gain control.** The stream is acquired
as `getUserMedia({ audio: true })` with no constraints
(`frontend/lib/pitchDetection.ts:191`). Browsers apply automatic gain control, echo
cancellation, and noise suppression by default. AGC continuously normalises level — which
means the loudness the app measures is substantially the browser's correction, not the
learner's playing. The `dynamics` dimension in `evaluation` is scored from this signal.

**The visual path depends on two external hosts.** `visualTracking.ts` loads the pinned
MediaPipe WASM bundle from `cdn.jsdelivr.net` and the hand/pose models from
`storage.googleapis.com` at runtime. The hosts and failure state are documented in
`docs/integrations.md` and `docs/video-analysis.md`, but they do not yet appear in the backend's
declarative integration report. The camera and selected-video features therefore require network
access on first model load even though they require no credential.

**Recorded audio is stored in Postgres.** `recordings.content` is a `LargeBinary` column.
`docs/deployment.md` discusses object storage for *document* bytes and does not mention
that practice audio grows the primary database.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Where decisions live | Adapters are thin; all judgement in `observation` | Segment inside the recorder | The adapters are deliberately untested (`vitest.config.ts`), which is only safe if they hold no decisions. |
| Analyser smoothing | Disabled (`smoothingTimeConstant = 0`) | Browser default | Smoothing blurs the frame-to-frame transitions onset detection depends on. |
| Pitch algorithm | Harmonic-salience peak picking with iterative spectral subtraction | Normalised autocorrelation (the previous detector); a learned detector (CREPE) | Autocorrelation is monophonic and cannot hear a chord. A learned detector would resolve polyphony too, but costs a model download and a runtime; salience peak picking resolves chords of harmonic instruments with the Web Audio API alone and keeps the capture layer dependency-free. The segmenter stays detector-agnostic so a learned detector remains a contained swap. |
| Landmark model | MediaPipe Tasks Vision | A server-side pose service | Keeps video in the browser, which the privacy position requires. |
| Silence threshold | −50 dBFS, named for its purpose | Any level gate | The coach speaks only at a rest, so this constant is the boundary between coaching and interrupting. |
| Take storage | Content-addressed by sha256, owner-deletable | Store every submission | Dedupe comes free from the hash, and a learner's own audio must be theirs to remove. |
| Upload ceiling | 20 MB | Unbounded, or a duration cap | A practice-clip store, not a media library. |
| Video egress | Never leaves the page | Upload frames for server-side analysis | Landmarks carry what the grader needs; video carries a learner's room. |
| Prerecorded analysis | Decode a selected MP4 locally through the live visual analyser | Upload to a batch service; maintain a second analyser | Local decoding preserves privacy, and one analyser prevents live and prerecorded feedback from disagreeing by implementation. |
| Audio in a selected video | Ignored by visual analysis | Reuse it for pitch/rhythm scoring | Audio analysis is a separate team boundary. The only shared coordinate is media time. |
| Hardware absence | A no-microphone fixture path | Require hardware | The whole loop must be demonstrable and testable without a device. |

## Open Questions & Future Decisions

### Deferred

1. **A learned detector is not used.** Salience peak picking resolves chords of harmonic
   instruments; dense clusters, strongly inharmonic timbres and very low fundamentals are
   where a learned detector would still do better. The segmenter and tracker would receive
   it unchanged.
2. **Should the browser's audio processing be disabled?** Turning off AGC, echo cancellation
   and noise suppression is a one-line constraint change, and every dynamics measurement
   depends on it. Nothing records whether the current behaviour was chosen or inherited.
3. **Should the MediaPipe CDN dependency be registered or vendored?** The hosts are documented,
   but adding them to the backend integration report would satisfy the one-register operations
   rule; vendoring the WASM and models would make offline visual analysis true.
4. **Should recorded audio move out of Postgres?** The object-storage backend already
   exists for document bytes.
5. **A frame-capture worklet is not used.** The `requestAnimationFrame` loop samples at
   frame rate rather than at a fixed hop, so the interval between analysed windows follows
   display refresh and leaves audio unanalysed between windows.

## References

- `docs/intent/observation/observation-design.md` — consumes this segment's frame streams
- `docs/integrations.md` — browser model-host dependencies and their failure behaviour
- `docs/video-analysis.md` — selected-video operation and calibration boundary
- `docs/api_contract.md` — `Recording`

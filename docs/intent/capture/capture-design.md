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

Pitch is detected by normalised autocorrelation over the time-domain buffer. The search
band spans roughly 55 Hz to 1200 Hz, expressed as lag bounds against the sample rate. A
frame is rejected when its energy falls below the silence gate or its clarity — the
normalised autocorrelation at the winning lag — falls below the clarity threshold.
Parabolic interpolation refines the winning lag, guarded against a near-zero denominator.

The analyser is configured with an FFT size of 4096 and a smoothing time constant of zero.
Smoothing is disabled deliberately: the analyser's built-in smoothing would blur exactly
the frame-to-frame transitions that note onset detection depends on.

`SILENCE_LEVEL_DB` (−50) is the threshold that separates a rest from playing. Its comment
names what it is for: the coach only speaks at a rest, so this is the line between coaching
and talking over someone.

The recorder also runs a `MediaRecorder` in parallel, so the take's audio can be preserved
independently of the analysis.

## Camera capture

`frontend/lib/handTracking.ts` wraps MediaPipe's `HandLandmarker`, sharing one `<video>`
element and one `getUserMedia` stream, and emits 21-point landmark arrays through a
`requestAnimationFrame` loop.

A tracking status — `idle`, `loading`, `tracking`, `unavailable` — is exposed so the UI can
distinguish "no camera" from "camera starting" from "camera running but seeing nothing".

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

**The camera path depends on two external hosts, undeclared.** `handTracking.ts` loads the
MediaPipe WASM bundle from `cdn.jsdelivr.net` and the hand-landmarker model from
`storage.googleapis.com` at runtime. Neither appears in `app/integrations.py`, in
`.env.example`, or in `docs/integrations.md`, all of which enumerate the system's external
dependencies. The product's stated position is that everything runs with no keys and no
network; the camera feature does not.

**No body-pose landmarker exists.** `observation` implements a 33-landmark posture engine
for five instruments. This segment constructs no producer for it.

**Recorded audio is stored in Postgres.** `recordings.content` is a `LargeBinary` column.
`docs/deployment.md` discusses object storage for *document* bytes and does not mention
that practice audio grows the primary database.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Where decisions live | Adapters are thin; all judgement in `observation` | Segment inside the recorder | The adapters are deliberately untested (`vitest.config.ts`), which is only safe if they hold no decisions. |
| Analyser smoothing | Disabled (`smoothingTimeConstant = 0`) | Browser default | Smoothing blurs the frame-to-frame transitions onset detection depends on. |
| Pitch algorithm | Normalised autocorrelation, pending replacement | FFT peak-picking; a learned detector (CREPE) | An interim choice, not the intended one. A learned detector resolves polyphony and yields a cents residual directly; autocorrelation is monophonic and cannot hear a chord. The segmenter above was written detector-agnostic expressly for this swap and names CREPE throughout as the target. |
| Landmark model | MediaPipe Tasks Vision | A server-side pose service | Keeps video in the browser, which the privacy position requires. |
| Silence threshold | −50 dBFS, named for its purpose | Any level gate | The coach speaks only at a rest, so this constant is the boundary between coaching and interrupting. |
| Take storage | Content-addressed by sha256, owner-deletable | Store every submission | Dedupe comes free from the hash, and a learner's own audio must be theirs to remove. |
| Upload ceiling | 20 MB | Unbounded, or a duration cap | A practice-clip store, not a media library. |
| Video egress | Never leaves the page | Upload frames for server-side analysis | Landmarks carry what the grader needs; video carries a learner's room. |
| Hardware absence | A no-microphone fixture path | Require hardware | The whole loop must be demonstrable and testable without a device. |

## Open Questions & Future Decisions

### Deferred

1. **The intended detector has not been adopted.** The current detector cannot resolve a
   chord, so any polyphonic exercise is scored from its fixture note path rather than from
   what was played. The replacement is a contained swap only once the live path runs through
   the shared segmenter rather than its inline duplicate — see `observation`.
2. **Should the browser's audio processing be disabled?** Turning off AGC, echo cancellation
   and noise suppression is a one-line constraint change, and every dynamics measurement
   depends on it. Nothing records whether the current behaviour was chosen or inherited.
2. **Should the MediaPipe CDN dependency be declared or vendored?** Declaring it in
   `integrations.py` makes it visible; vendoring the WASM and model makes the offline claim
   true. Doing neither leaves a silent network dependency in a product that advertises not
   having one.
3. **Should recorded audio move out of Postgres?** The object-storage backend already
   exists for document bytes.
4. **A frame-capture worklet is not used.** The `requestAnimationFrame` loop samples at
   frame rate rather than at a fixed hop, so the interval between analysed windows follows
   display refresh and leaves audio unanalysed between windows.

## References

- `docs/intent/observation/observation-design.md` — consumes this segment's frame streams
- `docs/integrations.md` — the external-dependency register this segment is absent from
- `docs/api_contract.md` — `Recording`

---
parent: high-level-design
prefix: COACH
---

# Coaching

## Context and Design Philosophy

Coaching turns a metric bundle into something a person can act on: a written examiner's
assessment after a take, and short spoken corrections during one. It is the segment where
numbers become language.

**Nothing to say is a valid answer.** A coach that talks constantly is worse than one that
says nothing. The policy is built to stay quiet by default and to speak only when it has
something specific, at a moment when the learner can hear it.

**The coach never changes a number.** It selects, orders and phrases what evaluation
already decided. A language model may improve wording; it may never alter a score. Every
utterance has a deterministic sentence behind it, which is what the learner hears when no
provider is configured, when the budget is spent, or when generation is too slow.

**Speak into silence.** Corrections land at a phrase end, not over the playing. This is why
the capture segment's silence threshold exists and why the policy takes silence duration as
an input rather than inferring it.

**Delivery, never authority.** The live socket cues and speaks; it does not grade. At the
end of a take it calls the same submission path the clip flow uses, under an idempotency
key derived from the take, so there is exactly one grading path and the streaming layer
cannot become a second one.

## The turn policy

`backend/app/domain/coach_policy.py` decides whether to speak, what about, and how
insistently. It imports nothing outside the standard library and takes time as a parameter,
so every decision is reproducible from a fixture.

`decide_turn` returns a frozen result carrying the chosen cue, its severity, and — when it
declines — an explicit reason for the suppression. Declining to speak is a first-class
outcome with a recorded cause, not an absence.

**Budget shape:** at most four utterances per take, at least eight seconds between them, a
twenty-five second cooldown per cue kind, and a minimum silence of six-tenths of a second
before any utterance. The single exception is losing one's place, which may interrupt, once
per take.

The course's model budget is an *input* to the policy rather than an exception thrown
mid-stream, so running out of budget degrades to the deterministic sentence instead of
failing a take.

## Cues

Cue selection is ordered by severity: losing the place first, then runs of missed or extra
notes, then pitch error, then timing bias. Timing distinguishes rushing from dragging by
reading a **signed** bias, so the two are separable.

## The examiner

`backend/app/evaluation/feedback.py` produces the post-take assessment. Numbers are
interpreted into words before they reach a prompt — a metric becomes "secure", "uneven", or
"not yet reliable" rather than "0.62" — driven by an explicit polarity table so that
"improved" is never guessed from the sign of a raw delta.

A deterministic examiner derives the whole assessment with no model at all. The model path
rewrites that assessment in an examiner's register; it does not compute it.

## Live delivery

The product goal this segment exists to serve is conversational: while a learner practises,
an examiner's voice speaks short corrections aloud, in the moment, without stopping the
take. Text-only feedback after the fact is the fallback, not the design.

Synthesis is provided by ElevenLabs behind `services/voice.py`, in two modes — one
synthesis per attempt for post-take feedback, content-addressed so a re-read never pays
twice, and sentence-at-a-time streaming during a take. The streaming path uses the
provider's latency-optimised model tier, because latency *is* the feature there.

The persona is a property of the prompt, not of the provider: the voice carries the
examiner's register that `feedback.py` and the versioned feedback prompt establish. Changing
the configured voice invalidates cached audio by design, since the alternative is serving
the previous persona from cache indefinitely.

`coach_service.py` owns the WebSocket session. Authentication is a token in the first frame
rather than in the URL, because browsers cannot set headers on a WebSocket handshake and a
URL lands in access logs.

Utterances persist through their own database session, separate from the socket's receive
loop, since a single async session must not be used concurrently.

Voice streams sentence-at-a-time. Text always arrives; audio is best-effort, degrading from
media-source streaming, to buffer-and-decode at end of utterance, to the operating system's
own voice.

## Current state versus intent

**A learner can never be told they are flat.** `coach_policy.py:193` selects between sharp
and flat with `pitch_error > 0`, but reaches that line only when `pitch_error >= 0.45`, and
the underlying metric is a magnitude that is never negative. `CueKind.FLAT_PITCH` is
unreachable. Every pitch cue says sharp — including when the learner is flat. The timing
branch four lines below reads a *signed* value and separates rushing from dragging
correctly, so the distinction was understood on one axis and lost on the other.

**Three intonation thresholds disagree across two segments.** Scoring fails intonation at 30
cents; coaching text triggers at 20; the sentence it produces describes a quarter-tone,
which is 50.

**A live take is pinned to one process.** The cross-instance guard in `coach_service.py` is
a process-local dictionary, so it cannot see a take held by another replica.

**No evaluation harness exists for the examiner.** Every model call records its prompt
identifier, version and hash precisely so that "did accuracy change when the rubric was
edited?" is answerable. The data accumulates and is never queried.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Silence requirement | Speak only after a minimum silence | Speak whenever a fault is detected | Talking over a learner is worse than not speaking. |
| Interruption | One cue may interrupt: lost place | None; or any high severity may interrupt | A learner who has lost the score is not playing usefully; everything else can wait for a rest. |
| Utterance budget | ≤4 per take, ≥8 s apart, 25 s per-cue cooldown | Unlimited; or one summary at the end | A stream of corrections is noise, and repeating one cue trains nothing. |
| Silence as input | `now_seconds` and `silence_seconds` are parameters | Read the clock inside the policy | Time as a parameter is what makes every decision reproducible from a fixture. |
| Declining to speak | Explicit suppression reason | Return nothing | "Why was it quiet?" must be answerable. |
| Model budget | An input to the policy | An exception raised mid-stream | Exhausted budget must degrade to the deterministic sentence, never fail a take. |
| Deterministic floor | Every cue has a written sentence | Model-only | The loop must work with no keys, no network, and no spend. |
| Model's role | Rewrites the examiner's wording | Computes the assessment | A model that can change a number can change a grade. |
| Numbers before prompting | Interpreted to words first | Pass raw metrics to the model | Handing a model raw numbers invites it to invent a reading of them. |
| Trend direction | Explicit polarity table | Infer from the sign of a delta | For some metrics lower is better; a sign alone cannot say. |
| WebSocket auth | Token in the first frame | Token in the URL query | Browsers cannot set handshake headers, and URLs are logged. |
| Utterance persistence | Its own session | Reuse the socket's session | Concurrent use of one async session silently loses writes. |
| Live scoring | Calls the clip path with a take-derived idempotency key | Persist the live matcher's result | One grading path; a race yields one attempt and one award. |
| Streamed audio | Best-effort, three-tier fallback | Require streamed audio | Text always arrives; audio is an enhancement, not the contract. |
| Streaming model | Latency-optimised tier | The strongest available model | A correction that starts two seconds late has missed its moment. |
| Voice provider | ElevenLabs, behind a provider seam | Browser speech synthesis alone; a self-hosted model | A recognisable examiner persona is the point; the OS voice cannot carry one. The seam keeps it swappable and keeps the product runnable with no key. |
| Persona ownership | The prompt owns it; the provider renders it | Encode the persona in voice settings | A persona expressed only in a voice cannot be versioned, diffed, or evaluated. |
| Voice cache key | Includes the configured voice | Key on text alone | Otherwise changing the persona serves the old one from cache forever. |

## Open Questions & Future Decisions

### Deferred

1. **Every policy constant is unvalidated.** The silence minimum, the eight-second spacing,
   the four-utterance cap, the twenty-five-second cooldown, and the rushing/dragging
   thresholds are all estimates. The policy is pure and cheap to test, and none of them have
   been tuned against a real learner.
2. **Should pitch error be signed?** Fixing the unreachable flat cue requires the underlying
   metric to carry direction, which is a change in `evaluation` — a cross-segment cascade.
3. **The intonation ladder is 20 cents to coach, 30 to fail.** Coaching earlier than scoring
   is deliberate: a learner should be told they are drifting before it costs them. The defect
   is the spoken sentence, which describes a quarter-tone (50 cents) while triggering at 20 —
   it must describe what it actually detects. `evaluation` owns the failing threshold;
   this segment owns the coaching one.
4. **How often do learners talk over the coach?** Barge-in is recorded as a distinct
   cancelled state specifically so this is answerable. It has not been asked.
5. **Sticky sessions**, without which live coaching cannot scale past one process.

## References

- `docs/intent/evaluation/evaluation-design.md` — supplies the metric bundle and owns the score
- `docs/intent/model-gateway/model-gateway-design.md` — owns budget, ledger and fallback
- `docs/api_contract.md` — the `coach.v1` protocol, `ExaminerFeedback`, `VoiceArtifact`

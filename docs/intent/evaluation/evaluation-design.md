---
parent: high-level-design
prefix: EVAL
---

# Evaluation

## Context and Design Philosophy

Evaluation turns an expected score and a set of observations into a metric bundle. It is
the segment that decides what a performance was worth, and it is governed by one rule
above all others.

**An unmeasured dimension is reported as unmeasured, never as zero.** A drum pattern has no
pitch. A take with no camera has no posture. A score with no dynamic markings has no
dynamics contrast. Each of those is `None`, and the weighting redistributes across the
dimensions that remain — so a take missing a dimension scores exactly as it would have if
that dimension had never existed. A zero would be a claim: *we measured, and you failed.*
The system is not entitled to make that claim about something it did not observe.

This discipline is stated in four separate module docstrings and asserted independently
across four test files. It is the closest thing this codebase has to a constitution.

**It is breakable at exactly one place: the type of an optional observation.** A dimension
arrives from the wire as a value or as nothing, and a domain type that cannot represent
"nothing" has to pick a sentinel. Every sentinel is wrong in one of two directions — treat
the sentinel as a reading and a learner is credited or penalised for something unobserved;
treat a real reading equal to the sentinel as absent and the learner's best notes are
discarded from their own average. So optional observations are typed optional all the way
down, and the scorer branches on presence rather than on value. `0.0` cents is a
measurement of a note played dead centre; `None` is silence about it.

**One grading path.** Every attempt — clip-submitted or streamed live — is graded by the
same call. The live matcher exists to cue coaching in real time, never to produce the
persisted score.

**Alignment before judgement.** Performance is compared to notation by dynamic time
warping, so a learner playing correctly but slowly is not scored as a learner playing
wrong notes. Tempo is a reported metric, not a penalty smuggled into pitch.

## Notation

`musicxml.py` parses a constrained MusicXML subset into ordered expected notes with beat
positions, plus dynamics marks. The parser is strict where strictness catches real errors:
tempo must be declared as a metronome direction rather than a bare sound element, note
durations must be integer multiples of the division unit, and each measure must sum
exactly to its time signature.

`score_generator.py` renders notation from a specification — instrument, pattern, key,
tempo, bars, difficulty — and **validates its own output through that same parser before
returning it.** A generator that emits notation the scorer cannot read fails at generation
time rather than at practice time.

## Alignment and scoring

`dtw.py` provides the alignment core. Each instrument module builds expected and observed
note sequences, aligns them, and derives its metrics.

| Instrument | Dimensions | Notes |
|---|---|---|
| piano | pitch, rhythm | the reference implementation |
| guitar | pitch, rhythm, technique | string/fret position from tablature metadata; chord events grouped by shared onset |
| violin | pitch, rhythm, intonation | intonation from per-note cents deviation |
| trumpet | pitch, rhythm | fixed-pitch monophonic; shares the core rather than duplicating it |
| drums | rhythm only | pitch is inapplicable and stored as NULL, not as a score |

`dynamics.py` scores loudness **relatively**. Absolute dBFS is microphone gain and room
acoustics, not playing, so levels are median-centred and contrast is reported as rank
agreement across consecutive written increases — did the crescendo happen — which is
gain-invariant by construction. Fewer than the minimum usable notes, or a score with no
dynamic spread, yields `None`.

`registry.py` maps instrument and evaluator version to an evaluator and a weight table, and
`combine()` renormalises weights over the dimensions actually present.

`online.py` is the live counterpart: a monotone cursor with bounded lookahead, O(1) per
note, whose committed outcomes are never revised — so live cues stay legible instead of
flickering as the matcher changes its mind.

## Versioning

Every metric bundle records the evaluator version that produced it. A change to scoring
behaviour is a new version, so a historical attempt is never retroactively reinterpreted by
a rule that did not exist when it was graded.

## Current state versus intent

**The shared alignment core is not shared.** `_tempo_metrics`, the timing tolerance
expression, the deletion and insertion costs, the pitch divisor, the pitch-quality divisor,
the alignment-confidence formula, the extra-note penalty and the low-confidence threshold
each exist in four independent copies across the piano, guitar, violin and drums modules.
They are currently identical by coincidence of authorship, not by construction.

**Duplicated constants that are meant to agree are not linked.**
`DYNAMIC_RANGE_DB = 24.0` in `dynamics.py:35` is re-hardcoded as `24.0` in `online.py:248`
under a comment asserting the two match. `MAX_FRET` is 24 in `guitar.py:24` and 12 in
`score_generator.py:86`. Three unrelated intonation thresholds exist: 30 cents for scoring,
20 cents for coaching text, and a coaching phrase that says "a quarter-tone", which is 50.

**The weight table carries no rationale.** `INSTRUMENT_WEIGHTS` decides what a performance
is worth, and no individual number in it is justified. Only the renormalisation property is
argued for.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Unmeasured dimension | `None`; weight redistributes | Score 0; score a neutral 0.5 | Zero is a claim about something not observed. Redistribution makes a missing dimension cost nothing. |
| Drum pitch | NULL | Score 1.0, or omit drums from pitch weighting silently | Pitch is inapplicable, not perfect. NULL says which. |
| Alignment | Dynamic time warping | Fixed-window matching against wall-clock | A correct-but-slow performance must not read as wrong notes. |
| Tempo | Reported as a metric | Penalised inside rhythm | Playing under tempo is information, not automatically an error. |
| Dynamics | Relative: median-centred, rank agreement | Absolute dBFS thresholds | Absolute level measures the microphone and the room. Rank agreement is gain-invariant. |
| Weight application | Renormalise over present dimensions | Fixed weights with zeros | Fixed weights make an absent dimension a penalty. |
| Live matching | Separate monotone matcher, never authoritative | Reuse DTW live; let the live result be the score | DTW needs the whole sequence; and one grading path is what keeps live and batch from diverging. |
| Committed live outcomes | Never revised | Re-decide as more notes arrive | A cue that contradicts itself mid-phrase is worse than no cue. |
| Generated notation | Self-validated through the real parser | Trust the generator | A generator that emits unreadable notation should fail at generation, not at practice. |
| Parser strictness | Reject a bar that does not sum | Pad or truncate silently | Silent repair produces a score that is not the one written. |
| Optional observations | Typed `float \| None` end to end; branch on presence | A sentinel value such as `0.0`; a parallel `has_x` flag | A sentinel cannot separate "measured, and it was zero" from "not measured", and both readings of it are wrong. A parallel flag can disagree with the value it guards. |
| Fixing a scorer that raises | Corrected in place, no version bump | Publish `violin-dtw-v2` and leave v1 registered | Versions exist so a stored bundle is never re-judged by a rule that postdates it. No violin bundle can carry the old rule: it raised on the ordinary path, so nothing was ever graded by it. Leaving it registered would strand every seeded violin exercise on a scorer known to crash. |
| Scoring changes | New evaluator version | Edit in place | Otherwise a past attempt is re-judged by a rule that did not exist. |

## Open Questions & Future Decisions

### Deferred

1. **`DYNAMIC_RANGE_DB = 24.0` is self-labelled a guess** and named in its own source as the
   first constant to recalibrate. It has not been calibrated.
2. **No golden test matrix exists** across perfect / slow / fast / wrong-pitch /
   missed-note / extra-note / silence, per instrument.
3. **Whether the four alignment cores should be unified.** They are identical today by
   authorship. Unifying them is a real refactor; leaving them is a real drift risk.
4. **The weight table is unjustified.** Whether piano pitch is worth 0.45 and rhythm 0.30 is
   the single most consequential set of numbers in the product, and no rationale is recorded.
5. **Polyphonic scoring is unexercised.** Chord-event grouping exists for guitar and has
   never been fed real polyphony, because the capture path is monophonic.
6. **Live-versus-batch divergence is recorded and unread.** Every live take stores its
   matched, missed and extra counts specifically so the online matcher's quality is
   measurable. Nobody has looked at the numbers.
7. **`score_generator.py:453`** documents a rock-groove kick/snare placement that the code
   at 457-462 does not produce.

## References

- `docs/intent/observation/observation-design.md` — supplies the observations
- `docs/intent/coaching/coaching-design.md` — consumes the metric bundle
- `docs/intent/progression/progression-design.md` — consumes the outcome
- `docs/api_contract.md` — `PerformanceMetrics`, `Exercise`

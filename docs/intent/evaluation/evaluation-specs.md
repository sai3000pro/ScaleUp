# Evaluation — EARS Specs

Prefix: `EVAL`. Facets: `NOTE` (notation parsing), `GEN` (score generation),
`ALIGN` (alignment), `INST` (per-instrument scoring), `DYN` (dynamics),
`WEIGHT` (combination), `LIVE` (online matching), `VER` (versioning).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Notation

- [x] **EVAL-NOTE-001**: The parser shall produce ordered expected notes with beat positions from a constrained MusicXML subset.
- [x] **EVAL-NOTE-002**: The parser shall require tempo to be declared as a metronome direction, and shall reject a score that declares it only as a playback attribute.
- [x] **EVAL-NOTE-003**: The parser shall reject a note duration that is not an integer multiple of the score's division unit.
- [x] **EVAL-NOTE-004**: The parser shall reject a measure whose durations do not sum to its time signature.
- [x] **EVAL-NOTE-005**: The parser shall read dynamics markings and hairpins, and shall report the expected level at a given beat.
- [x] **EVAL-NOTE-006**: The parser shall ignore a direction type it does not recognise rather than failing the score.
- [x] **EVAL-NOTE-007**: The parser shall read string and fret metadata where present.
- [x] **EVAL-NOTE-008**: The parser shall read unpitched percussion events and the drum each names.

## Score generation

- [x] **EVAL-GEN-001**: The generator shall produce notation from an instrument, pattern, key, tempo, bar count and difficulty.
- [x] **EVAL-GEN-002**: The generator shall validate every score it produces through the notation parser before returning it.
- [x] **EVAL-GEN-003**: The generator shall fit a generated phrase within the target instrument's playable range.
- [x] **EVAL-GEN-004**: The generator shall produce identical notation for identical inputs.
- [x] **EVAL-GEN-005**: Where a model proposes a musical upgrade, the system shall accept a note list rather than raw notation, and shall render it through the same generator.
- [x] **EVAL-GEN-006**: When a proposed upgrade fails validation, the system shall fall back to the procedurally generated score rather than failing the request.
- [x] **EVAL-GEN-007**: The system shall store a generated score once per course and content hash.
- [x] **EVAL-GEN-008**: The system shall attach an exercise to a node only when its curriculum version is published.

## Alignment

- [x] **EVAL-ALIGN-001**: The system shall align performed notes to expected notes by dynamic time warping rather than by wall-clock position.
- [x] **EVAL-ALIGN-002**: The system shall report missed notes, extra notes, and alignment confidence.
- [x] **EVAL-ALIGN-003**: The system shall report tempo as a measured metric rather than folding it into rhythm accuracy.
- [x] **EVAL-ALIGN-004**: When alignment confidence falls below the reliability floor, the system shall report the result as low confidence.
- [x] **EVAL-ALIGN-005**: When no notes were detected, the system shall report silence explicitly and shall not award a score.

## Per-instrument scoring

- [x] **EVAL-INST-001**: The system shall select an evaluator by instrument and evaluator version.
- [x] **EVAL-INST-002**: The system shall score piano on pitch and rhythm.
- [x] **EVAL-INST-003**: The system shall score guitar on pitch, rhythm and fret position, grouping notes that share an onset into chord events.
- [x] **EVAL-INST-004**: The system shall score violin on pitch, rhythm and intonation.
- [x] **EVAL-INST-005**: The system shall score trumpet through the shared pitch and rhythm core under its own evaluator version.
- [x] **EVAL-INST-006**: The system shall score drums on rhythm and drum identity.
- [D] **EVAL-INST-007**: The system shall not report a pitch score for drums.
- [D] **EVAL-INST-008**: The system shall not infer fingering, embouchure, or breath support from audio alone.
- [x] **EVAL-INST-009**: When a performed note carries no cents deviation, the violin evaluator shall report intonation as unmeasured rather than raising.
- [x] **EVAL-INST-010**: The violin evaluator shall count a note played exactly in tune toward intonation rather than excluding it.
- [x] **EVAL-INST-011**: When a chord technique score is unavailable, the guitar evaluator shall redistribute its weight rather than scoring it as zero.

## Dynamics

- [x] **EVAL-DYN-001**: The system shall score dynamics relative to the take's own median level, never against an absolute decibel threshold.
- [x] **EVAL-DYN-002**: The system shall report dynamic contrast as agreement with the direction of written level changes.
- [x] **EVAL-DYN-003**: When fewer than the minimum usable notes carry a level, the system shall report dynamics as unmeasured.
- [x] **EVAL-DYN-004**: When the score contains no meaningful dynamic spread, the system shall report dynamics as unmeasured.

## Combination

- [x] **EVAL-WEIGHT-001**: The system shall report an unmeasured dimension as unmeasured, never as zero.
- [x] **EVAL-WEIGHT-002**: The system shall renormalise its weights across the dimensions actually present.
- [x] **EVAL-WEIGHT-003**: When no optional dimension is present, the overall score shall equal the score the base evaluator produced, unchanged.
- [x] **EVAL-WEIGHT-004**: The system shall record which dimensions contributed to a bundle.
- [ ] **EVAL-WEIGHT-005**: Each weight in the instrument weight table shall carry a recorded rationale.

## Live matching

- [x] **EVAL-LIVE-001**: The live matcher shall advance monotonically with bounded lookahead and constant work per note.
- [x] **EVAL-LIVE-002**: The live matcher shall never revise an outcome it has already committed.
- [x] **EVAL-LIVE-003**: When expected notes pass without a match, the live matcher shall register them as missed.
- [x] **EVAL-LIVE-004**: The live matcher shall share its cost weights with the batch scorer rather than restating them.
- [x] **EVAL-LIVE-005**: Replaying a take's buffered notes through the live matcher shall reproduce its state exactly.
- [D] **EVAL-LIVE-006**: The live matcher's result shall never be persisted as an attempt's score.

## Versioning

- [x] **EVAL-VER-001**: Every metric bundle shall record the evaluator version that produced it.
- [x] **EVAL-VER-002**: A change in scoring behaviour shall be published as a new evaluator version rather than altering an existing one.
- [x] **EVAL-VER-003**: Re-grading an already-graded attempt shall return the stored result and shall not award experience a second time.
- [x] **EVAL-VER-004**: A take submitted over the live socket and the same notes submitted over the clip path shall produce identical metric bundles.

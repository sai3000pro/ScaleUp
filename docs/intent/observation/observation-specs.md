# Observation — EARS Specs

Prefix: `OBS`. Facets: `NOTE` (audio segmentation), `POSE` (body posture),
`HAND` (hand technique), `RED` (take-level reduction), `TIME` (visual timeline),
`ASSESS` (skill-aware visual assessment).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

**Producers live in `capture`.** This segment owns the reducers; the code paths that feed
them are `capture`'s. That the live audio path bypasses this segment's segmenter, that no
body-pose landmarker exists, and that the technique panel samples only its mock branch are
tracked as `CAP-MIC-008`, `CAP-CAM-006` and `CAP-CAM-008`.

---

## Note segmentation

- [x] **OBS-NOTE-001**: The note segmenter shall be a pure fold over pitch frames, acquiring no audio device, clock, or network resource.
- [x] **OBS-NOTE-002**: When a frame's confidence rises above the note-on threshold, the segmenter shall open a note.
- [x] **OBS-NOTE-003**: While a note is open, the segmenter shall keep it open until confidence falls below the note-off threshold, which shall be lower than the note-on threshold.
- [x] **OBS-NOTE-004**: When a frame's level rises above the note-on level threshold, the segmenter shall permit a note to open; while a note is open it shall close only after the level has remained below the note-off level threshold for the debounce count.
- [x] **OBS-NOTE-005**: When the level rises by at least the re-attack threshold within the re-attack window while a note is open, the segmenter shall close the current note and open a new one, even if the detected pitch has not changed.
- [x] **OBS-NOTE-006**: When a candidate note is shorter than the minimum note duration, the segmenter shall discard it rather than emit it.
- [x] **OBS-NOTE-007**: When the detected pitch changes for at least the pitch-change frame count, the segmenter shall close the current note and open a new one.
- [x] **OBS-NOTE-008**: The segmenter shall aggregate a note's pitch as the median over its frames rather than the mean.
- [x] **OBS-NOTE-009**: The segmenter shall report a note's pitch as a whole MIDI number and its sub-semitone residual separately as a cents deviation.
- [D] **OBS-NOTE-010**: The segmenter shall not report a fractional MIDI pitch.
- [x] **OBS-NOTE-011**: Given identical input frames, the segmenter shall produce identical segments.

## Posture

- [x] **OBS-POSE-001**: The posture reducer shall be pure over landmark arrays, reading no MediaPipe object and no browser global.
- [x] **OBS-POSE-002**: The reducer shall normalise every distance measurement by a body scale derived from shoulder-to-hip distance, falling back to shoulder width when hips are not visible.
- [x] **OBS-POSE-003**: Where any landmark a rule requires has visibility below the minimum, the reducer shall report that metric as not-detected with zero confidence rather than a value.
- [x] **OBS-POSE-004**: Where a rule's required landmarks were visible in less than the minimum share of recent frames, the reducer shall report that metric as low-confidence rather than a value.
- [x] **OBS-POSE-005**: The reducer shall select the rule set by instrument, and shall report metrics only for rules in that instrument's set.
- [x] **OBS-POSE-006**: The reducer shall evaluate the violin chin-tilt rule against a non-zero target angle.
- [x] **OBS-POSE-007**: Where a per-learner baseline is applied, the reducer shall shift each threshold band by no more than half that band's width.
- [x] **OBS-POSE-008**: The reducer shall report each metric's raw value and unit alongside its derived status.
- [x] **OBS-POSE-009**: The reducer shall report the threshold version under which its metrics were derived.
- [D] **OBS-POSE-010**: No posture rule shall derive a measurement from a landmark's depth coordinate.
- [ ] **OBS-POSE-012**: Where the drums rule set declares a grip-openness threshold, a rule shall compute that metric or the threshold shall be withdrawn.
- [x] **OBS-POSE-013**: Every instrument with a published curriculum shall have a declared posture rule set; no instrument shall reach the shared rules alone by omission.

## Hand technique

- [x] **OBS-HAND-001**: The technique reducer shall be pure over hand-landmark arrays.
- [x] **OBS-HAND-002**: The reducer shall report wrist elevation and hand stability with an explainable status rather than a bare score.
- [x] **OBS-HAND-003**: Where hand landmarks were present in less than the minimum share of recent frames, the reducer shall report low confidence rather than a value.
- [D] **OBS-HAND-004**: The technique reducer shall not report a judgement of musical quality.

## Take-level reduction

- [x] **OBS-RED-001**: The client shall accumulate posture samples across a take and reduce them once at its end, rather than submitting a single frame.
- [x] **OBS-RED-002**: The client shall reduce each metric key to its median value, its mean confidence, and the worst status observed.
- [x] **OBS-RED-003**: The client shall bound retained samples so a long take cannot grow without limit.
- [x] **OBS-RED-004**: The server shall count a metric toward posture accuracy only where its status is good or needs-attention and its confidence meets the minimum.
- [x] **OBS-RED-005**: When no metric qualifies, the server shall report posture accuracy as unmeasured rather than as zero.
- [x] **OBS-RED-006**: When posture is unmeasured, the take shall score exactly as it would if posture had never been submitted.
- [x] **OBS-RED-007**: The observation payload shall carry derived metrics only, and shall never carry landmarks or video.
- [ ] **OBS-RED-008**: The server shall persist the threshold version submitted with an observation.

## Visual timeline

- [x] **OBS-TIME-001**: Every selected-video observation frame shall retain its media timestamp and the versions of the reducers that produced it.
- [x] **OBS-TIME-002**: The visual summary shall reduce each metric to its median value, mean confidence, good-frame ratio, and measured-frame count using a pure deterministic function.
- [x] **OBS-TIME-003**: Adjacent needs-attention observations for the same metric shall collapse into one timestamped highlight rather than producing one correction per sampled frame.
- [x] **OBS-TIME-004**: A selected video with no countable visual metrics shall complete as an unmeasured result rather than receive a zero technique score.
- [D] **OBS-TIME-005**: The visual summary and export shall contain no notes, pitch, rhythm, MusicXML alignment, DTW result, raw landmark, video frame, or audio field.
- [x] **OBS-TIME-006**: Given identical derived frame observations, the visual summary and export shall be identical.

## Skill-aware visual assessment

- [x] **OBS-ASSESS-001**: The client shall declare every visual assessment as a versioned profile with a stable profile ID, instrument, curriculum skill slug, title, confidence floor, coverage floor, overall pass floor, and one or more positively weighted metric requirements that declare criticality and a pass floor.
- [x] **OBS-ASSESS-002**: The selected-video surface shall derive its instrument and skill choices from the assessment-profile registry, and shall not silently fall back to an instrument-wide rule set when a profile is absent.
- [x] **OBS-ASSESS-003**: The initial profile registry shall contain `five-finger-pattern` for piano, `basic-strumming` for guitar, `open-string-bow` for violin, `trumpet-orientation` for trumpet, `basic-strokes` for drums, and `banjo-strumming` for banjo, using only the observable metrics declared in the observation design.
- [x] **OBS-ASSESS-004**: A profile requirement shall count only readings whose status is good or needs-attention and whose confidence meets that profile's confidence floor.
- [x] **OBS-ASSESS-005**: The assessment reducer shall compute a requirement's evidence coverage as its countable-reading count divided by the total sampled-frame count, so missing and low-confidence readings remain evidence about observability without becoming zero-valued technique.
- [x] **OBS-ASSESS-006**: For each requirement with countable evidence, the assessment reducer shall compute median value, good-frame ratio, and a requirement score weighted 80 percent to median value and 20 percent to good-frame ratio so the derived binary status does not double-penalise the same geometry.
- [x] **OBS-ASSESS-007**: When there are no sampled frames, a declared metric has no countable reading, or any requirement's coverage is below the profile floor, the assessment reducer shall return insufficient-evidence with a null overall score rather than pass or retry.
- [x] **OBS-ASSESS-008**: Where evidence is sufficient, the assessment reducer shall compute the overall score as the requirement-weighted mean and shall return pass only when the overall score and every critical requirement score meet their declared floors; otherwise it shall return retry.
- [x] **OBS-ASSESS-009**: A needs-attention frame or collapsed correction range shall contribute to temporal aggregates and explanations but shall never independently override the take-level outcome.
- [x] **OBS-ASSESS-010**: Metrics not named by the selected profile may appear in diagnostic feedback but shall not affect its evidence coverage, score, or outcome.
- [x] **OBS-ASSESS-011**: The visual assessment reducer shall be a pure deterministic function of a profile and timestamped derived frames, reading no browser, model, device, clock, network, audio, or raw-media resource.
- [x] **OBS-ASSESS-012**: The assessment result shall retain profile identity and version, instrument, skill slug, outcome, nullable overall score, evidence coverage, thresholds, and a per-requirement breakdown containing weight, criticality, coverage, frame counts, median value, good-frame ratio, nullable score, pass state, and relevant timestamped corrections.
- [x] **OBS-ASSESS-013**: When selected-video analysis completes, the interface shall present pass, retry, or insufficient-evidence together with overall score when measured, evidence coverage, and the result of each declared requirement.
- [x] **OBS-ASSESS-014**: The selected-video JSON export shall include the assessment profile and derived result while retaining no raw video, image frame, landmark, note, pitch, rhythm, MusicXML alignment, DTW, or audio field.

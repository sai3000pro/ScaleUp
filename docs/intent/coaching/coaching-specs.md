# Coaching — EARS Specs

Prefix: `COACH`. Facets: `POLICY` (when to speak), `CUE` (what to say),
`EXAM` (post-take examiner), `VOICE` (synthesis and delivery),
`SESSION` (the live socket).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Turn policy

- [x] **COACH-POLICY-001**: The policy shall receive the current time and the elapsed silence as parameters, and shall read no clock of its own.
- [x] **COACH-POLICY-002**: The policy shall import nothing outside the standard library.
- [x] **COACH-POLICY-003**: The policy shall speak only after the learner has been silent for at least the minimum silence duration.
- [x] **COACH-POLICY-004**: The policy shall permit at most the per-take maximum number of utterances.
- [x] **COACH-POLICY-005**: The policy shall require at least the minimum interval between consecutive utterances.
- [x] **COACH-POLICY-006**: The policy shall not repeat a cue of the same kind within its cooldown period.
- [x] **COACH-POLICY-007**: Where the learner has lost their place, the policy shall permit one interrupting utterance per take.
- [x] **COACH-POLICY-008**: When the policy declines to speak, it shall report an explicit reason for the suppression.
- [x] **COACH-POLICY-009**: The policy shall receive the remaining model budget as an input rather than discovering exhaustion by failure.
- [x] **COACH-POLICY-010**: Given identical inputs, the policy shall reach an identical decision.
- [D] **COACH-POLICY-011**: The policy shall not speak merely because time has passed without a fault.

## Cue selection

- [x] **COACH-CUE-001**: The system shall order cue selection by severity, considering a lost place before missed or extra runs, and those before pitch and timing.
- [x] **COACH-CUE-002**: The system shall raise a cue for a run of missed notes only once the run reaches its threshold.
- [x] **COACH-CUE-003**: The system shall distinguish rushing from dragging by reading a signed timing bias.
- [x] **COACH-CUE-004**: Every cue shall have a deterministic sentence available with no model call.
- [x] **COACH-CUE-005**: The system shall recognise a sustained passage without fault and may acknowledge it.
- [x] **COACH-CUE-006**: The system shall distinguish playing sharp from playing flat, and shall not report a flat passage as sharp.
- [x] **COACH-CUE-007**: The system shall raise an intonation cue at a smaller deviation than the one at which the evaluator fails intonation, so a learner is warned before being penalised.
- [x] **COACH-CUE-008**: A spoken correction shall describe the deviation it actually detected, rather than a larger one.

## Post-take examiner

- [x] **COACH-EXAM-001**: The system shall interpret each metric into words before it reaches a prompt.
- [x] **COACH-EXAM-002**: The system shall determine whether a metric improved using an explicit polarity table rather than the sign of its change.
- [x] **COACH-EXAM-003**: The system shall produce a complete assessment with no model configured.
- [x] **COACH-EXAM-004**: Where a model is configured, it shall rewrite the assessment's wording and shall not alter any score.
- [x] **COACH-EXAM-005**: The system shall constrain examiner output to a typed schema and validate it before persistence.
- [x] **COACH-EXAM-006**: When model feedback fails or is invalid, the system shall persist the deterministic assessment.
- [x] **COACH-EXAM-007**: The system shall persist the persona, tone and prompt version alongside the feedback.
- [D] **COACH-EXAM-008**: The examiner shall not comment on a dimension that was not measured.
- [x] **COACH-EXAM-009**: The system shall report cross-session trends computed on read rather than from stored aggregates.

## Voice

- [x] **COACH-VOICE-001**: Every response shall carry spoken text, whether or not audio was synthesised.
- [x] **COACH-VOICE-002**: Where no voice provider is configured, the system shall remain fully usable and the interface shall speak the text itself.
- [x] **COACH-VOICE-003**: The system shall cache synthesised audio by content so that re-reading a take does not resynthesise it.
- [x] **COACH-VOICE-004**: The cache key shall include the configured voice, so changing the persona does not serve the previous one.
- [x] **COACH-VOICE-005**: When synthesis fails, the system shall degrade to text and shall not fail the take.
- [x] **COACH-VOICE-006**: During a take, the system shall synthesise a sentence at a time rather than waiting for a complete utterance.
- [x] **COACH-VOICE-007**: The system shall use a latency-optimised model tier for live synthesis.
- [x] **COACH-VOICE-008**: The system shall record voice synthesis spend in the same ledger as model calls.

## Live session

- [x] **COACH-SESSION-001**: The socket shall authenticate from a token in the first frame, never from the connection URL.
- [x] **COACH-SESSION-002**: The socket shall reject a client whose protocol version it does not support.
- [x] **COACH-SESSION-003**: The socket shall refuse a second claim on a take already held.
- [x] **COACH-SESSION-004**: The socket shall stream cue text incrementally rather than only on completion.
- [x] **COACH-SESSION-005**: When the learner resumes playing during an utterance, the system shall abandon it and record the call as cancelled rather than as successful.
- [x] **COACH-SESSION-006**: When first-token latency exceeds its limit, the system shall abandon generation and deliver the deterministic sentence.
- [x] **COACH-SESSION-007**: The system shall persist each utterance through a session separate from the socket's receive loop.
- [x] **COACH-SESSION-008**: On finalisation, the system shall submit the take through the standard attempt path under an idempotency key derived from the take.
- [x] **COACH-SESSION-009**: When the socket disconnects, the client shall be able to submit the same take over the clip path and produce exactly one attempt.
- [x] **COACH-SESSION-010**: A coach session shall record its live matched, missed and extra counts as divergence telemetry.
- [D] **COACH-SESSION-011**: A coach session shall not award experience, mastery, or any progression of its own.
- [x] **COACH-SESSION-012**: A take shall remain resumable when the request reaches a different application instance.

# Roadmap — ScaleUp

**Last reviewed:** 2026-09-28
**Product direction:** multi-instrument practice over the existing Learn-Anything
learning loop. The learner-facing chooser currently covers piano, guitar,
violin, trumpet, drums, and banjo; this does not imply equal depth of pedagogy or
hardware-backed pitch extraction across those instruments.

Learn-Anything already turns structured educational content into a prerequisite
DAG, lets a learner drill nodes, awards EXP, and schedules review through decay.
The next product slice applies that loop to instrument practice:

```text
choose instrument and exercise
  → capture audio (and optionally camera landmarks)
  → align performance to MusicXML
  → score pitch, rhythm, and technique
  → explain the metrics as an examiner
  → speak concise coaching feedback
  → award EXP and update mastery
  → turn decayed skills into daily practice quests
```

The target is a reproducible, deterministic demo with versioned curricula,
score-backed exercises, and fake providers at external boundaries. Production
hosting, live hardware validation, and audio-to-note quality remain explicit
verification gates rather than implied accomplishments.

---

## Product decisions

### First instrument: piano

Piano is the first DAG and evaluation target. It gives us:

- unambiguous note identity and onset timing for a first MusicXML fixture set;
- exercises that can begin as monophonic right-hand phrases before polyphony;
- measurable pitch and rhythm feedback without requiring a specialised acoustic
  model;
- a reusable skill tree shape for the later violin, trumpet, and drums trees.

The piano evaluator supports short, mostly monophonic exercises:
scales, five-finger patterns, and simple melodies. Chords, sustain-pedal nuance,
left/right-hand coordination, and full-song alignment are follow-on work, not
hidden MVP requirements.

### Next instrument: guitar

Guitar is the second instrument after the piano contracts are stable. The first
guitar curriculum should target standard-tuned six-string guitar and start with
single-note exercises, string/fret awareness, pick or finger attack, and a small
set of open chords. It should not claim to infer exact fingering from audio alone:
MusicXML/tablature supplies expected string/fret metadata, while audio measures
what can be heard and camera metrics cover only technique signals that have
sufficient confidence.

Guitar gets its own versioned curriculum and exercise fixtures, but shares the
session, scoring, feedback, EXP, SRS, and quest contracts. The guitar tree is the
first proving ground for making curriculum graphs data-driven rather than adding
another tree in Python seed code.

### Architecture boundaries

- **Postgres remains authoritative.** Instrument trees, exercises, attempts,
  metrics, feedback, EXP, and quest state belong in Postgres. Derived search and
  graph projections remain rebuildable.
- **The existing FastAPI backend remains the application boundary.** The Render
  deployment is a hosting decision, not a reason to bypass routers, services,
  repositories, or the domain layer.
- **The browser owns capture and lightweight vision.** Web Audio records the
  practice clip and emits monophonic pitch observations. MediaPipe tracks hand
  and pose landmarks in-browser when the learner grants camera access. Send only
  derived metrics to scoring; raw video stays local.
- **Python owns deterministic evaluation.** The browser capture adapter emits
  canonical notes; Python normalizes MusicXML and uses Dynamic Time Warping to
  align events. Raw-audio feature extraction on the server is not part of this
  scoring path.
- **n8n owns macro-orchestration, not business rules.** It may call authenticated
  backend endpoints for session completion, feedback, nightly quest refresh, and
  audio retention. Domain calculations stay in services/domain so they remain
  testable, idempotent, and usable without n8n.
- **LLM callers name roles.** Add a performance-feedback role to the existing LLM
  registry; callers must not name a provider or model. Prompts remain versioned
  files with hashes recorded in `llm_calls`.
- **ElevenLabs is an optional voice provider.** Text feedback must work without a
  voice API key. The provider belongs behind a service boundary with a fake
  implementation and a text-only fallback.
- **Base44 is a rapid UI/prototyping input, not a reason to discard typed
  contracts.** Prototype the practice and skill-tree screens there if useful, but
  keep the current Next.js application as the integration target until auth,
  media capture, accessibility, and the API contract have parity. Replacing the
  frontend is a separate decision gate, not part of the scoring MVP.

These boundaries preserve the layering in `CLAUDE.md`:

```text
routers  →  services  →  {repositories | models | llm | vector}  →  domain
tasks    →  services
domain   →  nothing
```

---

## How the DAG becomes data-driven

The hardcoded piano tree is a deterministic source fixture; runtime curricula use
the **versioned curriculum compiler**: source
material produces a draft graph, validation and review produce a published graph,
and only published graphs can unlock skills or create quests.

### Canonical data model

Separate stable skill identity from a particular curriculum graph:

- `Instrument` — piano, guitar, violin, trumpet, drums, and future instruments;
- `Curriculum` and immutable `CurriculumVersion` — the scope, source set,
  evaluator capabilities, and publication status for one tree;
- `SkillDefinition` — stable skill ID, title, outcomes, aliases, instrument scope,
  difficulty, and assessment metadata;
- `CurriculumNode` — membership of a skill in a version, including its position,
  labels, and exercise references;
- `PrerequisiteCandidate` — proposed directed edge with confidence, relation type,
  and status (`draft`, `accepted`, `rejected`, `ambiguous`);
- `Evidence` — source document/chunk, quote or structured rationale, extractor
  version, and hash proving why a candidate edge exists;
- `CurriculumReview` — human decision, reviewer, timestamp, and reason;
- `Exercise` and `AssessmentCapability` — what can actually be taught and measured
  for a node on each instrument.

A published version is immutable. A revision creates a new version and maps stable
skill IDs forward, so a learner's EXP and SRS history do not change because a
curriculum editor improved an edge.

### Curriculum compiler flow

```text
source bundle
  → parse, clean, chunk, and hash
  → extract candidate skills and aliases
  → normalize and deduplicate skill identities
  → infer prerequisite candidates over the closed vocabulary
  → attach quote/structured evidence
  → reject cycles, validate capabilities, and transitively reduce
  → human review of new/ambiguous/high-impact edges
  → publish immutable CurriculumVersion
  → project to the learner graph and exercise index
```

1. **Source bundle.** A curriculum author supplies method books, standards,
   exercise metadata, or an expert-authored outline. The existing ingestion and
   provenance system stores the material; no model receives an untraceable blob.
2. **Candidate extraction.** A versioned LLM role or deterministic parser proposes
   small, teachable skills and aliases. The model may propose; it cannot publish.
   A normalization service merges spelling variants and asks for review when two
   skills may be different granularity.
3. **Evidence-backed edge inference.** Reuse the existing two-pass prerequisite
   extraction over a closed vocabulary. Every proposed edge must include a quote
   or structured source reference that was actually available to the extractor.
   The system records confidence, extractor/prompt version, and source hashes.
4. **Graph validation.** The domain validator rejects self-edges, missing nodes,
   cycles, impossible prerequisite directions, duplicate edges, and nodes without
   an assessment path unless they are explicitly structural. Transitive reduction
   happens only after accepted edges are chosen.
5. **Review and publication.** A review queue shows the proposed edge, evidence,
   affected unlock path, and confidence. High-confidence, low-impact candidates
   may be batch-approved later, but the initial guitar tree requires explicit
   approval. Rejected and ambiguous candidates remain visible for audit.
6. **Runtime projection.** Postgres stores the published version. Neo4j/Chroma or
   other indexes are derived projections. Learner progress references stable skill
   IDs plus the curriculum version; projections can be rebuilt without changing
   progression truth.

n8n may trigger extraction, review notifications, publication, or projection
rebuilds, but the compiler and publication rules stay in backend services. This
prevents a workflow edit from silently changing unlock semantics.

### Migration path from the hardcoded fixture

1. **Fixture:** keep the piano JSON only as a deterministic test/demo source.
2. **Data seed:** load that JSON through the same `CurriculumVersion` tables and
   validator; no runtime code should branch on `if piano`.
3. **Guitar draft:** create guitar skills and exercises as database draft records,
   using the same schema and review screen as piano.
4. **Generated candidates:** run the compiler against a curated guitar source
   bundle and compare generated candidates with the expert seed.
5. **Publish:** approve the reviewed guitar version, pin the demo to its version,
   and expose version IDs in API responses.
6. **Continuous revisions:** publish a new version for changed prerequisites,
   preserve stable skill IDs where meaning is unchanged, and provide explicit
   mappings when a skill splits, merges, or is retired.

This gives us generated curriculum without making the learner a beta tester for
unreviewed LLM edges.

---

## Definition of done for the first demo

A seeded user can:

1. select **Piano** and see a published prerequisite DAG;

2. open an unlocked exercise with a MusicXML-backed expected performance;
3. record a short attempt in the browser with Web Audio;
4. submit the recording and receive deterministic pitch/rhythm metrics;
5. optionally enable the camera and receive a technique metric with confidence;
6. see an examiner-style explanation of the metrics, with fake LLM output by
   default;
7. hear the feedback through ElevenLabs when configured, or read it as text when
   it is not;
8. earn EXP, see the next node unlock, and find a decayed skill on the daily
   quest board;
9. repeat the same submission safely without duplicate EXP or duplicate feedback.

The demo must run with `LLM_PROVIDER=fake`, no ElevenLabs key, and no live n8n
workflow. The fake path is not a mock around the core: it exercises the same API,
service, persistence, grading, progression, and idempotency contracts.

---

## Work board

Each phase below is intended to leave the repository runnable and typechecking.
Changes should remain bounded, include contract/tests, and update this document
with evidence as delivery progresses.

### 0. Foundation and contracts — do first

**Outcome:** the new concepts have stable interfaces before providers or UI are
introduced.

- [x] Add an instrument vocabulary and ownership model. `Instrument`, stable
  `SkillDefinition`, and `CurriculumVersion` now own the versioned graph scope.
- [x] Add models/migrations for curriculum versions, skill definitions,
  prerequisite candidates, evidence, and reviews.
- [x] Add persisted exercise, score asset, practice session, performance attempt,
  metric bundle, examiner feedback, voice artifact, and raw recording records
  with evaluator/version provenance.
- [x] Add an explicit publication state so draft curriculum cannot affect unlocks,
  SRS, or quests; only `publish()` projects to `skill_nodes`.
- [x] Define IDs, lifecycle states, timestamps, score/evaluator versions, and
  metric provenance; time-derived mastery/proficiency remain computed on read.
- [x] Extend `docs/api_contract.md` and `frontend/lib/types.ts` for tree,
  exercise, session, score, feedback, and quest responses with an executable
  backend/type mirror check. Job polling semantics are documented for ingestion;
  scoring remains synchronous.
- [x] Define recording size/formats, browser capture settings, retention,
  camera consent and owner deletion. Production retention execution remains an
  operations verification gate described in phase 8.
- [x] Define idempotency for session submission and webhook feedback; retries
  return stored results and do not repeat EXP or paid synthesis.
- [x] Add offline piano/instrument fixtures and deterministic fake boundaries;
  unit evaluation does not require an LLM, camera, n8n, or ElevenLabs.

**Likely files:** `backend/app/models/`, `backend/app/services/`,
`backend/app/domain/`, `backend/app/api/routers/`,
`backend/alembic/versions/`, `docs/api_contract.md`, `frontend/lib/types.ts`.

**Acceptance:** migrations apply cleanly; the seed is idempotent; unit tests can
construct the fixture without Docker; the OpenAPI/type contract has no drift.

### 1. Piano DAG and progression vertical slice

**Outcome:** the existing RPG loop works for a piano learner before audio exists.

- [x] Author the first deterministic piano DAG as checked-in curriculum data, not
  LLM output.  It covers keyboard layout, finger numbers, rhythm, five-finger

  patterns, melodies, scales, triads, chord progressions, and sight reading.
  It is now loaded through the published curriculum tables and generic compiler.
- [x] Validate acyclicity, missing prerequisites, duplicate slugs, and unreachable
  nodes at seed time; unit coverage currently exercises the shared DAG validator.
- [x] Reuse the current EXP, SRS, and progress services rather than creating
  instrument-specific copies. Graph state and unlocks continue to derive from the
  existing learner graph on refresh.
- [x] Attach the first piano exercise and MusicXML asset to a published node. A
  broader exercise catalog and prerequisite-aware selection remain follow-on work.
- [x] Render the shared instrument skill graph with distinct states and
  prerequisite explanations; a decayed node links into practice/quest flow.

**Likely files:** `backend/app/seed.py`, `backend/app/domain/`, existing skill-node
models/services, `frontend/components/skill-tree/`,
`frontend/app/courses/[courseId]/page.tsx`.

**Acceptance:** the seeded piano tree renders as a DAG; a drill changes EXP and
unlock state exactly once; existing textbook-course behavior remains intact.

### 2. Score assets and browser audio capture

**Outcome:** a learner can record and submit a bounded piano practice clip.

- [x] Add a MusicXML asset loader with validation, canonical note representation,
  tempo/time-signature handling, and a score hash. The persisted asset boundary
  rejects malformed scores during evaluation; upload/size policy is still open.
- [x] Build a browser recording control using the Web Audio API
  (`frontend/lib/pitchDetection.ts`): explicit permission, recording/stopping
  states, typed denied/unavailable/unsupported failures, canonical segmented
  note observations, and best-effort raw clip preservation. It is clip-based and
  separate from the optional live-coach WebSocket flow.
- [x] Preserve the original recording as content-addressed storage with
  course/user ownership and deletion rules. `POST /api/recordings` dedupes per
  (user, content sha256), the owner streams bytes back from a separate content
  endpoint, and `DELETE` removes a take at any time. The attempt submission
  cites its take by `recording_id` (ownership and course validated; foreign
  takes rejected), and the frontend's MediaRecorder captures `audio/webm`
  alongside the pitch analysis — best-effort, so a failed upload never sinks
  the take's score.
- [ ] Move scoring to `202` plus a pollable job if measured production workloads
  exceed the synchronous envelope. Current bounded requests are synchronous.
- [x] Add a no-microphone fixture path so the demo and tests can submit known
  canonical observations through the same API contract as the microphone path.
- [x] Add a typed practice panel with exercise selection, score breakdown,
  retry/error and capture-failure feedback, persisted results, fixture retry,
  feedback speech/browser-TTS fallback, and a daily-quest call to action.
- [x] Bound scoring submissions to 256 KiB and 256 observations before JSON
  parsing; keep the 50 ms target as a measured golden-fixture objective rather
  than rejecting learner attempts based on host load.

**Likely files:** `frontend/components/` practice-session components,
`frontend/lib/api.ts`, backend storage/job services, score-asset models, and the
existing job router/contract.

**Acceptance:** fixture notes reach a persisted attempt; capture failures,
empty audio, bounded scoring payloads, duplicate submission, and owner deletion
have explicit behavior. Database-dependent persistence/retention tests require
Postgres and are not covered by the offline validation gate.

### 3. Deterministic piano evaluator and deployment readiness

**Outcome:** canonical observations and MusicXML produce explainable metrics;
external deployment remains an explicit follow-up.

- [x] Implement a pure score normaliser: MusicXML → ordered expected notes,
  durations, beats, and exercise metadata. The parser currently supports the
  one-part, mostly monophonic MVP subset plus chord/rest and string/fret metadata.
- [x] Implement audio capture in the browser: `frontend/lib/pitchDetection.ts`
  records from the microphone and turns the take into canonical note
  observations with autocorrelation pitch detection and onset/duration
  segmentation. Same submission contract as the fixture path.
- [x] Persist practice sessions, performance attempts, metric bundles, evaluator
  versions, low-confidence outcomes, and idempotent EXP/SRS updates for fixture
  note submissions.
- [x] Align expected and performed events with Dynamic Time Warping. Return
  pitch accuracy, onset/rhythm accuracy, tempo deviation, missed notes, extra
  notes, alignment confidence, and evaluator version for canonical observations.
- [x] Handle silence/no detected notes and low-confidence alignment explicitly;
  empty observations score zero and withhold EXP.
- [x] Level gating and hysteresis land in `frontend/lib/noteSegmentation.ts`:
  an RMS floor with a 7 dB release gap, a note-off debounce, a median filter
  over the pitch stream, and an amplitude re-attack trigger so two identical
  repeated notes stop merging into one. Clipping detection remains open.
- [x] Keep the evaluator as a pure Python boundary called by the application
  backend; no external evaluator service or provider is required.
- [x] Add deterministic coverage for perfect, wrong-pitch, missed-note, extra,
  repeated-phrase and budget cases. The 50 ms target is tracked in golden tests.
- [ ] Add measured slow/fast/noisy microphone fixtures and verify the evaluator
  on actual audio hardware; the current tests operate on canonical note events.
- [ ] Verify the same contract on the eventual Render deployment.

**Likely files:** a new `backend/app/evaluation/` or isolated scoring package,
`backend/tests/unit/` and `backend/tests/integration/`, plus Render deployment
configuration only after the service contract is stable.

**Acceptance:** golden fixtures have stable metric tolerances; the evaluator has no
LLM dependency; a low-confidence recording is surfaced as such; local and Render
responses are schema-compatible.

### 4. MediaPipe technique analysis

**Outcome:** the demo can show physical-form feedback without uploading raw video.

- [x] Add an explicit camera-consent flow and a capability check. Audio practice
  remains usable when the camera is unavailable or declined, and a mock-landmark
  mode demonstrates the metric pipeline with no camera at all.
- [x] Run the browser MediaPipe hand-landmark model (`@mediapipe/tasks-vision`,
  model loaded from the standard CDN at runtime) and retain only the 21 3D
  landmark observations or the derived metrics the exercise needs. Raw video
  never leaves the page.
- [x] Ship two piano checks that are observable and explainable — wrist
  elevation and hand stability (`frontend/lib/technique.ts`). Each returns
  value, confidence, status, and an explanation key.
- [x] Never claim the landmark model assesses musical quality it cannot see.
  Every metric is one of `not_detected`, `low_confidence`, `needs_attention`,
  or `good`, and the UI shows the confidence.
- [x] Add a deterministic mock-landmark fixture (`mockHandLandmarks`) and keep
  the metric reducer (`reduceTechnique`) pure, so the reducer is testable and
  demoable independently of the browser camera runtime.
- [x] Construct the MediaPipe body-pose producer and feed both live camera and
  selected MP4 playback through the same `VisualTracker`, hand reducer, and
  posture reducer. Media time labels every selected-video observation.
- [x] Add a local MP4 analysis surface with model-loading, analysing, paused,
  completed, cancelled, unsupported, failed, and unmeasured states; a bounded
  correction timeline; and a derived visual JSON export. The MP4 audio track is
  deliberately outside this workstream.
- [x] Aggregate the complete selected video against a versioned curriculum-skill profile. Ship
  one observable profile for each of piano, guitar, violin, trumpet, drums, and banjo; report
  Pass, Retry, or Insufficient evidence from median value, good-frame ratio, evidence coverage,
  weighted requirements, and critical requirements rather than worst-frame status.

**Likely files:** `frontend/components/practice/`, `frontend/lib/`, a small
technique-metric contract, and backend metric validation/persistence.

**Acceptance:** camera denial never blocks audio scoring; mock landmarks produce
stable metrics; no raw video is persisted by default; the UI exposes confidence;
an MP4 can be selected and analysed locally without invoking audio analysis.

### 5. Virtual examiner and voice feedback

**Outcome:** raw measurements become concise, useful coaching.

- [x] Add an `LLMRole.PERFORMANCE_FEEDBACK` role with a versioned prompt and
  schema. It receives only the canonical metrics plus exercise context and the
  deterministic floor, and runs once per attempt at submission time.
- [x] Constrain output to a typed feedback schema: summary, tone, up to three
  strengths, up to three corrections, and next step; every field falls back to
  the deterministic floor, so a partial model response is still coherent.
- [x] Validate and persist the result with the attempt: provider, persona, tone,
  strengths, corrections, and next step live on `performance_attempts`, and the
  `llm_calls` ledger records prompt id/version/SHA-256 and provider as usual.
- [x] Add a deterministic examiner (`app/evaluation/feedback.py`) that derives
  persona-voiced summary, strengths, corrections, and next step from the metric
  bundle. It is the zero-provider floor, so the practice result renders useful
  coaching even with `LLM_PROVIDER=fake`; every attempt response includes it.
- [x] Put ElevenLabs behind a voice service (`app/services/voice.py`) with a
  deterministic fake audio artifact, content-addressed cache keys, timeout
  handling, and text fallback. `POST /practice/attempts/{id}/speech` returns
  audio when a provider is configured and `spoken_text` always, so the frontend
  falls back to browser TTS. A voice failure never invalidates a score or EXP.
- [x] Streaming conversational corrections now ship alongside the clip path:
  `WS /api/practice/coach` follows the take with an online matcher, sends
  always-on cues at ~10 Hz with no model involved, and streams at most a few
  spoken corrections at phrase boundaries. It never produces a score — the take
  is graded by the same `submit_attempt` the clip path uses, under a shared
  idempotency key, so a dropped socket costs nothing.

**Likely files:** `backend/app/llm/registry.py`, `backend/app/llm/prompts/`,
`backend/app/services/`, voice-provider adapter, feedback router, and practice UI.

**Acceptance:** feedback is typed, versioned, reproducible in fake mode, shown as
text, and spoken when configured; provider failures leave the learner with a
usable result.

### 6. n8n macro-orchestration and nightly quests

**Outcome:** automation coordinates the product without becoming a second source
of truth.

- [x] Define signed, versioned webhook contracts for `session.completed`,
  `feedback.requested`, `daily-quests.refresh`, and `audio.retention.cleanup` —
  one literal route per event type under `/api/webhooks/v1/`, HMAC-SHA256 over exact request
  bytes (`X-Webhook-Signature: sha256=<hex>`, keyed by `WEBHOOK_SECRET`).
- [x] Make every n8n-triggered endpoint authenticated, idempotent, replay-safe,
  and observable: a `webhook_events` ledger keyed by caller-supplied
  `event_id` answers replays with `status: duplicate` from the stored result
  without re-executing, and `correlation_id` is echoed and persisted.
- [x] Build the happy-path webhooks: `session.completed` verifies the attempt
  and returns its outcome, `feedback.requested` returns the persisted examiner
  feedback and can synthesize (cache-backed) voice on demand, and
  `daily-quests.refresh` returns the computed board and
  `audio.retention.cleanup` removes expired audio. Versioned n8n workflow exports
  live in `n8n/workflows/`; raw-body HMAC configuration has an offline contract test.
- [x] Build nightly decay/quest refresh as a call to the existing SRS service;
  n8n schedules it but does not reimplement decay math or write quest rows behind
  the API. The board is computed on read, so a nightly refresh never double-writes
  anything.
- [x] Document local development with a fake webhook runner
  (`scripts/smoke_webhooks.py`) and a `DEV_WEBHOOKS_ENABLED` dev mode that
  accepts unsigned requests; the deployed config validator refuses
  `DEPLOYED=true` with an empty `WEBHOOK_SECRET`. The MVP works when n8n is
  stopped, using the synchronous/local task path.
- [x] Keep Celery for internal background work where it already exists. n8n
  only schedules delivery; every side effect runs through the same services the
  synchronous path uses, so there is no duplicated business workflow.

**Likely files:** `docs/api_contract.md`, backend webhook/router/service modules,
existing Celery task wiring, and a documented n8n workflow export outside the
application source if the team chooses to version it.

**Acceptance:** replaying a webhook is harmless; a failed voice step does not
rerun scoring; nightly refresh is safe to rerun; the core demo passes with n8n
unavailable.

### 6b. Perception and generated scores — shipped

- [x] Exercise scores are generated rather than hand-written
  (`app/evaluation/score_generator.py`), from a node's own title and difficulty,
  with an optional `score_compose` LLM upgrade that returns a note list the
  deterministic renderer turns into MusicXML. Every assessable published node
  gets a generated lesson set; structural/non-assessable nodes are not playable.
- [x] Dynamics are parsed from the score (`<dynamics>`, `<wedge>`,
  `<sound dynamics>`) and scored relatively — median-centred levels plus a
  gain-invariant contrast measure. Inapplicable yields NULL, never 0.
- [x] Posture from MediaPipe Pose (`frontend/lib/posture.ts`), written from
  scratch, with per-instrument rules, scale normalisation, `visibility` gating,
  and no rule built on the unreliable depth axis. Thresholds are versioned and
  the raw geometry is persisted so they can be retuned.
- [x] One evaluator registry (`app/evaluation/registry.py`) replaces the
  instrument if/elif chain, with weights that renormalise over the components
  actually present — so an attempt with no dynamics and no posture scores
  exactly as it did before either existed.

### 7. Practice UX and Base44 parity gate

**Outcome:** the new loop feels like a tutor rather than an upload form.

- [x] Add an instrument picker, shared skill-tree view, exercise selection,
  recording state, score breakdown, technique confidence, examiner feedback,
  voice control, and next-quest call to action in the existing Next.js app.
- [x] Distinguish microphone permission denial, unavailable hardware, unsupported
  capture, and generic failure; distinguish camera hardware failure from model
  runtime failure without blocking audio practice.
- [ ] Use the existing design-system redesign work and keep the skill tree's five
  distinct node states accessible. Practice-critical controls must work by
  keyboard and with reduced motion.
- [ ] Prototype the screen flow in Base44 if it accelerates exploration, then
  record the final interaction and API requirements in the repository.
- [ ] Decide at the parity gate whether Base44 can satisfy media capture, typed
  error/polling states, auth, accessibility, and provider fallback requirements.
  If not, implement the agreed screen in Next.js rather than creating a second
  production frontend.
- [x] Add loading, empty, error, retry, permission-denied, capture failure, and
  low-confidence states. Browser/device coverage and accessibility audit remain.

**Acceptance:** a new learner can complete the entire piano demo without reading
API docs; the UI distinguishes processing from grading and low confidence from
failure; mobile and desktop layouts are usable.

### 8. Demo hardening and deployment

**Outcome:** a repeatable demo can be run without paid or live dependencies.

- [x] Add one smoke script for seed → choose piano → submit fixture → score →
  feedback → EXP → quest state: `scripts/smoke_webhooks.py` completes a real
  piano attempt and drives the quest board, then fires the webhook contracts.
- [x] Add provider health and dependency status without leaking credentials:
  `GET /api/health/providers` reports the configured LLM/voice/research/email
  providers, storage backend, webhook arm status, and deployed flag — never a
  key or secret.
- [x] Define the hosted deployment — service/environment configuration, health
  checks, storage, logs, and rollback notes in `docs/deployment-hosted.md`
  (Supabase + Upstash + Koyeb + Vercel). Do not auto-migrate on process start.
- [x] Add n8n and ElevenLabs as opt-in deployment profiles: fake implementations
  remain the default for CI and local development, and the live providers are
  enabled purely by configuration (`WEBHOOK_SECRET` + `DEV_WEBHOOKS_ENABLED`,
  `VOICE_PROVIDER` + `ELEVENLABS_API_KEY`), with the deployed validator
  refusing to start without them configured.
- [ ] Verify production data deletion and retention behavior. Policy is 30 days
  for raw recordings and synthesized audio, and indefinite for attempts, metrics,
  feedback, and progress. Audio bytes currently live in PostgreSQL `LargeBinary`
  rows; the cleanup service removes those rows,
  but audio is not wired to external object storage and has no object-deletion path.
  The n8n schedule remains an inactive template pending operator configuration
  and a live execution check.

- [ ] Capture a short golden demo recording and document the exact seed/config
  needed to reproduce it.

**Acceptance:** a clean checkout can reproduce the demo from documented commands;
CI does not need API keys; deploy failures are visible and recoverable; `pytest`,
Ruff, frontend typecheck, and frontend lint are clean.

### 9. Data-driven curriculum graph — after the MVP

**Outcome:** piano and guitar are authored through the same versioned curriculum
pipeline, and generated candidates never change learner progression without review.

- [x] Load the hardcoded piano fixture through `CurriculumVersion` tables and the
  same DAG validator used by generated curricula.
- [x] Build a draft curriculum workflow from source bundles: extract skills and
  aliases, normalize identities, infer evidence-backed prerequisite candidates,
  validate, and queue review.
- [x] Add a review API showing the proposed edge, source quote, confidence,
  cycle path, and accept/reject/ambiguous actions.
- [x] Publish immutable versions and map stable skill IDs across revisions. A
  published version projects to `skill_nodes`; drafts remain inert.
- [x] Prove the source path with a violin source bundle. It is loaded as generic
  sections, produces quoted prerequisite candidates, and is seeded through the
  same publication path without violin-specific DAG code.
- [ ] Add a browser review surface showing the affected unlock path and candidate
  evidence; the backend API is ready for it.
- [ ] Handle explicit skill split, merge, rename, and retirement mappings across
  revisions rather than relying only on stable `(instrument, slug)` identities.
- [ ] Add quality gates: evidence-backed assessment coverage (generated
  exercises exist for every assessable published node), confidence thresholds,
  and a small hand-labeled edge set for precision/recall regression testing.
- [ ] Let n8n schedule compiler jobs and notifications only; backend services own
  extraction, validation, publication, and projection writes.

**Current proof (2026-09-28):** piano, guitar, trumpet, drums, and banjo are seeded as
published, versioned curriculum graphs; violin is generated from source-section
data through the same generic source compiler and publication service — all six have deterministic score-backed lessons; piano, guitar, violin, trumpet,
and drums have evaluator paths, while banjo shares guitar scoring. The lifecycle
stores stable skill definitions, immutable versions, candidate edges, exact
chunk quotes, extractor/prompt/source hashes, and review decisions. Drafts
cannot change learner unlocks, EXP, SRS, or quests; publication ensures each
assessable node gets a deterministic lesson set. The browser candidate-review
surface, explicit skill identity migration policy, and empirical quality gates
remain open.

**Acceptance:** a new guitar curriculum can be drafted and reviewed without a
Python code change; only a published version appears in learner unlocks; a graph
revision preserves existing progress through stable ID mappings; rejected edges
remain auditable.

---

## Instrument rollout

- **Banjo — shipped curriculum and shared guitar-style evaluator:** a learner-
  selectable banjo campaign exists and uses the fretted/strummed position scorer;
  instrument-specific audio pitch detection and banjo-specific pedagogy remain
  follow-on work.
- **Guitar — shipped evaluator path:** standard-tuned six-string guitar with two
  evaluators (`app/evaluation/guitar.py`). Browser autocorrelation currently
  supplies pitch only; string/fret observations are supported by contract and
  fixture paths, not inferred from the microphone. Single-note scoring adds
  `technique_accuracy` and `position_error_count` from MusicXML/tablature
  string/fret metadata (low-E fretting drill). Open-chord/strumming scoring
  groups written notes by shared onset and observed notes by strum spread into
  chord events, scoring pitch-set coverage, rhythm, and fret position
  (G-C-D strum on the `open-chords` node). Pick-attack scoring remains
  follow-on, and fingering is never inferred from audio alone.
- **Violin — shipped evaluator path (`app/evaluation/violin.py`):** the
  source-generated curriculum has a practice loop. A DTW scorer over the shared
  pitch/rhythm core adds `intonation_accuracy` and
  `intonation_deviation_cents` from per-note cents deviation. Current browser
  autocorrelation emits pitch only, so cents must be measured by a future
  instrument-aware capture adapter; and an open-string scale
  exercise is seeded onto the `open-string-bow` node. Bowing, posture, and
  wrist checks remain camera (MediaPipe) work: audio cannot see them, and the
  evaluator does not pretend otherwise.
- **Trumpet — shipped evaluator path (`app/evaluation/trumpet.py`):** a fixed-pitch
  monophonic instrument, so it routes through the shared pitch/rhythm/tempo
  core with its own evaluator version and a C-major arpeggio exercise, rather
  than duplicating the DTW machinery. Embouchure and breath signals are not yet
  observable from audio in this stack and are not claimed.
- **Drums — shipped evaluator path (`app/evaluation/drums.py`):** rhythm and drum identity
  first, with pitch explicitly inapplicable. The score is a sequence of
  unpitched rhythmic events (display-step/display-octave names the drum, like
  guitar tab names the position), `pitch_accuracy` is stored as NULL rather
  than a fake score, and a rock-groove exercise is seeded onto the
  `eighth-note-groove` node. Limb coordination from camera landmarks remains
  follow-on.

Every supported curriculum has deterministic score-backed exercise generation;
not every instrument has dedicated browser audio analysis. Shared contracts cover
session lifecycle, metric provenance, feedback, EXP, SRS, and quests;
instrument-specific evaluators may add metrics but must not silently reinterpret
piano fields.

---

## Carry-forward work from the textbook product

The existing textbook loop remains supported while the instrument slice is built.
These items are valuable but do not block the piano demo:

- **Extraction quality:** the CO 250 reference measurement is 37 nodes, recall
  0.397, precision 0.600, and zero backwards edges. The main issue is granularity;
  title-distinctiveness filtering is still needed before enabling sub-section
  segmentation.
- **Generated API types:** FastAPI already emits OpenAPI, while
  `frontend/lib/types.ts` is maintained by hand. Add code generation when the
  instrument contract settles, and narrow the existing contract test accordingly.
- **Deployment guard:** deployed startup now rejects loopback allowances in
  `cors_origin_regex`; review the exact production allowlist before release.
- **Frontend redesign:** continue the celestial-atlas token, responsive, keyboard,
  and reduced-motion audits; practice is now a first-class course surface, but no
  external accessibility audit has been completed.
- **URL dedupe:** raw-byte dedupe intentionally does not guarantee stable URL
  dedupe for changing HTML.
- **Production credentials:** deployed environments still require real JWT,
  OAuth/email, storage and enabled provider credentials. Render deployment is
  not currently verified; migrations remain an explicit operator step.

---

## Existing capabilities to reuse

The following are working foundations, not rewrite targets:

- PDF/HTML/public-URL ingestion with provenance, SSRF/robots/readability checks,
  content-addressed storage, chunking, and background progress;
- TOC-first prerequisite graph construction, cycle rejection, transitive
  reduction, quote-backed inferred edges, and rebuildable Neo4j/Chroma projections;
- four drill formats, rubric grading, EXP, levels, unlocks, SM-2 scheduling, EMA
  mastery, decay quests, search, citations, and guided paths;
- auth, password recovery, Google OAuth configuration, character, perks, and
  achievements; course sharing, cohort leaderboards, and admin reindex/staleness
  tools;
- fake LLM mode, idempotent drill/grading behavior, cancellation, and per-course
  spend ceilings.

The new work should call these through services and contracts. It should not
create a second progression system, a second graph authority, or a second hidden
scheduler.

---

## Verification checklist

Before calling a phase complete:

```powershell
cd backend;  .\.venv\Scripts\pytest.exe -q;  .\.venv\Scripts\ruff.exe check .
cd frontend; npm run typecheck; npm run lint
```

Also verify:

- no `continue` statements in Python or TypeScript;
- no live LLM, ElevenLabs, camera, n8n, or Render dependency in unit tests;
- every external response has an explicit timeout and failure state;
- every paid/provider operation has an idempotency key or content-addressed cache;
- metrics carry evaluator/version/confidence metadata;
- Postgres is the only authoritative write target;
- the demo still works with `LLM_PROVIDER=fake` and no provider keys.

`CLAUDE.md` remains the source of repository-wide engineering conventions.

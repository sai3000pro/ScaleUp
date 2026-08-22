# API Contract

**Owner:** `backend/app/schemas/` (Pydantic v2)
**Consumer:** `frontend/lib/types.ts` — a literal mirror of this document
**Validation:** `backend/tests/unit/test_api_contract.py` verifies the route
inventory, success status, generated OpenAPI response refs, representative
nested JSON payloads, and the top-level field mirror in `frontend/lib/types.ts`.
The backend integration tests still exercise the live response values; frontend
typecheck and lint catch TypeScript usage errors.

There is no shared codegen between a Python backend and a TypeScript frontend in
stage 1, so this document *is* the type system between them. Change it here
first, then both sides. The executable verifier covers the response seam without
requiring a live datastore stack; it intentionally does not replace integration
tests for ownership, persistence, or derived-store behavior.

Base URL: `http://localhost:8000`. All paths are prefixed `/api`.
All requests except `/api/auth/*` require `Authorization: Bearer <access_token>`.

---

## Conventions

- All ids are UUID strings.
- All timestamps are ISO-8601 with a `Z` suffix (UTC).
- Errors use `{"detail": "<message>"}` with a conventional status code.
- `POST` endpoints that create billable work accept an `Idempotency-Key` header.

---

## Auth

### `POST /api/auth/register`
```jsonc
// request
{ "email": "dev@local", "password": "hunter22", "display_name": "Dev" }
// 201
{ "access_token": "eyJ…", "token_type": "bearer", "user": User }
```
`409` if the email is taken.

### `POST /api/auth/login`
```jsonc
{ "email": "dev@local", "password": "hunter22" }   // → 200 same shape as register
```
`401` on bad credentials. Successful register/login responses also set an
HttpOnly, path-scoped refresh cookie; the cookie is never included in the JSON
contract.

### `POST /api/auth/refresh` → `TokenResponse`

Rotates the HttpOnly refresh cookie and returns a new access token. Refresh
sessions are stored only as hashes, are single-use, and expire after
`REFRESH_TOKEN_TTL_DAYS`. Reuse of an already-rotated token revokes the active
session family and requires a fresh login.

### `POST /api/auth/logout` → `204`

Revokes the presented refresh session and clears the HttpOnly cookie. The
endpoint is safe to call when the cookie is already absent.

### `POST /api/auth/password-reset/request` → `202 PasswordResetRequested`
```jsonc
{ "email": "learner@example.com" }
// 202 for both known and unknown addresses
{ "message": "If that email is registered, a reset link is on its way." }
```
The response is deliberately identical for known and unknown addresses. A
known account receives a single-use link by the configured email provider; reset
tokens are stored only as SHA-256 hashes, expire after the configured TTL, and
are invalidated when consumed or when a newer reset is requested.

### `POST /api/auth/password-reset/consume` → `TokenResponse`
```jsonc
{ "token": "one-time-token-from-email", "password": "new-long-password" }
```
`400` for an invalid, expired, or already-used token. Success signs the learner
in immediately with a fresh bearer token.

### `GET /api/auth/google/start` → `307 redirect`

Starts Google OpenID Connect authorization. The backend stores a short-lived
hashed state value and redirects to Google; client secrets never reach the
browser.

### `GET /api/auth/google/callback` → `303 redirect`

Google returns here after consent. The backend validates and consumes state,
retrieves a verified Google profile, links or creates the local account, and
redirects to the frontend callback route with a short-lived one-time exchange
code. OAuth failures redirect to `/login?error=google_sign_in_failed`.

### `POST /api/auth/google/exchange` → `TokenResponse`
```jsonc
{ "code": "one-time-exchange-code-from-callback" }
```
The frontend redeems the code over HTTPS; the code is hashed at rest, expires
quickly, and cannot be reused. The returned access token is stored by the existing auth store and the response
sets the same rotating refresh cookie, so Google sign-in uses the same protected
API and RPG progression path as password sign-in.

### `GET /api/auth/me` → `User`

```ts
type User = {
  id: string;
  email: string;
  display_name: string;
  total_exp: number;
  level: number;            // derived from total_exp, see srs_and_exp.md
  exp_into_level: number;
  exp_for_next_level: number;
  streak_days: number;
  created_at: string;
};
```

---

## Character progression

### `GET /api/character` → `CharacterSheet`

Returns the authenticated learner's account progression, derived learning stats,
achievements, and perk catalog. `profile` is `null` until the learner completes
character creation; the account's EXP remains authoritative in `User` and is
never duplicated in the profile row.

### `POST /api/character` → `201 CharacterSheet`

```json
{
  "character_name": "Ada",
  "avatar_key": "owl",
  "archetype": "scholar",
  "skin_tone": "sand",
  "hair_style": "sweep",
  "hair_color": "chestnut",
  "outfit_color": "azure",
  "accessory": "none"
}
```

The archetype is identity and presentation only. It does not make any course or
subject easier or harder.

### `PATCH /api/character` → `CharacterSheet`

Updates any selected identity or appearance fields. Appearance choices are persisted in the profile and rendered by the client-side SVG sprite. The accepted customization vocabulary is:

```ts
type CharacterAppearance = {
  skin_tone: "moon" | "sand" | "honey" | "copper" | "ebony";
  hair_style: "sweep" | "curls" | "bob" | "mohawk" | "crown";
  hair_color: "ink" | "chestnut" | "silver" | "violet" | "rose";
  outfit_color: "azure" | "violet" | "coral" | "mint" | "gold";
  accessory: "none" | "glasses" | "headband" | "crown" | "earring";
};
```

`POST /api/character/perks/{perk_id}` unlocks one catalog perk when the learner has an unspent account-level perk point.
Perks are deliberately meta-progression; knowledge skills remain the grounded
course graph nodes.

```ts
type CharacterSheet = {
  profile: {
    user_id: string;
    character_name: string;
    avatar_key: string;
    archetype: string;
    skin_tone: string;
    hair_style: string;
    hair_color: string;
    outfit_color: string;
    accessory: string;
    unlocked_perks: string[];
    created_at: string;
  } | null;
  level: number;
  total_exp: number;
  exp_into_level: number;
  exp_for_next_level: number;
  streak_days: number;
  stats: { focus: number; memory: number; resilience: number; curiosity: number };
  perks: { id: string; title: string; description: string; cost: number; unlocked: boolean }[];
  achievements: { id: string; title: string; description: string; progress: number; target: number; unlocked: boolean }[];
  available_perk_points: number;
};
```

Stats and achievements are deterministic projections of existing attempts,
node-progress, courses, and streak facts. This keeps the RPG layer auditable and
prevents a second source of truth for mastery. Account level-ups are returned
explicitly by `GradeResult.account_level_up`; a skill-node level-up is a separate
field because the two curves serve different purposes.

---

## Courses

### `POST /api/courses` → `201 Course`
```jsonc
{ "title": "Piano", "description": "Alfred's Basic Adult Piano Course, book 1." }
```

### `GET /api/courses` → `{ "courses": Course[] }`

### `GET /api/courses/{course_id}` → `Course & { documents: DocumentSummary[], curriculum_provenance: string | null }`

`curriculum_provenance` is how the published curriculum was built, and is `null`
until one is published:

| Value | Meaning |
|---|---|
| `catalogue-assembly-v1` | Assembled from a curriculum this project ships |
| `catalogue-plan-v1` | Proposed by a model against the shared catalogue, validated |
| `curriculum-compiler-v1` | Compiled from source documents with quote-backed evidence |

### `POST /api/courses/from-goal` → `201 Course`
```jsonc
{ "goal": "I want to learn how to play guitar" }
```

Builds a published, playable skill tree from the learner's own sentence, in one
request — no document, no ingest, no background job. The instrument is read out
of the goal text; the tree is assembled from the shared skill catalogue, and for
an instrument the project does not ship a curriculum for, a model proposes the
specialisation against that catalogue and the proposal is validated before
anything is stored.

`422` when the goal names no instrument. The `detail` is written for the learner
and can be shown verbatim.

The courses dashboard offers three entry points: create an empty skill tree,
build one from a stated goal (above), or start a source-backed campaign whose
approved sources enter the ingestion pipeline and become evidence for extracted
skills and prerequisite links.

```ts
type Course = {
  id: string;
  title: string;
  description: string | null;
  status: "draft" | "ingesting" | "ready" | "failed";
  // Where the course came from. "learner" for one they created, "prebuilt" for
  // one the project offers ready-made, "internal" for one seeded only so the
  // system is developable offline. A bare string like `status`: clients treat an
  // unrecognised shelf as the learner's own rather than hiding the course.
  shelf: "learner" | "prebuilt" | "internal" | (string & {});
  graph_version: number;
  node_count: number;
  edge_count: number;
  mastered_count: number;
  created_at: string;
};

type DocumentSummary = {
  id: string;
  filename: string;
  source_type: "pdf" | "html";
  source_uri: string | null;   // original public URL; null for local uploads
  page_count: number | null;
  chunk_count: number;
  created_at: string;
};
```

### `POST /api/courses/{course_id}/share` → `201 ShareCreated`

Create (or rotate) the course's share link. Only courses in status `ready`
qualify; anything else is `409`. One share per course: creating again deletes
the old token's hash, so the previous link stops resolving immediately.

The raw token appears in the response exactly once -- the backend stores only
its SHA-256 -- so the frontend copies `url` now or the owner regenerates later.

```ts
type ShareCreated = {
  course_id: string;
  url: string;          // {FRONTEND_URL}/share/{token}
  created_at: string;
};
```

### `GET /api/courses/{course_id}/share` → `ShareStatus`

Whether the course currently has a share. The link itself is deliberately not
returned -- only its hash is stored, so a GET cannot re-show it.

```ts
type ShareStatus = {
  course_id: string;
  shared: boolean;
  created_at: string | null;  // when the share was created; null when not shared
};
```

### `DELETE /api/courses/{course_id}/share` → `204`

Revoke the share. The old link stops resolving (404 on every endpoint).

### `GET /api/shares/{token}` → `SharePreview` — PUBLIC

The public face of a share link. No auth: the token IS the credential, and the
visitor may not have an account yet. Deliberately small -- documents, chunks,
the graph, and questions stay owner-scoped; the visitor decides to copy from
the tree's shape.

```ts
type SharePreview = {
  course_id: string;
  title: string;
  description: string | null;
  status: string;
  node_count: number;
  edge_count: number;
  shared_by: string;    // sharer's display name
  created_at: string;
};
```

### `POST /api/shares/{token}/copy` → `201 Course` (200 when already copied)

Deep-copy the shared course into the caller's account: documents, parsed
pages, chunks, the skill graph, and the question bank. Copying is idempotent
per (owner, source course) -- a second copy returns the existing copy with
`200` and the same `Course.id`. Learner progress, attempts, ingest jobs, the
LLM cost ledger, and curriculum proposals never travel.

Copied chunks keep their documents' content-addressed storage paths but drop
`vector_id`: Chroma collections are course-scoped, so semantic search falls
back to the lexical path until the new owner runs the owner-scoped reindex.

### `GET /api/courses/{course_id}/leaderboard` → `CourseLeaderboard`

The cohort scoreboard. A cohort is the original course plus every copy made
from its share link, so this is the social face of sharing: every learner on
the same tree can see how their EXP ranks against the rest. Owner-scoped like
every course endpoint (someone else's course is a 404), and reveals only
`display_name` and progress aggregates -- never emails.

```ts
type LeaderboardEntry = {
  display_name: string;
  level: number;
  total_exp: number;
  streak_days: number;
  mastered_count: number;   // within this course
  started_count: number;    // within this course
  me: boolean;
};

type CourseLeaderboard = {
  course_id: string;
  cohort_size: number;
  entries: LeaderboardEntry[];  // sorted by total_exp desc, then level desc
  my_rank: number;              // 1-based; the caller owns the course, so always present
};
```

### `GET /api/courses/{course_id}/campaign/briefing` → `CampaignBriefing`

Returns the owner-scoped RPG briefing projection. It combines the latest
campaign objective with the actual generated skill-tree shape and a lexical
outcome-coverage signal over skill titles and summaries. A missing proposal is
represented by an empty objective rather than an error, so textbook-first
courses can use the same briefing.

```ts
type CampaignBriefing = {
  course_id: string;
  goal: string | null;
  target_outcome: string;
  proposal_version: number | null;
  tree_shape: {
    playable_skills: number;
    branches: number;
    prerequisite_links: number;
    depth: number;
    depth_counts: Record<string, number>;
    starting_skills: { id: string; title: string }[];
  };
  outcome_coverage: {
    outcome: string;
    terms: string[];
    matched_terms: string[];
    missing_terms: string[];
    coverage: number;
    signal: string;
  };
};
```

### `POST /api/courses/{course_id}/campaign/evaluate` → `CampaignOutcomeEvaluation`

Runs an on-demand review of the persisted victory condition against the generated
skill summaries. It is not called on every page load and does not create nodes or
change progression. With a real LLM provider, `mode` is `semantic`; the default
fake provider reports `deterministic`, and provider failures degrade to
`lexical_fallback`.

```ts
type CampaignOutcomeEvaluation = {
  course_id: string;
  outcome: string;
  provider: string;
  mode: string;                         // semantic | deterministic | lexical_fallback | unavailable
  evaluated_skill_count: number;
  readiness: number;                    // advisory 0..1 signal
  matched_skills: { id: string; title: string }[];
  missing_capabilities: string[];
  side_quests: {
    capability: string;
    title: string;
    reason: string;
    source_query: string;
    action: string;
  }[];                                  // source-addition tasks, never drillable skills
  rationale: string;
};
```

### `POST /api/courses/{course_id}/curriculum/proposals` → `201 CurriculumProposal`

Creates a bounded web-source proposal for a learning goal. Search returns only
metadata and short highlights; it does not fetch or ingest the proposed pages.

```ts
{
  goal: string;
  target_outcome?: string;                                   // max 300 chars; the campaign's victory condition
  prior_knowledge?: string;                                  // max 300 chars; learner's starting point
  application_context?: string;                              // max 300 chars; intended use/project
  learner_level?: "beginner" | "intermediate" | "advanced"; // default beginner
  weekly_minutes?: number;                                    // 15..600, default 120
  format_preference?: "mixed" | "textbook" | "course" | "papers";
  max_sources?: number;                                       // 1..12
}
```
The default development provider is `fake`. Set `RESEARCH_PROVIDER=exa` and
`EXA_API_KEY` to use the optional Exa adapter. Each proposal uses at most four
bounded discovery angles—general, fundamentals, practical application, and
reference—and deduplicates URLs before ranking. The learner context is included
in the search query and source ranking, but ranking remains deterministic and
explainable. `discovery_angle` preserves which angle surfaced each URL.

Policy metadata is conservative: the planner does not fetch `robots.txt` or
license pages before approval. It gives the learner the exact robots URL and
requires an explicit acknowledgement that policy status is unverified.

```ts
type CurriculumProposal = {

  id: string;
  course_id: string;
  goal: string;
  target_outcome: string;
  prior_knowledge: string;
  application_context: string;
  proposal_version: number;
  supersedes_id: string | null;
  learner_level: "beginner" | "intermediate" | "advanced";
  weekly_minutes: number;
  format_preference: "mixed" | "textbook" | "course" | "papers";
  provider: string;
  status: string;              // draft | approved | ingesting | completed
  created_at: string;
  sources: CurriculumSource[];
};
```

### `GET /api/courses/{course_id}/curriculum/proposals/latest` → `CurriculumProposal`

Returns the owner's most recent proposal so a campaign can restore its victory
condition and approved source state after navigation. Returns `404` when the
course has no proposal yet.

### `GET /api/courses/{course_id}/curriculum/proposals/{proposal_id}` → `CurriculumProposal`

Returns one owner-scoped proposal by id.

```ts
type CurriculumSource = {
  id: string;
  rank: number;
  title: string;
  url: string;
  domain: string;
  snippet: string;
  discovery_angle: string;  // general | fundamentals | practical | reference
  published_at: string | null;
  quality_score: number;       // 0..1, deterministic fit score
  quality_reasons: string[];   // shown so the learner can override the ranking
  policy_status: string;       // review_required until the learner reviews it
  robots_url: string;          // exact robots URL to inspect
  robots_status: string;       // not_checked in this bounded planner
  license_status: string;      // not_identified unless a provider supplies it
  policy_reasons: string[];
  policy_checked_at: string | null;
  policy_acknowledged: boolean;
  selected: boolean;
  status: string;              // proposed | approved | ingesting | failed
  ingest_job_id: string | null;
  ingest_error: string | null;
};
```

### `POST /api/courses/{course_id}/curriculum/proposals/{proposal_id}/sources/{source_id}/policy-check` → `CurriculumProposal`

Explicitly checks the selected source's bounded `robots.txt` rules and its own
page for an explicit license declaration. This endpoint performs network work
only because the learner requested it. Results are recorded with a check time;
fetch failures remain `unavailable`, an identified license remains review-only,
and a robots disallowance makes the source ineligible for approval.

### `POST /api/courses/{course_id}/curriculum/proposals/{proposal_id}/approve` → `CurriculumProposal`

```ts
{ source_ids: string[]; acknowledge_policy?: boolean } // 1–12 ids; required for unverified sources
```

Approval replaces the prior selection. A source is not handed to ingestion until
this endpoint succeeds. Since search metadata cannot establish a license or
current robots rules, selected unverified sources require `acknowledge_policy: true`.
Repeated proposals are numbered and retain a `supersedes_id` link to the prior
proposal for auditability.

### `POST /api/courses/{course_id}/curriculum/proposals/{proposal_id}/ingest` → `202 CurriculumIngestAccepted`

Hands only the approved URLs to the existing URL ingestion pipeline. Each source
is bounded independently by the URL fetch protections; partial fetch failures are
returned per source rather than silently dropping the rest.

```ts
type CurriculumIngestAccepted = {
  proposal_id: string;
  course_id: string;
  accepted: { source_id: string; job_id: string | null; status: string; error: string | null }[];
};
```

### `POST /api/courses/{course_id}/curriculum/versions` → `201 CurriculumVersion`

Creates a draft curriculum from already-ingested source chunks. Concepts and
candidate edges are stored separately from the learner graph. Every edge may
carry one or more exact quotes; the backend verifies each quote against the
referenced chunk and records the chunk hash and compiler version.

```ts
type CurriculumVersion = {
  id: string;
  course_id: string;
  instrument: string;
  slug: string;
  title: string;
  version: number;
  status: string;              // draft | review | published | retired
  compiler_version: string;
  node_count: number;
  candidate_count: number;
  rejected_count: number;
  created_at: string;
  published_at: string | null;
};
```

The request contains `instrument`, `slug`, `title`, a closed list of `concepts`,
and `edges`. Each concept can name its source chunk IDs. An edge's `evidence`
contains `{ chunk_id, quote, extractor_version, prompt_sha256?, source_sha256? }`.
Unknown concepts, cross-course chunks, invented quotes, and hash mismatches are
rejected before the draft is committed.

### `GET /api/courses/{course_id}/curriculum/versions/{version_id}/candidates` → `CurriculumCandidate[]`

Lists every candidate in stable review order, including cycle rejections produced
by the compiler. The frontend uses each returned ID to submit an explicit review.

### `POST /api/courses/{course_id}/curriculum/versions/{version_id}/candidates/{candidate_id}/review` → `CurriculumCandidate`

```ts
{ decision: "accepted" | "rejected" | "ambiguous"; reason?: string }
```

A candidate is inert while `draft` or `ambiguous`. Accepting requires at least
one verified evidence quote. Reviews are append-only and identify the reviewer.

```ts
type CurriculumCandidate = {
  id: string;
  version_id: string;
  prereq: string;
  target: string;
  confidence: number;
  support: number;
  status: string;
  rationale: string | null;
  rejection_reason: string | null;
  cycle_path: string[];
  evidence_count: number;
};
```

### `POST /api/courses/{course_id}/curriculum/versions/{version_id}/publish` → `CurriculumPublishResult`

Publication is refused while any candidate is unreviewed or ambiguous, or when
an accepted candidate has no evidence. It revalidates the accepted edge set,
then projects the immutable version through the existing DAG persistence path.
Only at this point do `skill_nodes`, unlocks, EXP, SRS, and quests see the new
curriculum. Re-publishing an already published version is idempotent; published
versions cannot be edited.

```ts
type CurriculumPublishResult = {
  version_id: string;
  course_id: string;
  graph_version: number;
  node_count: number;
  edge_count: number;
};
```

### `GET /api/courses/{course_id}/practice/exercises` → `Exercise[]`

Returns active score-backed exercises owned by the course. The piano and guitar
reference scores expose short monophonic MusicXML exercises (piano stepwise notes and a
guitar low-E fretting drill with string/fret tab, a violin open-string scale
with intonation tracking, a trumpet C-major arpeggio, and a rhythm-only drums
rock groove). The browser can use this same response for a real microphone
path or the deterministic reference-note path. Every instrument with a score
asset has a working evaluator; guitar open-chord/strumming scoring remains
follow-on work.

```ts
type Exercise = {
  id: string;
  course_id: string;
  node_id: string;
  slug: string;
  title: string;
  instructions: string;
  score_title: string;
  score_format: string;
  tempo_bpm: number;
  duration_beats: number;
  evaluator_version: string;
  difficulty: number;
};
```

### `POST /api/practice/sessions` → `201 PracticeSession`

```ts
{ exercise_id: string }
```

Creates an authenticated, course-owned practice session. The session is the
stable boundary between selecting an exercise and submitting a performance.

### `POST /api/practice/sessions/{session_id}/attempts` → `201 PerformanceAttempt`

Header: `Idempotency-Key: <unique key>` (required, trimmed to at most 128 characters).

The MVP submission carries canonical note observations so the backend contract
is stable before browser DSP is added. This is a deterministic reference path, not
an assertion that microphone recordings are already analyzed:

```ts
type PerformedNote = {
  pitch_midi: number | null; // null only for drums, where `drum` carries identity
  onset_seconds: number;
  duration_seconds: number;
  confidence: number;
  string?: number | null; // guitar fretboard position; null for piano
  fret?: number | null;
  cents_deviation?: number | null; // violin intonation offset; positive = sharp
  drum?: string | null; // kick | snare | hihat | … for rhythm-only instruments
};
```

The body may also name a preserved take as the attempt's evidence:
`recording_id` (optional) must belong to the caller and to the same course as
the practice session, or the submission is rejected with a 400. When accepted,
the attempt stores the link, so the take can be replayed from the attempt's
history. Preserving the take is best-effort on the client: upload failure is
surfaced but never sinks the submission, because the notes are the score.

The backend routes observations to the instrument's evaluator by the score
asset's declared instrument:

- **piano / trumpet** — shared monophonic pitch/rhythm/tempo core;
- **guitar** — single notes get the shared core plus string/fret position
  technique; open-chord exercises (`guitar-chords-v1`) group written notes by
  shared onset and observed notes by strum spread into chord events, scoring
  pitch-set coverage, rhythm, and fret position with the same metric contract;
- **violin** — the core plus intonation from per-note cents deviation;
- **drums** — rhythm and drum identity only; pitch is inapplicable, never a
  fake score.

It normalizes MusicXML, runs the versioned DTW evaluator, persists raw
observations and the complete metric bundle, updates the existing SRS/EXP rows
when alignment confidence is sufficient, and marks silence/low-confidence
submissions as `needs_review` without awarding EXP. Repeating the idempotency key returns
the original persisted result and never awards EXP twice.

Every attempt also returns persona-voiced examiner feedback. A deterministic
floor is always derived from the metric bundle, then the `performance_feedback`
LLM role may upgrade the wording (never the numbers); both are persisted with
the attempt at submission time, so idempotent re-reads never regenerate a paid
call. Provider failures fall back to the deterministic floor.

```ts
type ExaminerFeedback = {
  persona: string;
  tone: string; // celebratory | encouraging | coaching | supportive
  summary: string;
  strengths: string[];
  corrections: string[];
  next_step: string;
};

type PerformanceAttempt = {
  id: string;
  session_id: string;
  exercise_id: string;
  status: string; // completed | needs_review | failed
  overall_score: number;
  alignment_confidence: number;
  exp_awarded: number;
  feedback_provider: string; // deterministic | fake | anthropic | openai
  created_at: string;
  metrics: {
    evaluator_version: string;
    expected_note_count: number;
    observed_note_count: number;
    matched_note_count: number;
    missed_note_count: number;
    extra_note_count: number;
    pitch_accuracy: number | null; // null for drums: rhythm-only
    rhythm_accuracy: number;
    technique_accuracy: number | null; // fretboard position; null for piano
    position_error_count: number;
    intonation_accuracy: number | null; // violin; null for other instruments
    intonation_deviation_cents: number | null; // mean |cents|; null when not measured
    tempo_bpm: number | null;
    tempo_deviation_percent: number | null;
    alignment_confidence: number;
    overall_score: number;
    low_confidence: boolean;
  };
  feedback: ExaminerFeedback;
};
```

### `GET /api/practice/attempts/{attempt_id}` → `PerformanceAttempt`

Returns an owner-scoped persisted result for refresh/retry-safe result screens.

### `POST /api/practice/attempts/{attempt_id}/speech` → `VoiceArtifact`

Speaks the attempt's examiner feedback through the configured voice provider
(`fake` by default, or `elevenlabs` with a key). Artifacts are cached in
Postgres by content hash, so the same text with the same voice is synthesized
at most once and repeat requests are served without a second paid call; a
concurrent duplicate insert is recovered by re-reading the winner. The response
always carries `spoken_text` and only carries `audio_base64` when a provider is
configured, so the frontend can fall back to browser TTS. A provider failure
degrades delivery, never the score or EXP award:

```ts
type VoiceArtifact = {
  attempt_id: string;
  provider: string; // fake | elevenlabs | unavailable
  voice_key: string;
  format: string; // wav | mp3 | text
  audio_base64: string | null;
  spoken_text: string;
  cache_key: string; // content-addressed over (voice_key, spoken_text)
  cached: boolean; // served from the artifact store
};
```

### `POST /api/courses/{course_id}/practice/exercises` → `201 Exercise` (200 when it already exists)

Generate a score-backed exercise for one skill node. Everything except
`node_id` is optional -- the point is that a node gets something playable
automatically, derived from its own title and difficulty.

```ts
{
  node_id: string;
  instrument?: string;      // defaults to the course's published curriculum
  pattern?: string;         // scale_ascending | arpeggio | chord_progression | ...
  tonic?: string; mode?: string;
  tempo_bpm?: number; bars?: number;
  beats_per_measure?: number; beat_type?: number;
  title?: string;
  use_llm?: boolean;        // false keeps the deterministic floor, calls nothing
}
```

A deterministic generator always produces a valid score first; the
`score_compose` role may then compose something more musical, returning a NOTE
LIST rather than XML. The rendered result must be accepted by the same parser
the evaluator uses before it is stored, and any failure -- schema, range, bar
sum, budget, refusal, outage -- keeps the procedural score. Generating an
exercise therefore cannot fail for a reason the learner has to care about.

Idempotent: a node that already has an exercise of that pattern returns the
existing one with `200`. Regenerating is deliberately not offered, because
attempt history is grouped by exercise and swapping the score under a stable id
would compare a learner against a different piece of music.

Every node of every published instrument curriculum gets one automatically at
publication time, using the procedural generator only -- publication is the one
path that must stay deterministic and offline.

---

## Live coaching (`WS /api/practice/coach`, protocol `coach.v1`)

A WebSocket that follows a take as it happens: cheap always-on cues at ~10 Hz,
and at most a few spoken corrections, delivered at phrase boundaries.

**The socket never produces a score.** At `take.finalize` the server calls the
same `submit_attempt` the clip path uses, with `Idempotency-Key:
coach:{take_id}`. Grading, EXP, and SRS have exactly one implementation, and the
`take.result` frame carries the unmodified `PerformanceAttempt` contract.

**Auth.** Browsers cannot set an `Authorization` header on a WebSocket
handshake, and a token in the query string ends up in every access log on the
way. So the access token arrives in the first frame instead, validated by the
same code as every other route.

Every frame carries `{ v: 1, type, seq }`.

**Client → server**

| type | payload |
|---|---|
| `hello` | `token`, `protocol_version` |
| `take.start` | `take_id` (client-generated), `practice_session_id` |
| `notes` | `take_clock_seconds`, `notes: PerformedNote[]` (≤32, batched ~10 Hz) |
| `frame` | `take_clock_seconds`, `rms_db`, `silence_seconds` |
| `technique` | reduced posture metrics — never landmarks, never video |
| `barge_in` | the learner started playing again |
| `heartbeat` | keeps the take claim alive |
| `take.finalize` | the client's complete `notes`, optional `recording_id`, `posture`, `analyzer` |
| `take.abandon` | give up on the take |

**Server → client**

| type | payload |
|---|---|
| `session.ready` | `protocol_version`, `resumed`, `exercise`, `audio_format` |
| `cue` | cursor, matched/missed/extra, timing bias, `progress_ratio`, `suppressed_by`. No model, no spend. |
| `coach.begin` / `coach.delta` / `coach.audio` / `coach.end` | one streamed utterance |
| `coach.cancel` | `reason: barge_in \| timeout \| take_finalized \| budget` |
| `take.result` | `attempt: PerformanceAttempt` |
| `error`, `pong` | |

Close codes: `4401` unauthenticated, `4403` not the owner, `4409` the take is
already open elsewhere, `4426` protocol mismatch, `4429` rate limited.

**When the coach speaks.** Only after ~0.6s of silence (a phrase end), at most
four times a take, never twice about the same thing inside 25s, and never past
the course budget. Losing your place is the one cue allowed to interrupt, once.
"Nothing to say" is a normal outcome and appears as `suppressed_by` on the cue
frame.

**With no keys.** The deterministic sentence for each cue is streamed word by
word by the fake provider and spoken by the browser's own voice, so the whole
loop -- incremental render, barge-in, ledger row -- runs with no API key and no
network. `spoken_text` is always present; audio is best-effort.

**If the socket drops.** The client holds every note and resubmits over
`POST /api/practice/sessions/{id}/attempts` with the same
`Idempotency-Key: coach:{take_id}`, so a lost connection cannot produce a second
attempt or a second EXP award.

---

## Preserved takes

Raw practice audio is evidence: the browser segments a take into canonical
notes, but the take itself is preserved so a replay can hear what was scored.
Endpoints are owner-scoped; a take from another user is indistinguishable from
one that does not exist (404).

### `POST /api/recordings` → `201 Recording`

```ts
{
  course_id: string;
  format: string; // webm | wav | mp3 | ogg | m4a
  duration_seconds: number | null;
  content_base64: string; // the raw bytes, base64-encoded
}
```

Content-addressed per user: re-uploading identical bytes returns the original
row with `deduplicated: true` and never stores a second copy. Invalid base64,
empty content, and content over the 20 MB cap are rejected before touching the
database (400/400/413). The browser captures `audio/webm` via MediaRecorder,
which is the one container guaranteed to exist wherever the API is used.

```ts
type Recording = {
  id: string;
  course_id: string;
  attempt_id: string | null; // set once the attempt that cited it is submitted
  format: string;
  byte_size: number;
  content_sha256: string;
  duration_seconds: number | null;
  created_at: string;
  deduplicated: boolean;
};
```

### `GET /api/recordings/{recording_id}` → `Recording`

Metadata only, so replay clients can list takes without hauling bytes.

### `GET /api/recordings/{recording_id}/content` → bytes (`audio/webm`)

The raw take, streamed for the `<audio>` element. Content and metadata are
separate endpoints so replay never forces bytes through a JSON payload.

### `DELETE /api/recordings/{recording_id}` → `204`

Owner-only delete; a deleted take 404s thereafter. Deleting a take does not
change the attempt it was linked to — the notes and metrics are the persisted
score.

### `GET /api/courses/{course_id}/progress` → `ProgressAnalytics`

Returns the learner's historical progress for this course. The trend is
replayed from graded attempts, while current skill counts come from the current
review facts. It is owner-scoped and returns `404` for another user's course.

```ts
type ProgressAnalytics = {
  course_id: string;
  total_skills: number;
  started_skills: number;
  mastered_skills: number;
  total_attempts: number;
  average_score: number | null;
  exp_earned: number;
  review_days: number;
  tracked_days: number;
  consistency: number;             // review_days / tracked_days, 0..1
  mastery_trend: {
    date: string;                   // one point per day with a graded attempt
    attempts: number;
    average_score: number;          // 0..1
    mastery: number;                // replayed EMA across course skills, 0..1
    exp_earned: number;
  }[];
  source_coverage: {
    document_id: string;
    filename: string;
    skills_total: number;
    skills_started: number;
    attempts: number;
  }[];
};
```

---

## Ingestion

### `POST /api/courses/{course_id}/documents` → `202`

`multipart/form-data` with a `file` field. **PDF and HTML.**

```ts
type IngestAccepted = {
  document: DocumentSummary;
  job_id: string;
  deduplicated: boolean;   // true => an existing document/job was reused;
                           // false => a new ingest job was created
};
```

Dedupe key is `(course_id, sha256(bytes))`. Re-uploading the same file is a no-op
that returns the current job for the existing document, never a second concurrent
ingest. A failed job can instead be retried with `POST /api/jobs/{job_id}/retry`.

`DocumentSummary.source_type` is `"pdf" | "html"`, decided by sniffing the bytes.
The filename and the `Content-Type` are not consulted, so renaming a `.pdf` to
`.html` changes nothing. Anything that is neither is `415`.

### `POST /api/courses/{course_id}/documents/url` → `202`

```ts
type DocumentUrlIn = { url: string };   // http/https only, ≤ 2048 chars
```

Returns the same `IngestAccepted`. **This endpoint blocks while it fetches** --
`content_sha256` is `NOT NULL` and the `(course_id, content_sha256)` unique
constraint is the outer layer of idempotency, so the bytes must exist before the
document row can. Bounded by `URL_FETCH_TIMEOUT_SECONDS` (default 15s).

`400` with a human-readable reason for every refusal: a non-http(s) scheme,
credentials in the URL, a port other than 80/443, a host resolving to a private
or reserved address, more than `URL_FETCH_MAX_REDIRECTS` hops, a body over
`URL_FETCH_MAX_BYTES`, or an upstream error status. `415` if the fetched bytes
are neither PDF nor HTML.

**Dedupe is on the fetched bytes, never the URL** — `?utm_source=` and a trailing
slash are the same page and normalising a URL well enough to say so is a losing
game. `Document.source_uri` carries the URL as provenance, not identity. The
honest consequence: HTML is rarely byte-stable, so re-submitting the same URL
usually creates a *second* document rather than deduplicating.

### `GET /api/jobs/{job_id}` → `IngestJob`

```ts
type IngestJob = {
  id: string;
  document_id: string | null;       // null for a reindex job -- it spans the course
  course_id: string;
  state: "queued" | "parsing" | "chunking" | "embedding"
       | "extracting" | "reducing" | "finalizing"
       | "succeeded" | "failed" | "cancelled";
  units_done: number;
  units_total: number;
  percent: number;                  // 0..100, already rounded
  stage_detail: {
    pages?: number;
    chunks?: number;
    concepts_raw?: number;          // before merge
    concepts_merged?: number;       // after merge
    edges_accepted?: number;
    edges_rejected?: number;
    failed_windows?: number;        // partial failures the pipeline absorbed
    // reindex jobs only
    scope?: "all" | "graph" | "vectors";
    embedded?: number | null;       // vectors written to Chroma
    neo4j_edges?: number | null;    // edges written to the projection
    stale?: boolean;                // post-condition read back after projecting
  };
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
};
```

The frontend polls this at 1.5s, backing off to 5s after 60s (and briefly
backs off further after transient polling failures), and stops on
`succeeded | failed | cancelled`. A failed document job can be retried through
`POST /api/jobs/{job_id}/retry` without reselecting the source. Polling was chosen
over SSE deliberately: it is stateless, survives a page refresh, needs no sticky routing, and costs ~1.5s of
latency on a job measured in minutes. The DTO above is the payload either way, so
switching later touches one hook.

The same shape serves both job kinds. A reindex reuses the `embedding` and
`finalizing` states rather than inventing new literals, so the polling UI and its
human labels need no change.

### `POST /api/jobs/{job_id}/retry` → `202 IngestAccepted`

Retries a failed document ingest using the exact source bytes already stored by
the server. This does not re-upload a local file or re-fetch a URL, so the retry
uses the same `Document` and content hash. It is available only for failed
`ingest` jobs; reindex jobs should be requested through the admin endpoint.

Returns the normal `IngestAccepted` shape with a new `job_id`. A concurrent retry
of the same failed job is deduplicated and returns the winning retry job.

### `POST /api/jobs/{job_id}/cancel` → `IngestJob`

Asks a job to stop. `409` if it has already reached `succeeded | failed |
cancelled`; `404` for a job in a course you do not own.

**Cooperative, not pre-emptive.** The endpoint flips the job row and the worker
notices at its next stage boundary, because Celery's `revoke()` does not reach a
task that is already executing. Concretely: a **queued** job never starts, and a
**running** one finishes the stage it is in and then stops. Cancelling four
minutes into a forty-minute extraction does not abort the extraction — it stops
the pipeline before the next stage. The response is the job as of the flip, so
its `state` reads `cancelled` immediately even though a worker may still be
finishing the current stage.

---

## Graph

### `GET /api/courses/{course_id}/graph` → `GraphSnapshot`

```ts
type GraphSnapshot = {
  course_id: string;
  graph_version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: { total: number; locked: number; available: number;
           learning: number; decaying: number; mastered: number };
};

type GraphNode = {
  id: string;
  slug: string;
  title: string;
  summary: string;
  difficulty: 1 | 2 | 3 | 4 | 5;
  depth: number;               // topological layer; drives the dagre rank
  assessable: boolean;         // false => structural node, never drilled or quested
  section: string | null;      // outline heading this skill came from; PROVENANCE, not structure
  progress: {
    state: "locked" | "available" | "learning" | "decaying" | "mastered";
    exp: number;
    level: number;
    mastery: number;           // 0..1, EMA of graded scores — does NOT decay
    proficiency: number;       // 0..1, mastery after time decay — this is the ring
    due_at: string | null;
    overdue_days: number;      // 0 when not overdue
  };
  blocked_by: { id: string; title: string }[];   // unmet prerequisites, for locked nodes
  sources: SourceEvidence[];                      // exact passages that support this skill
};

type SourceEvidence = {
  chunk_id: string;
  document_id: string;
  section_path: string | null;
  page_start: number;
  excerpt: string;                                 // bounded excerpt from the stored chunk
};

type GraphEdge = {
  id: string;
  source: string;   // the PREREQUISITE node id  ── matches React Flow's
  target: string;   // the DEPENDENT node id     ── source/target naming exactly
  confidence: number;
  support: number;                                  // independent supporting passes
  rationale: string | null;
  sources: SourceEvidence[];                        // target passages grounding the relation
};
```

**Edge direction convention, stated once and obeyed everywhere:** `source` is the
prerequisite, `target` depends on it. Read `source → target` as "learn source
before target".

`edges` contains the **transitively reduced** set — if `A→B` and `B→C` both
exist, `A→C` is omitted even though it is stored. Rendering the full set makes a
real textbook graph an unreadable hairball; roughly 40% of extracted edges are
transitively implied. Node and rendered-edge provenance is read from Postgres,
not reconstructed from Chroma: each response includes up to four exact stored
chunks with document, section, page, and excerpt fields. Edge evidence points to
the target skill's passages, which are the text the prerequisite inference read.

**`stats` is a census of `progress.state`, and counts structural nodes.** That is
correct and deliberate: a node with `assessable: false` still has a real state,
because `gating_masteries` walks *through* containers, so a container has to be
able to reach `available` or the whole subtree behind it would be permanently
locked. The consequence is that `stats.available` is **not** the number of things
the user can drill — on a freshly ingested textbook the entire depth-0 rank is
containers, all of them `available`, so the two numbers can differ by a lot.

A client that wants "how many skills are ready" must filter
`nodes.filter(n => n.assessable && n.progress.state === "available")`. It has
every node in the same payload, so this costs nothing; `frontend/app/courses/[courseId]/page.tsx`
does exactly that. `stats` is retained as-is so that
`locked + available + learning + decaying + mastered === total` stays true, which
is asserted by `tests/integration/test_graph_endpoint.py` and
`test_structural_nodes.py`.

**Every enum below is a bare `str` over the wire.** `state`, `Course.status`,
`GradeResult.verdict` and `Quest.reason` are serialised from Python enums into
plain strings and typed `str` on the response models, so nothing stops a new
member reaching a client built before it existed. `frontend/lib/types.ts` models
this with a `KnownX` / `X` pair rather than a closed union, and every lookup
keyed on one of them goes through an accessor with a fallback.

---

## Explore

Three reads that navigate a course rather than change it. All of them are
projections of data the pipeline already produces — the chunk vectors Chroma has
held since ingest, and the topological order `domain.dag.topological_depths`
computes on every persist. All three are owner-scoped and **404 rather than 403**
for someone else's course, like the rest of `/api/courses`.

### `GET /api/courses/{course_id}/search?q=…&limit=20` → `SearchResults`

```ts
type SearchResults = {
  query: string;
  results: SearchHit[];
  semantic: boolean;   // false => the vector index was unreachable; title-only results
};

type SearchHit = {
  node_id: string;
  slug: string;
  title: string;
  summary: string;
  assessable: boolean;
  depth: number;
  score: number;                            // 0..1, comparable across both matchers
  match: "title" | "content" | "both";      // bare `str` over the wire
  snippet: string;                          // the matching passage, or the summary
  source: { document_id: string; section_path: string | null; page_start: number } | null;
};
```

`q` is required and 1..200 characters; `limit` is 1..50 and defaults to 20.

**Two matchers, unioned.** Titles are matched by substring and by `difflib`
similarity, in Python, over the nodes already in the request. Content is matched
by embedding `q` and querying the course's Chroma collection, then folding the
returned chunks onto the nodes that own them via `skill_nodes.source_chunk_ids`.
Neither alone is sufficient: a three-letter acronym is a rounding error inside an
800-token chunk's vector, and a concept the author renamed is invisible to a
title matcher.

Scores are banded so a solid title match always outranks a strong vector one:
exact name 1.0, prefix 0.92, substring 0.84, fuzzy `ratio × 0.8` above a 0.62
floor; a semantic hit is `similarity × 0.78`. `score` is `max` of the two.

**A semantic hit below 0.15 similarity is discarded.** A vector index returns the
k *nearest* chunks, never the k relevant ones, so without a floor every query
matches every node that owns a chunk — searching a course for `zzzz` returned the
whole tree at `score: 0.0`.

**`semantic: false` is not "nothing matched".** It means the vector half could
not be reached, so the results are names only. A client that does not surface the
difference is telling the user the book does not mention something when the index
is merely down.

### `POST /api/courses/{course_id}/ask` → `AskAnswer`

```ts
// request
{ question: string }          // 3..1000 characters

type AskAnswer = {
  question: string;
  answer: string;
  citations: Citation[];
  retrieved: number;          // passages the model was shown; 0 => no model call was made
};

type Citation = {
  node_id: string;
  node_title: string;
  slug: string;
  chunk_id: string;
  quote: string;              // verified to be a substring of the cited chunk
  source: { document_id: string; section_path: string | null; page_start: number };
};
```

Retrieval prefers Chroma and falls back to a lexical scan over the course's
chunks, so a course whose collection has been dropped still answers rather than
500ing — this is the endpoint a stuck learner reaches for.

**Citations are filtered twice before they reach this response.** A citation must
name a passage the model was actually shown, and its `quote` must be a substring
of that passage with whitespace flattened. Anything else is dropped and logged.
The second check is the one that matters: a fluent, invented quotation attached to
a real node id is the failure that makes a cited answer worse than no answer.

`502` when the model returns something the schema rejects, or refuses. Reported
rather than swallowed into an empty answer, which the learner would read as "the
book does not cover this" — the one wrong thing to tell them.

`document_id` identifies the uploaded source in `CourseDetail.documents`, so the
frontend can show the filename alongside the section and page rather than
presenting every citation as an anonymous page number.

`retrieved: 0` with `citations: []` means retrieval found nothing and **no model
call was made** — an ungrounded answer is the one thing this endpoint must not
produce, and the cheapest guarantee is not to ask. `retrieved > 0` with
`citations: []` is different: the model was given material and would not claim
anything from it, which is a legitimate answer.

### `GET /api/courses/{course_id}/path` → `CoursePath`

```ts
type CoursePath = {
  course_id: string;
  steps: PathStep[];
  next_node_id: string | null;   // first step not yet cleared; null => all cleared
  completed: number;
  total: number;
};

type PathStep = {
  order: number;                 // 0-based position in the walk
  node_id: string;
  slug: string;
  title: string;
  summary: string;
  depth: number;                 // layer in the CONTRACTED graph, not skill_nodes.depth
  difficulty: 1 | 2 | 3 | 4 | 5;
  state: "locked" | "available" | "learning" | "decaying" | "mastered";
  mastery: number;               // 0..1
  done: boolean;                 // mastery >= 0.5, the prerequisite threshold
};
```

**Structural nodes are never steps.** A container cannot be drilled, so a walk
containing one sends the learner somewhere with nothing to do. They are *seen
through* instead — a container contributes its own prerequisites to whatever
depends on it, exactly as `gating_masteries` does for locking — so dropping them
loses no ordering. `depth` is recomputed on that contracted graph, because
`skill_nodes.depth` counts containers as layers and would report gaps that do not
exist for a learner.

**The route does not reorder as you progress.** A prerequisite order is a
property of the material, and a path that reshuffles between visits is one nobody
can hold in their head. What adapts is `next_node_id`. Because steps are in
topological order, when every earlier step is `done` every prerequisite of the
first un-done step is `done` too — so `next_node_id` can never name a locked node.

---

## Drill

### `POST /api/nodes/{node_id}/drill` → `201 Drill`

Header: `Idempotency-Key: <uuid>` (optional but recommended — a repeated key
returns the same attempt instead of paying for another generation call).

Query: `question_type=short_answer|mcq|cloze|code` (optional, defaults to
`short_answer`). The idempotency key is scoped to both the node and the requested
format.

```ts
type QuestionType = "short_answer" | "mcq" | "cloze" | "code";

type QuestionOption = {
  id: string;             // stable wire id, e.g. "option-a"
  text: string;
};

type Drill = {
  attempt_id: string;
  node_id: string;
  node_title: string;
  question: string;
  question_type: QuestionType;
  options: QuestionOption[]; // four options for MCQ; empty for other formats
  code_language: string | null; // present only for code drills
  difficulty: 1 | 2 | 3 | 4 | 5;
  sources: { document_id: string; section_path: string | null; page_start: number }[];
};
```

`409` if the node is `locked` or the idempotency key was already used for a
different node/format. MCQ choices are generated from the cited material; the
correct option is never included in the response.

### `POST /api/attempts/{attempt_id}/grade` → `GradeResult`

```jsonc
// short answer
{ "answer": "You multiply row i of A by column j of B and sum the products." }
// MCQ: send the selected option id, not its display text
{ "answer": "option-b" }
// Cloze: send the learner's fill
{ "answer": "orthogonal" }
// Code: send the snippet; the backend never executes it
{ "answer": "def dot(a, b):\\n    return ..." }
```

MCQ grading compares the submitted option id with the stored correct id and
makes no grading-model call. Cloze grading normalizes the answer against hidden
source-grounded accepted answers. Code grading performs only static matching of
stored observable requirements; learner code is never executed. All formats
return the same `GradeResult` shape, so EXP, mastery, and review scheduling are
identical across formats.

```ts
type GradeResult = {
  attempt_id: string;
  node_id: string;
  score: number;                              // 0..1
  verdict: "correct" | "partial" | "incorrect";
  feedback: string;
  points_hit: string[];                       // rubric point ids
  points_missed: string[];
  exp_awarded: number;
  rescue_bonus_applied: boolean;              // true when a decayed node was rescued
  level_before: number;                  // course-node level
  level_after: number;
  level_up: boolean;                      // course-node level-up
  account_level_before: number;
  account_level_after: number;
  account_level_up: boolean;              // character/account level-up
  user_total_exp: number;
  progress: GraphNode["progress"];            // the node's new state
  unlocked_node_ids: string[];                // newly reachable — drives the unlock cascade
};
```

Grading an already-graded attempt returns the stored result verbatim with
`exp_awarded` unchanged. Retrying on a flaky connection never double-awards.

---

## Quests

### `GET /api/quests/daily` → `QuestBoard`

```ts
type QuestBoard = {
  date: string;             // YYYY-MM-DD
  streak_days: number;
  total_reward_exp: number;
  quests: Quest[];
};

type Quest = {
  node_id: string;
  node_title: string;
  course_id: string;
  course_title: string;
  reason: "overdue" | "frontier";
  overdue_days: number;
  proficiency: number;
  due_at: string | null;    // next review time; null for a never-reviewed frontier skill
  reward_exp: number;       // includes the rescue bonus
};
```

Computed, not stored — the board is a query, which keeps the endpoint stateless.
Up to 8 `overdue` quests ranked by how badly overdue they are *relative to their
own interval*, topped up with `frontier` quests (available, never drilled,
shallowest depth) so a new user never opens an empty board.

---

## Admin

**`/api/admin` names the surface, not a privilege level.** There is no admin
flag. Every route below is owner-scoped through the same `get_owned` used by
`/api/courses/{id}/graph`, and someone else's course is a `404` rather than a
`403` so the prefix is not an enumeration oracle. The prefix is kept because
`CLAUDE.md`, this document and `docs/archive/graph_extraction_contract.md` all already
name `POST /api/admin/courses/{id}/reindex` by that path. A real admin flag
arrives with the first operation that is not course-scoped.

### `POST /api/admin/courses/{course_id}/reindex` → `202 ReindexAccepted`

Rebuilds the Chroma collection and the Neo4j projection from Postgres. This is
the escape hatch that makes the derived stores safe to depend on.

```ts
type ReindexAccepted = {
  job_id: string;
  course_id: string;
  scope: "all" | "graph" | "vectors";
  deduplicated: boolean;    // true when an unfinished reindex was joined instead
};
```

Query parameter `scope` (default `all`) picks which stores are rebuilt, because
their costs differ by orders of magnitude: `graph` is one bulk write over a few
hundred rows and is free, while `vectors` re-embeds every chunk in the course and
is billable. Poll the returned `job_id` on `GET /api/jobs/{id}` exactly as for an
upload.

**Reindex reads Postgres and does not write the graph.** It does not re-run
extraction, so `graph_version` does not move and no `node_progress` row is
touched. (The single Postgres write it does perform is `chunks.vector_id`, which
records the id a chunk was stored under in Chroma — bookkeeping about the derived
index, deterministic, and idempotent.) That is the property the endpoint exists
for: routing it through the
extraction pipeline would reach `persist_graph`, which full-replaces
`skill_nodes` and cascades away every user's EXP and review history, and would
increment the very `graph_version` that staleness is measured against.

Within a job, **Chroma is rebuilt before Neo4j**. Projecting writes
`graphVersion`, which is the entire input to the staleness check, so the reverse
order would leave the gauge reading "fine" over a half-written index. Unlike an
ingest, a projection failure **fails** a reindex — on a reindex the projection is
the deliverable, not a side effect.

### `GET /api/admin/courses/{course_id}/projection` → `ProjectionStatus`

```ts
type ProjectionStatus = {
  course_id: string;
  graph_version: number;        // Postgres, the source of truth
  node_count: number;
  edge_count: number;
  chunk_count: number;

  neo4j_reachable: boolean;
  projected_version: number | null;   // null when nothing has been projected
  stale: boolean;                     // projected_version !== graph_version

  chroma_reachable: boolean;
  vector_count: number | null;

  detail: string | null;        // why a store is unreachable, when one is
};
```

`stale` is the monitorable scalar `CLAUDE.md` names as the whole consistency
story. An absent projection is stale, not fresh — a course that has never been
projected reads exactly like one whose store was wiped, and both want a reindex.

**Never 500s.** An unreachable store is reported in the body (`reachable: false`,
`stale: true`) rather than raised; a status endpoint that fails when the store is
down is useless in the one situation it was written for. Deliberately not folded
into `CourseOut`, which runs per course on the list page: this makes two network
calls to two other services.

### `GET /api/admin/courses/{course_id}/rejections` → `RejectionsPage`

```ts
type RejectionReason = "self_loop" | "duplicate" | "unknown_node"
                     | "low_confidence" | "cycle";

type RejectionRow = {
  id: string;
  prereq_slug: string;
  target_slug: string;
  reason: RejectionReason;
  confidence: number | null;
  cycle_path: string[];      // the chain the edge would have closed; [] unless cycle
  created_at: string;
};

type RejectionsPage = {
  course_id: string;
  total: number;
  by_reason: Record<string, number>;  // over the WHOLE course, not the page
  limit: number;                      // 1..500, default 50
  offset: number;
  rows: RejectionRow[];
};
```

Edges the extractor proposed and the DAG builder refused — "the primary debugging
material for prompt iteration". Newest first, ties broken by id so a page
boundary never repeats or skips a row. Pagination is not decorative: a bad prompt
version produces thousands of rows in one ingest, which is exactly the run
someone opens this to understand.

### `GET /api/courses/{course_id}/cost` → `CourseCost`

Reads the `llm_calls` ledger. Every call goes through
`services/llm_gateway.recording_llm_client`, so **failures are included** — a
schema error still burned output tokens, and an ingest where 3 of 51 windows
failed is a fact that belongs in the ledger, not only in a log line.

```ts
type RoleCost = {
  // An LLM role ("graph_extract_map", "graph_merge", "prereq_infer",
  // "section_segment", "question_gen", "grade"), or "embedding".
  //
  // Embeddings are in the ledger because they are billable: retrieval embeds on
  // every drill, an ingest embeds every chunk, and a `scope=vectors` reindex is
  // a rebuild whose entire cost is embeddings. They carry no prompt, so their
  // `prompt_version` is the sentinel "n/a", and their `input_tokens` is an
  // estimate (chars / 4) -- embedding providers return vectors, not usage.
  role: string;
  model: string;
  prompt_version: string;
  calls: number;
  failed: number;          // calls - (calls with status "ok")
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  avg_latency_ms: number | null;
};

type CourseCost = {
  course_id: string;
  total_calls: number;
  failed_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  budget_usd: number;
  budget_remaining_usd: number;
  budget_exceeded: boolean;
  by_role: RoleCost[];
};
```

`by_role` is an **array grouped by `(role, model, prompt_version)`**, not a map
keyed by role. A map cannot represent the same role served by two models, or the
same role before and after a prompt edit — which is exactly the comparison the
ledger exists to make possible. Rows are ordered by descending spend.

`budget_usd` comes from `COURSE_LLM_BUDGET_USD` (default `$5.00`) and covers
billable LLM and embedding calls for this course. Before a real-provider call,
the backend estimates input tokens plus the role's maximum output; if that would
cross the remaining budget it rejects the call with `429` before contacting the
provider. Fake-provider calls estimate to zero and remain free. `budget_exceeded`
and `budget_remaining_usd` let the frontend explain why a campaign is paused.

---

## Webhooks (n8n)

**Owner:** `backend/app/api/routers/webhooks.py` +
`backend/app/services/webhook_service.py`
**Consumer:** n8n (and `scripts/smoke_webhooks.py` for the fake runner)

These are the n8n seam from the architecture blueprint: n8n schedules
`session.completed`, `feedback.requested`, and `daily-quests.refresh`; the
backend owns verification, dedupe, and every side effect. **The product never
depends on n8n running** — the synchronous practice path works with n8n
stopped, and these endpoints only exist to let automation trigger the same
services.

### Authentication

Every request signs the **exact request bytes** with HMAC-SHA256 keyed by
`WEBHOOK_SECRET`, sent as:

```
X-Webhook-Signature: sha256=<hex>
```

Compute it over the raw body, not the pretty-printed JSON:

```bash
python -c "import hmac,hashlib,sys; print('sha256='+hmac.new(b'<WEBHOOK_SECRET>', sys.stdin.buffer.read(), hashlib.sha256).hexdigest())" < payload.json
```

- `401` — missing or invalid signature (when `WEBHOOK_SECRET` is set).
- `503` — no `WEBHOOK_SECRET` and `DEV_WEBHOOKS_ENABLED` is false. The demo
  works without webhooks; they are opt-in configuration.
- `DEV_WEBHOOKS_ENABLED=true` accepts unsigned requests for local testing and
  the fake webhook runner. The deployed config validator refuses
  `DEPLOYED=true` with an empty `WEBHOOK_SECRET`, so this can never silently
  become a production bypass.

### Replay-safety and the event ledger

Every payload carries a caller-generated `event_id`. The first delivery
processes the event and stores the result in `webhook_events` (keyed by
`event_id`); **any replay of the same id answers from the ledger with
`status: "duplicate"` and never re-executes** — no second EXP award, voice
synthesis, or quest pass. n8n should generate one `event_id` per logical event
and reuse it on retries. Underlying services are idempotent anyway, so even a
fresh id is harmless. Events that fail validation (404 target, 422 payload)
are **not** recorded.

A `correlation_id` in the payload (or `X-Correlation-ID` header, which wins
when the payload lacks one) is echoed back and stored, so n8n runs are
traceable end to end.

### `POST /api/webhooks/v1/session.completed` → `WebhookResult`

Fired after a practice session completes. Verifies the attempt exists and
returns its outcome for n8n to act on (notifications, badges, downstream
workflows).

```jsonc
// request
{
  "event_id": "00000000-0000-0000-0000-000000000001",
  "occurred_at": "2026-08-20T12:00:00Z",
  "correlation_id": "run-42",          // optional
  "attempt_id": "00000000-0000-0000-0000-000000000003"
}
// 200 — result
{
  "attempt_id": "…",
  "status": "completed",               // completed | needs_review | failed
  "overall_score": 1.0,
  "exp_awarded": 100,
  "has_feedback": true
}
```

### `POST /api/webhooks/v1/feedback.requested` → `WebhookResult`

Returns the attempt's persisted examiner feedback; with `voice: true` it also
synthesizes (and content-addressed caches) the spoken feedback through the
voice service. `404` if the attempt does not exist.

```jsonc
// request
{
  "event_id": "00000000-0000-0000-0000-000000000002",
  "occurred_at": "2026-08-20T12:00:00Z",
  "attempt_id": "00000000-0000-0000-0000-000000000003",
  "voice": true                          // optional, default false
}
// 200 — result
{
  "attempt_id": "…",
  "feedback_provider": "deterministic",
  "feedback_persona": "Professor Cadenza",
  "feedback_tone": "celebratory",
  "feedback_summary": "Stepwise C Major was a clean, confident run at 100%.",
  "feedback_strengths": ["Your pitch is nearly flawless."],
  "feedback_corrections": [],
  "feedback_next_step": "Raise the tempo a little and press it once more.",
  "voice": {                             // only when voice: true
    "provider": "fake",
    "voice_key": "professor-cadenza",
    "format": "wav",
    "audio_base64": "UklGRgAAABdGTFNF…",
    "spoken_text": "…",
    "cache_key": "a1b2c3…",
    "cached": false
  }
}
```

### `POST /api/webhooks/v1/daily-quests.refresh` → `WebhookResult`

The nightly quest refresh. n8n schedules the call; the backend runs the
existing SRS/decay math (`quest_service.build_board`) and returns the computed
board. **Nothing time-derived is stored** — the board is a query, so rerunning
this is always safe and there are no rows to double-write.

```jsonc
// request
{
  "event_id": "00000000-0000-0000-0000-000000000003",
  "occurred_at": "2026-08-20T12:00:00Z",
  "user_id": "00000000-0000-0000-0000-000000000001"
}
// 200 — result
{
  "user_id": "…",
  "date": "2026-08-20",
  "quest_count": 3,
  "total_reward_exp": 250,
  "quests": [
    {
      "node_id": "…",
      "node_title": "Stepwise Melody",
      "course_id": "…",
      "course_title": "Piano",
      "reason": "overdue",
      "overdue_days": 2.4,
      "proficiency": 0.31,
      "due_at": "2026-08-18T00:00:00Z",
      "reward_exp": 80
    }
  ]
}
```

### `WebhookResult` (the shared envelope)

```ts
type WebhookResult = {
  event_id: string;
  event_type: string;       // session.completed | feedback.requested | daily-quests.refresh
  status: "processed" | "duplicate";
  correlation_id: string | null;
  result: Record<string, unknown>;  // per-type shape above
};
```

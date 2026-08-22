/**
 * The literal mirror of docs/api_contract.md.
 *
 * There is no shared codegen between a Python backend and a TypeScript frontend
 * in stage 1, so that document is the type system between them. Change it there
 * first, then here.
 */

/**
 * Every enum below comes over the wire as a bare `str` -- FastAPI serialises
 * `NodeState.LOCKED` to `"locked"` and the response models type it `str`, so
 * nothing on the backend stops a new member reaching this file.
 *
 * Each therefore has TWO types:
 *
 *   `KnownX`  the members this build knows about. Use it for the exhaustive
 *             `Record<KnownX, …>` style tables, so adding a member here is a
 *             compile error until every table covers it.
 *   `X`       what actually arrives. `(string & {})` widens to `string` while
 *             preserving autocomplete on the known members.
 *
 * The distinction is not academic. `STATE_STYLES[state].accent` on an unseen
 * state is a TypeError that takes the whole canvas down, and
 * `${STATUS_STYLE[status]}` on an unseen status renders the literal text
 * "undefined" into a className. Look every one of them up through the
 * fallback-bearing accessors in lib/nodeState.ts instead of indexing directly.
 */
export type KnownNodeState = "locked" | "available" | "learning" | "decaying" | "mastered";
export type NodeState = KnownNodeState | (string & {});

export interface User {
  id: string;
  email: string;
  display_name: string;
  total_exp: number;
  level: number;
  exp_into_level: number;
  exp_for_next_level: number;
  streak_days: number;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export type CharacterArchetype = "scholar" | "builder" | "explorer" | "mentor";
export type CharacterAvatar = "owl" | "fox" | "robot" | "wizard" | "cat" | "dragon";
export type CharacterSkinTone = "moon" | "sand" | "honey" | "copper" | "ebony";
export type CharacterHairStyle = "sweep" | "curls" | "bob" | "mohawk" | "crown";
export type CharacterHairColor = "ink" | "chestnut" | "silver" | "violet" | "rose";
export type CharacterOutfitColor = "azure" | "violet" | "coral" | "mint" | "gold";
export type CharacterAccessory = "none" | "glasses" | "headband" | "crown" | "earring";

export interface CharacterProfile {
  user_id: string;
  character_name: string;
  avatar_key: CharacterAvatar | string;
  archetype: CharacterArchetype | string;
  skin_tone: CharacterSkinTone | string;
  hair_style: CharacterHairStyle | string;
  hair_color: CharacterHairColor | string;
  outfit_color: CharacterOutfitColor | string;
  accessory: CharacterAccessory | string;
  unlocked_perks: string[];
  created_at: string;
}

export interface CharacterStats {
  focus: number;
  memory: number;
  resilience: number;
  curiosity: number;
}

export interface CharacterPerk {
  id: string;
  title: string;
  description: string;
  cost: number;
  unlocked: boolean;
}

export interface Achievement {
  id: string;
  title: string;
  description: string;
  progress: number;
  target: number;
  unlocked: boolean;
}

export interface CharacterSheet {
  profile: CharacterProfile | null;
  level: number;
  total_exp: number;
  exp_into_level: number;
  exp_for_next_level: number;
  streak_days: number;
  stats: CharacterStats;
  perks: CharacterPerk[];
  achievements: Achievement[];
  available_perk_points: number;
}

export interface PasswordResetRequested {
  message: string;
}

export type KnownCourseStatus = "draft" | "ingesting" | "ready" | "failed";
export type CourseStatus = KnownCourseStatus | (string & {});

/**
 * Where a course came from. A bare string over the wire, like `status`: a shelf
 * added after this build must not make a course vanish from every list.
 *
 * @see docs/api_contract.md
 */
export type CourseShelf = "learner" | "prebuilt" | "internal" | (string & {});

export interface Course {
  id: string;
  title: string;
  description: string | null;
  status: CourseStatus;
  /** "learner" for one they made, "prebuilt" for one offered ready-made, "internal" for one seeded for development. */
  shelf: CourseShelf;
  graph_version: number;
  node_count: number;
  edge_count: number;
  mastered_count: number;
  created_at: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  // Sniffed from the bytes, never from the filename or Content-Type. Left as a
  // bare string on purpose: the backend column's CHECK also permits "epub" and
  // "text", so narrowing it here would make the type lie the day either ships.
  source_type: string;
  /** Original public URL for web ingestion; null for local uploads. */
  source_uri: string | null;
  // Synthetic for HTML -- one page is one heading plus its prose. See
  // backend/app/ingestion/parsers/html.py.
  page_count: number | null;
  chunk_count: number;
  created_at: string;
}

export interface CourseDetail extends Course {
  documents: DocumentSummary[];
  /**
   * How this course's published curriculum was built, or null before one is
   * published. A tree the project authored and a tree the system proposed are
   * both playable; this is what tells them apart.
   */
  curriculum_provenance: CurriculumProvenance | null;
}

/** @see docs/api_contract.md — the values `compiler_version` can carry. */
export type CurriculumProvenance =
  | "catalogue-assembly-v1"
  | "catalogue-plan-v1"
  | "curriculum-compiler-v1"
  | (string & {});

/** The owner-facing answer to "share this course". */
export interface ShareCreated {
  course_id: string;
  /** The one place the raw token ever appears; copy it now. */
  url: string;
  created_at: string;
}

export interface ShareStatus {
  course_id: string;
  shared: boolean;
  /** The link is only ever shown at creation, so there is no url field here. */
  created_at: string | null;
}

/** One learner's standing inside a shared course's cohort. */
export interface LeaderboardEntry {
  display_name: string;
  level: number;
  total_exp: number;
  streak_days: number;
  /** Within this course: nodes mastered / started. */
  mastered_count: number;
  started_count: number;
  me: boolean;
}

export interface CourseLeaderboard {
  course_id: string;
  /** The original course plus every copy made from its share link. */
  cohort_size: number;
  entries: LeaderboardEntry[];
  /** 1-based rank of the caller; always present for the owner. */
  my_rank: number;
}

/** What an anonymous visitor sees from a share link, before deciding to copy. */
export interface SharePreview {
  course_id: string;
  title: string;
  description: string | null;
  status: string;
  node_count: number;
  edge_count: number;
  shared_by: string;
  created_at: string;
}

export interface CurriculumSource {
  id: string;
  rank: number;
  title: string;
  url: string;
  domain: string;
  snippet: string;
  discovery_angle: string;
  published_at: string | null;
  quality_score: number;
  quality_reasons: string[];
  policy_status: string;
  robots_url: string;
  robots_status: string;
  license_status: string;
  policy_reasons: string[];
  policy_checked_at: string | null;
  policy_acknowledged: boolean;
  selected: boolean;
  status: string;
  ingest_job_id: string | null;
  ingest_error: string | null;
}

export interface CurriculumProposal {
  id: string;
  course_id: string;
  goal: string;
  target_outcome: string;
  prior_knowledge: string;
  application_context: string;
  proposal_version: number;
  supersedes_id: string | null;
  learner_level: string;
  weekly_minutes: number;
  format_preference: string;
  provider: string;
  status: string;
  created_at: string;
  sources: CurriculumSource[];
}

export interface CurriculumVersion {
  id: string;
  course_id: string;
  instrument: string;
  slug: string;
  title: string;
  version: number;
  status: string;
  compiler_version: string;
  node_count: number;
  candidate_count: number;
  rejected_count: number;
  created_at: string;
  published_at: string | null;
}

export interface CurriculumCandidate {
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
}

export interface CurriculumPublishResult {
  version_id: string;
  course_id: string;
  graph_version: number;
  node_count: number;
  edge_count: number;
}

export interface ExerciseNote {
  pitch_midi: number | null;
  note_name: string;
  onset_beats: number;
  duration_beats: number;
  fret: number | null;
  string: number | null;
}

export interface Exercise {
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
  notes?: ExerciseNote[];
}

export interface PracticeSession {
  id: string;
  course_id: string;
  exercise_id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export interface PerformedNote {
  /** Null for rhythm-only instruments (drums), where `drum` carries identity. */
  pitch_midi: number | null;
  onset_seconds: number;
  duration_seconds: number;
  confidence: number;
  /** Guitar fretboard position; null for piano notes. */
  string?: number | null;
  fret?: number | null;
  /** Violin intonation offset in cents (positive sharp, negative flat). */
  cents_deviation?: number | null;
  /** Drum identity for rhythm-only instruments; ignored elsewhere. */
  drum?: string | null;
  /**
   * Mean level of the note in dBFS. Only ever compared to the other notes in
   * the same take -- absolute loudness is microphone gain and room, not
   * playing. Omitted when the client did not measure it.
   */
  level_db?: number | null;
}

/** One physical-form reading, already reduced in the browser. */
export interface PostureMetricIn {
  key: string;
  value: number;
  confidence: number;
  status: string;
  /** The geometry the value came from, so thresholds stay retunable. */
  raw?: number | null;
  unit?: string | null;
}

/** Derived posture for one take. Never landmarks, never video. */
export interface PostureObservation {
  version: string;
  threshold_version: string;
  instrument?: string | null;
  metrics: PostureMetricIn[];
  frame_count: number;
  coverage: number;
}

export interface PerformanceMetrics {
  evaluator_version: string;
  expected_note_count: number;
  observed_note_count: number;
  matched_note_count: number;
  missed_note_count: number;
  extra_note_count: number;
  /** Null for drums: rhythm-only instruments have no pitch to score. */
  pitch_accuracy: number | null;
  rhythm_accuracy: number;
  /** Fretboard position accuracy; null for instruments without tab positions. */
  technique_accuracy: number | null;
  position_error_count: number;
  /** Violin intonation; null for instruments that do not measure it. */
  intonation_accuracy: number | null;
  intonation_deviation_cents: number | null;
  /**
   * Dynamics. Null means the score carried no dynamic markings, or too few
   * notes were measured -- never "measured as zero".
   */
  dynamics_accuracy: number | null;
  dynamic_range_db: number | null;
  dynamics_contrast: number | null;
  /** Physical form from browser landmarks. Null when the camera was off. */
  posture_accuracy: number | null;
  posture_version: string | null;
  /** Which pitch detector produced the observations. */
  analyzer: string | null;
  tempo_bpm: number | null;
  tempo_deviation_percent: number | null;
  alignment_confidence: number;
  overall_score: number;
  low_confidence: boolean;
}

export interface ExaminerFeedback {
  persona: string;
  tone: string;
  summary: string;
  strengths: string[];
  corrections: string[];
  next_step: string;
}

export interface VoiceArtifact {
  attempt_id: string;
  /** fake | elevenlabs | unavailable — how the audio was produced. */
  provider: string;
  voice_key: string;
  format: string;
  /** Null when no voice provider is configured; use spoken_text + browser TTS. */
  audio_base64: string | null;
  spoken_text: string;
  cache_key: string;
  /** True when served from the content-addressed artifact store. */
  cached: boolean;
}

export interface Recording {
  id: string;
  course_id: string;
  /** The attempt this take was scored from, once the submission names it. */
  attempt_id: string | null;
  format: string;
  byte_size: number;
  content_sha256: string;
  duration_seconds: number | null;
  created_at: string;
  /** True when the upload was a content-addressed duplicate of an existing take. */
  deduplicated: boolean;
}

export interface PerformanceAttempt {
  id: string;
  session_id: string;
  exercise_id: string;
  status: string;
  overall_score: number;
  alignment_confidence: number;
  exp_awarded: number;
  /** deterministic | fake | anthropic | openai — how the coaching was produced. */
  feedback_provider: string;
  created_at: string;
  metrics: PerformanceMetrics;
  feedback: ExaminerFeedback;
}

export interface CampaignSkillRef {
  id: string;
  title: string;
}

export interface CampaignTreeShape {
  playable_skills: number;
  branches: number;
  prerequisite_links: number;
  depth: number;
  depth_counts: Record<string, number>;
  starting_skills: CampaignSkillRef[];
}

export interface CampaignOutcomeCoverage {
  outcome: string;
  terms: string[];
  matched_terms: string[];
  missing_terms: string[];
  coverage: number;
  signal: string;
}

export interface CampaignBriefing {
  course_id: string;
  goal: string | null;
  target_outcome: string;
  proposal_version: number | null;
  tree_shape: CampaignTreeShape;
  outcome_coverage: CampaignOutcomeCoverage;
}

export interface CampaignSideQuest {
  capability: string;
  title: string;
  reason: string;
  source_query: string;
  action: string;
}

export interface CampaignOutcomeEvaluation {
  course_id: string;
  outcome: string;
  provider: string;
  mode: string;
  evaluated_skill_count: number;
  readiness: number;
  matched_skills: CampaignSkillRef[];
  missing_capabilities: string[];
  side_quests: CampaignSideQuest[];
  rationale: string;
}

export interface CurriculumIngestItem {
  source_id: string;
  job_id: string | null;
  status: string;
  error: string | null;
}

export interface CurriculumIngestAccepted {
  proposal_id: string;
  course_id: string;
  accepted: CurriculumIngestItem[];
}

export interface IngestAccepted {
  document: DocumentSummary;
  job_id: string;
  deduplicated: boolean;
}

export type JobState =
  | "queued"
  | "parsing"
  | "chunking"
  | "embedding"
  | "extracting"
  | "reducing"
  | "finalizing"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface IngestJob {
  id: string;
  /**
   * Null for a `reindex` job, which rebuilds the derived stores for the whole
   * course and so has no single document to point at. Ingest jobs always have
   * one -- the backend CHECK constraint enforces both halves.
   */
  document_id: string | null;
  course_id: string;
  state: JobState;
  units_done: number;
  units_total: number;
  percent: number;
  /**
   * `boolean` is in the union for the reindex job's `stale` post-condition --
   * the projection is read back after being written, and the answer lands here.
   */
  stage_detail: Record<string, number | string | boolean | null>;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface NodeRef {
  id: string;
  title: string;
}

export interface NodeProgress {
  state: NodeState;
  exp: number;
  level: number;
  /** EMA of graded scores. Does not decay. */
  mastery: number;
  /** Mastery after time decay -- this is what the ring shows. */
  proficiency: number;
  due_at: string | null;
  overdue_days: number;
}

export interface SourceEvidence {
  chunk_id: string;
  document_id: string;
  section_path: string | null;
  page_start: number;
  excerpt: string;
}

export interface GraphNode {
  id: string;
  slug: string;
  title: string;
  summary: string;
  difficulty: number;
  depth: number;
  assessable: boolean;
  /**
   * The outline heading this skill was found under. Provenance and a grouping
   * key for the canvas -- never structure. The chapter a concept was printed in
   * is not one of its prerequisites, so it is a label rather than a node.
   * `null` when the document had no usable outline.
   */
  section: string | null;
  progress: NodeProgress;
  blocked_by: NodeRef[];
  sources: SourceEvidence[];
}

export interface GraphEdge {
  id: string;
  /** The PREREQUISITE. Named to match React Flow exactly. */
  source: string;
  /** Depends on `source`. */
  target: string;
  confidence: number;
  support: number;
  rationale: string | null;
  sources: SourceEvidence[];
}

export interface GraphStats {
  total: number;
  locked: number;
  available: number;
  learning: number;
  decaying: number;
  mastered: number;
}

export interface GraphSnapshot {
  course_id: string;
  graph_version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: GraphStats;
}

export type QuestionType = "short_answer" | "mcq" | "cloze" | "code";

export interface QuestionOption {
  id: string;
  text: string;
}

export interface SourceRef {
  /** The document owning the cited chunk; resolve through CourseDetail.documents. */
  document_id: string;
  section_path: string | null;
  page_start: number;
}

export interface Drill {
  attempt_id: string;
  node_id: string;
  node_title: string;
  question: string;
  question_type: QuestionType;
  options: QuestionOption[];
  code_language: string | null;
  difficulty: number;
  sources: SourceRef[];
}

export type KnownVerdict = "correct" | "partial" | "incorrect";
export type Verdict = KnownVerdict | (string & {});

export interface GradeResult {
  attempt_id: string;
  node_id: string;
  score: number;
  verdict: Verdict;
  feedback: string;
  points_hit: string[];
  points_missed: string[];
  exp_awarded: number;
  rescue_bonus_applied: boolean;
  level_before: number;
  level_after: number;
  level_up: boolean;
  account_level_before: number;
  account_level_after: number;
  account_level_up: boolean;
  user_total_exp: number;
  progress: NodeProgress;
  unlocked_node_ids: string[];
}

/** `overdue` is a decayed skill being rescued; `frontier` is a never-drilled top-up. */
export type KnownQuestReason = "overdue" | "frontier";
export type QuestReason = KnownQuestReason | (string & {});

/** Which matcher found a search hit. `both` means the title and the prose agreed. */
export type KnownSearchMatch = "title" | "content" | "both";
export type SearchMatch = KnownSearchMatch | (string & {});

export interface SearchHit {
  node_id: string;
  slug: string;
  title: string;
  summary: string;
  assessable: boolean;
  depth: number;
  /** 0..1, comparable across the title and semantic matchers. */
  score: number;
  match: SearchMatch;
  /** The matching passage, or the node's summary for a title-only hit. */
  snippet: string;
  source: SourceRef | null;
}

export interface SearchResults {
  query: string;
  results: SearchHit[];
  /**
   * False when the vector index could not be reached, so these results are
   * title-only. "Nothing matched" and "semantic search is down" look identical
   * without this.
   */
  semantic: boolean;
}

export interface Citation {
  node_id: string;
  node_title: string;
  slug: string;
  chunk_id: string;
  /** Verified server-side to be a substring of the cited chunk. */
  quote: string;
  source: SourceRef;
}

export interface AskAnswer {
  question: string;
  answer: string;
  citations: Citation[];
  /** Passages the model was shown. 0 means retrieval found nothing to ground on. */
  retrieved: number;
}

export interface PathStep {
  order: number;
  node_id: string;
  slug: string;
  title: string;
  summary: string;
  depth: number;
  difficulty: number;
  state: NodeState;
  mastery: number;
  done: boolean;
}

export interface CoursePath {
  course_id: string;
  steps: PathStep[];
  /** The first step not yet cleared: "start here", or "next" once some are. */
  next_node_id: string | null;
  completed: number;
  total: number;
}

export interface ProgressTrendPoint {
  date: string;
  attempts: number;
  average_score: number;
  mastery: number;
  exp_earned: number;
}

export interface ProgressSourceCoverage {
  document_id: string;
  filename: string;
  skills_total: number;
  skills_started: number;
  attempts: number;
}

export interface ProgressAnalytics {
  course_id: string;
  total_skills: number;
  started_skills: number;
  mastered_skills: number;
  total_attempts: number;
  average_score: number | null;
  exp_earned: number;
  review_days: number;
  tracked_days: number;
  consistency: number;
  mastery_trend: ProgressTrendPoint[];
  source_coverage: ProgressSourceCoverage[];
}

export interface Quest {
  node_id: string;
  node_title: string;
  course_id: string;
  course_title: string;
  reason: QuestReason;
  overdue_days: number;
  proficiency: number;
  due_at: string | null;
  reward_exp: number;
}

export interface QuestBoard {
  date: string;
  streak_days: number;
  total_reward_exp: number;
  quests: Quest[];
}

/**
 * One row of the `llm_calls` ledger, grouped by (role, model, prompt_version).
 *
 * Grouped rather than keyed by role on purpose: the same role can be served by
 * two models, or by one prompt before and after an edit, and telling those
 * apart is the entire reason the ledger stores a prompt hash.
 */
export interface RoleCost {
  role: string;
  model: string;
  prompt_version: string;
  calls: number;
  /** Calls that did not return `ok`. A schema error still burned output tokens. */
  failed: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  avg_latency_ms: number | null;
}

export interface CourseCost {
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
}

// ── admin surface ──────────────────────────────────────────────────────────
//
// `/api/admin` names the surface, not a privilege level: every route is
// owner-scoped exactly like `/api/courses/{id}/graph`, and someone else's course
// is a 404 rather than a 403.

/**
 * Which derived stores a reindex rebuilds.
 *
 * Not cosmetic: `graph` is one bulk write over a few hundred rows and is free,
 * while `vectors` re-embeds every chunk in the course and costs real money.
 */
export type ReindexScope = "all" | "graph" | "vectors";

export interface ReindexAccepted {
  job_id: string;
  course_id: string;
  scope: ReindexScope;
  /** True when an unfinished reindex was joined rather than a second started. */
  deduplicated: boolean;
}

/**
 * Is the projection stale?
 *
 * The one monitorable scalar of the whole design: Postgres is the source of
 * truth, Neo4j and Chroma are derived, so consistency is a comparison rather
 * than a correctness bug. An absent projection (`projected_version === null`)
 * is stale, not fresh.
 *
 * This never fails on an unreachable store -- that is reported here, in the
 * body, because a status endpoint that errors when the store is down is useless
 * in the one situation it exists for.
 */
export interface ProjectionStatus {
  course_id: string;
  graph_version: number;
  node_count: number;
  edge_count: number;
  chunk_count: number;

  neo4j_reachable: boolean;
  projected_version: number | null;
  stale: boolean;

  chroma_reachable: boolean;
  vector_count: number | null;

  /** Why a store is unreachable, when one is. */
  detail: string | null;
}

export type RejectionReason =
  | "self_loop"
  | "duplicate"
  | "unknown_node"
  | "low_confidence"
  | "cycle";

export interface RejectionRow {
  id: string;
  prereq_slug: string;
  target_slug: string;
  reason: RejectionReason;
  confidence: number | null;
  /** The chain the edge would have closed. Empty unless `reason` is "cycle". */
  cycle_path: string[];
  created_at: string;
}

export interface RejectionsPage {
  course_id: string;
  total: number;
  /** Counted over the whole course, so it does not change as you page. */
  by_reason: Record<string, number>;
  limit: number;
  offset: number;
  rows: RejectionRow[];
}


/** One calendar day of practice, averaged. */
export interface DailyMetricsOut {
  day: string;
  attempts: number;
  means: Record<string, number>;
}

export interface MetricComparisonOut {
  key: string;
  current: number;
  previous: number | null;
  change: number;
  /** Which way the number moved: up | down | baseline. */
  trend: string;
  improvement_percentage: number | null;
  /**
   * Whether that movement is good news. Null when the metric has no declared
   * polarity -- "we do not know" is a real answer, and different from "no".
   */
  improved: boolean | null;
}

/** How a learner's practice has moved. Computed on read, never stored. */
/** One lesson in a skill's run. @see docs/api_contract.md */
export interface Lesson {
  exercise_id: string;
  title: string;
  /** What the learner is asked to play, so a realm can say so before they commit. */
  instructions: string;
  difficulty: number;
  /** Ordinal within the run, from 1. A run is a sequence, not a set. */
  step: number;
  attempts: number;
  /** The learner's best take, or null where they have never played it. */
  best_score: number | null;
  cleared: boolean;
  /** Playable now. Cleared lessons stay open, because skills decay. */
  open: boolean;
}

/** A skill's lesson run and whether its test has been earned. */
export interface SkillRealm {
  node_id: string;
  node_title: string;
  lessons: Lesson[];
  /** The step to play next, or null when every lesson is cleared. */
  open_step: number | null;
  test_open: boolean;
}

export interface PracticeReport {
  course_id: string;
  exercise_id: string | null;
  window_days: number;
  attempt_count: number;
  practice_days: number;
  summary: string;
  insights: string[];
  daily: DailyMetricsOut[];
  comparisons: MetricComparisonOut[];
}

export interface CoachLiveTipRequest {
  exercise_title: string;
  instrument: string;
  tempo_bpm: number;
  current_note?: string | null;
  signed_timing_bias_seconds?: number | null;
  mean_pitch_error_semitones?: number | null;
  streak_count?: number;
}

export interface CoachLiveTipResponse {
  tip: string;
  focus_area: string;
  suggested_action: string;
}

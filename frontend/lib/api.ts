/**
 * Typed fetch client. Hand-written rather than generated: at ~10 endpoints a
 * codegen step costs more than it saves, and lib/types.ts already gives the
 * compile-time contract.
 */

import type {
  AskAnswer,
  CharacterAccessory,
  CharacterArchetype,
  CharacterAvatar,
  CharacterHairColor,
  CharacterHairStyle,
  CharacterOutfitColor,
  CharacterSheet,
  CharacterSkinTone,
  CampaignBriefing,
  CampaignOutcomeEvaluation,
  CoachLiveTipRequest,
  CoachLiveTipResponse,
  Course,
  CourseCost,
  CourseDetail,
  CurriculumCandidate,
  CurriculumIngestAccepted,
  CurriculumProposal,
  CurriculumPublishResult,
  CurriculumVersion,
  Exercise,
  PerformanceAttempt,
  PerformedNote,
  PostureObservation,
  PracticeReport,
  PracticeSession,
  Recording,
  SkillRealm,
  VoiceArtifact,
  CourseLeaderboard,
  CoursePath,
  Drill,
  GradeResult,
  GraphSnapshot,
  IngestAccepted,
  IngestJob,
  PasswordResetRequested,
  ProgressAnalytics,
  ProjectionStatus,
  QuestionType,
  QuestBoard,
  SearchResults,
  ReindexAccepted,
  ReindexScope,
  RejectionsPage,
  ShareCreated,
  SharePreview,
  ShareStatus,
  TokenResponse,
  User,
} from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_KEY = "learn-anything.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function readToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function writeToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token === null) {
    window.localStorage.removeItem(TOKEN_KEY);
  } else {
    window.localStorage.setItem(TOKEN_KEY, token);
  }
}

let refreshInFlight: Promise<string | null> | null = null;

async function rotateAccessToken(): Promise<string | null> {
  if (refreshInFlight === null) {
    refreshInFlight = fetch(`${BASE_URL}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then(async (response) => {
        if (!response.ok) return null;
        const result = (await response.json()) as TokenResponse;
        writeToken(result.access_token);
        return result.access_token;
      })
      .catch(() => null)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

const AUTH_PATHS_WITHOUT_REFRESH = new Set([
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/refresh",
  "/api/auth/logout",
  "/api/auth/password-reset/request",
  "/api/auth/password-reset/consume",
  "/api/auth/google/exchange",
]);

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = readToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response = await fetch(`${BASE_URL}${path}`, { ...init, headers, credentials: "include" });

  if (
    response.status === 401
    && token !== null
    && !AUTH_PATHS_WITHOUT_REFRESH.has(path)
  ) {
    const refreshedToken = await rotateAccessToken();
    if (refreshedToken !== null) {
      headers.set("Authorization", `Bearer ${refreshedToken}`);
      response = await fetch(`${BASE_URL}${path}`, { ...init, headers, credentials: "include" });
    }
  }

  if (!response.ok) {
    // FastAPI puts the message on `detail`; a 422 puts an array there.
    let message = response.statusText;
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail) && detail.length > 0) {
        message = detail.map((d: { msg?: string }) => d.msg ?? "invalid").join("; ");
      }
    } catch {
      // Body was not JSON; keep the status text.
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  register: (email: string, password: string, displayName: string) =>
    request<TokenResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName }),
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  requestPasswordReset: (email: string) =>
    request<PasswordResetRequested>("/api/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  consumePasswordReset: (token: string, password: string) =>
    request<TokenResponse>("/api/auth/password-reset/consume", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),

  exchangeGoogleCode: (code: string) =>
    request<TokenResponse>("/api/auth/google/exchange", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  refresh: () => request<TokenResponse>("/api/auth/refresh", { method: "POST" }),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  googleStartUrl: () => `${BASE_URL}/api/auth/google/start`,

  /** Only exists when the backend runs with DEV_AUTH_ENABLED=true. */
  devLogin: () => request<TokenResponse>("/api/auth/dev-login", { method: "POST" }),

  me: () => request<User>("/api/auth/me"),

  getCharacter: () => request<CharacterSheet>("/api/character"),

  createCharacter: (
    characterName: string,
    avatarKey: CharacterAvatar,
    archetype: CharacterArchetype,
    appearance: {
      skin_tone: CharacterSkinTone;
      hair_style: CharacterHairStyle;
      hair_color: CharacterHairColor;
      outfit_color: CharacterOutfitColor;
      accessory: CharacterAccessory;
    },
  ) =>
    request<CharacterSheet>("/api/character", {
      method: "POST",
      body: JSON.stringify({ character_name: characterName, avatar_key: avatarKey, archetype, ...appearance }),
    }),

  updateCharacter: (payload: {
    character_name?: string;
    avatar_key?: CharacterAvatar;
    archetype?: CharacterArchetype;
    skin_tone?: CharacterSkinTone;
    hair_style?: CharacterHairStyle;
    hair_color?: CharacterHairColor;
    outfit_color?: CharacterOutfitColor;
    accessory?: CharacterAccessory;
  }) =>
    request<CharacterSheet>("/api/character", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  unlockCharacterPerk: (perkId: string) =>
    request<CharacterSheet>(`/api/character/perks/${encodeURIComponent(perkId)}`, { method: "POST" }),

  listCourses: () => request<{ courses: Course[] }>("/api/courses"),

  createCourse: (title: string, description?: string) =>
    request<Course>("/api/courses", {
      method: "POST",
      body: JSON.stringify({ title, description: description || null }),
    }),

  /**
   * Build a published skill tree from a learner's own sentence.
   *
   * One request: the instrument is read out of the goal and the tree is
   * assembled from the shared catalogue. A goal naming no instrument comes back
   * 422 with a message worth showing the learner verbatim.
   */
  // @spec CURR-GOAL-001
  createCourseFromGoal: (goal: string) =>
    request<Course>("/api/courses/from-goal", {
      method: "POST",
      body: JSON.stringify({ goal }),
    }),

  getCourse: (courseId: string) => request<CourseDetail>(`/api/courses/${courseId}`),

  /** The cohort scoreboard for this course: original plus every share-copy. */
  getLeaderboard: (courseId: string) =>
    request<CourseLeaderboard>(`/api/courses/${courseId}/leaderboard`),

  /** Create (or rotate) the course's share link. Only `ready` courses qualify. */
  shareCourse: (courseId: string) =>
    request<ShareCreated>(`/api/courses/${courseId}/share`, { method: "POST" }),

  getShareStatus: (courseId: string) =>
    request<ShareStatus>(`/api/courses/${courseId}/share`),

  revokeShare: (courseId: string) =>
    request<void>(`/api/courses/${courseId}/share`, { method: "DELETE" }),

  /** Public: the token is the credential, so no auth header is sent. */
  getSharePreview: (token: string) => request<SharePreview>(`/api/shares/${token}`),

  /** Deep-copy a shared course into the caller's account; idempotent. */
  copySharedCourse: (token: string) =>
    request<Course>(`/api/shares/${token}/copy`, { method: "POST" }),

  getCampaignBriefing: (courseId: string) =>
    request<CampaignBriefing>(`/api/courses/${courseId}/campaign/briefing`),

  evaluateCampaignOutcome: (courseId: string) =>
    request<CampaignOutcomeEvaluation>(`/api/courses/${courseId}/campaign/evaluate`, {
      method: "POST",
    }),

  getLatestCurriculumProposal: (courseId: string) =>
    request<CurriculumProposal>(`/api/courses/${courseId}/curriculum/proposals/latest`),

  createCurriculumProposal: (
    courseId: string,
    goal: string,
    learnerLevel = "beginner",
    weeklyMinutes = 120,
    formatPreference = "mixed",
    maxSources = 8,
    targetOutcome = "",
    priorKnowledge = "",
    applicationContext = "",
  ) =>
    request<CurriculumProposal>(`/api/courses/${courseId}/curriculum/proposals`, {
      method: "POST",
      body: JSON.stringify({
        goal,
        target_outcome: targetOutcome,
        prior_knowledge: priorKnowledge,
        application_context: applicationContext,
        learner_level: learnerLevel,
        weekly_minutes: weeklyMinutes,
        format_preference: formatPreference,
        max_sources: maxSources,
      }),
    }),

  checkCurriculumSourcePolicy: (courseId: string, proposalId: string, sourceId: string) =>
    request<CurriculumProposal>(
      `/api/courses/${courseId}/curriculum/proposals/${proposalId}/sources/${sourceId}/policy-check`,
      { method: "POST" },
    ),

  approveCurriculumSources: (
    courseId: string,
    proposalId: string,
    sourceIds: string[],
    acknowledgePolicy = false,
  ) =>
    request<CurriculumProposal>(`/api/courses/${courseId}/curriculum/proposals/${proposalId}/approve`, {
      method: "POST",
      body: JSON.stringify({ source_ids: sourceIds, acknowledge_policy: acknowledgePolicy }),
    }),

  ingestCurriculumSources: (courseId: string, proposalId: string) =>
    request<CurriculumIngestAccepted>(`/api/courses/${courseId}/curriculum/proposals/${proposalId}/ingest`, {
      method: "POST",
    }),

  createCurriculumVersion: (
    courseId: string,
    payload: {
      instrument: string;
      instrument_title: string;
      slug: string;
      title: string;
      compiler_version?: string;
      source_bundle_sha256?: string | null;
      concepts: Array<{
        slug: string;
        title: string;
        summary: string;
        difficulty?: number | null;
        assessable?: boolean;
        key_terms?: string[];
        source_chunk_ids?: string[];
        section?: string | null;
      }>;
      edges?: Array<{
        prereq: string;
        target: string;
        confidence?: number;
        support?: number;
        rationale?: string;
        evidence?: Array<{
          chunk_id: string;
          quote: string;
          extractor_version?: string;
          prompt_sha256?: string | null;
          source_sha256?: string | null;
        }>;
      }>;
    },
  ) =>
    request<CurriculumVersion>(`/api/courses/${courseId}/curriculum/versions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listCurriculumCandidates: (courseId: string, versionId: string) =>
    request<CurriculumCandidate[]>(
      `/api/courses/${courseId}/curriculum/versions/${versionId}/candidates`,
    ),

  reviewCurriculumCandidate: (
    courseId: string,
    versionId: string,
    candidateId: string,
    decision: "accepted" | "rejected" | "ambiguous",
    reason = "",
  ) =>
    request<CurriculumCandidate>(
      `/api/courses/${courseId}/curriculum/versions/${versionId}/candidates/${candidateId}/review`,
      { method: "POST", body: JSON.stringify({ decision, reason }) },
    ),

  publishCurriculumVersion: (courseId: string, versionId: string) =>
    request<CurriculumPublishResult>(`/api/courses/${courseId}/curriculum/versions/${versionId}/publish`, {
      method: "POST",
    }),

  listPracticeExercises: (courseId: string) =>
    request<Exercise[]>(`/api/courses/${courseId}/practice/exercises`),

  /** Every skill's lesson run in one call: the realm reads this. */
  listSkillRealms: (courseId: string) =>
    request<SkillRealm[]>(`/api/courses/${courseId}/practice/realms`),

  createPracticeSession: (exerciseId: string) =>
    request<PracticeSession>("/api/practice/sessions", {
      method: "POST",
      body: JSON.stringify({ exercise_id: exerciseId }),
    }),

  submitPerformanceAttempt: (
    sessionId: string,
    observedNotes: PerformedNote[],
    idempotencyKey: string,
    recordingId: string | null = null,
    // Derived posture only -- never landmarks, never video. Omitting it is not
    // a failure: the posture weight redistributes and the take scores exactly
    // as it would have with no camera in the room.
    posture: PostureObservation | null = null,
    analyzer: string | null = null,
  ) =>
    request<PerformanceAttempt>(`/api/practice/sessions/${sessionId}/attempts`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        observed_notes: observedNotes,
        recording_id: recordingId,
        posture,
        analyzer,
      }),
    }),

  /** How this learner's practice has moved. Computed on read, never stored. */
  getPracticeReport: (courseId: string, options: { exerciseId?: string; days?: number } = {}) => {
    const params = new URLSearchParams();
    if (options.exerciseId !== undefined) params.set("exercise_id", options.exerciseId);
    if (options.days !== undefined) params.set("days", String(options.days));
    const query = params.toString();
    return request<PracticeReport>(`/api/courses/${courseId}/practice/report${query === "" ? "" : `?${query}`}`);
  },

  /** Generate a score-backed exercise for one skill node. Idempotent. */
  generateExercise: (courseId: string, nodeId: string, options: Record<string, unknown> = {}) =>
    request<Exercise>(`/api/courses/${courseId}/practice/exercises`, {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, ...options }),
    }),

  /** Get real-time pedagogical AI guidance tailored to current performance metrics. */
  getLiveCoachTip: (courseId: string, payload: CoachLiveTipRequest) =>
    request<CoachLiveTipResponse>(`/api/courses/${courseId}/practice/coach/tip`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** Preserve the raw take; content-addressed per user, so re-uploads dedupe. */
  uploadRecording: (
    courseId: string,
    blob: Blob,
    durationSeconds: number | null = null,
  ) => {
    const format = (blob.type.split(";")[0].split("/")[1] ?? "webm").toLowerCase();
    return new Promise<Recording>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = typeof reader.result === "string" ? reader.result : "";
        const comma = dataUrl.indexOf(",");
        const contentBase64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
        request<Recording>("/api/recordings", {
          method: "POST",
          body: JSON.stringify({
            course_id: courseId,
            format,
            duration_seconds: durationSeconds,
            content_base64: contentBase64,
          }),
        })
          .then(resolve)
          .catch(reject);
      };
      reader.onerror = () => reject(reader.error ?? new Error("Could not read the recording."));
      reader.readAsDataURL(blob);
    });
  },

  getPerformanceAttempt: (attemptId: string) =>
    request<PerformanceAttempt>(`/api/practice/attempts/${attemptId}`),

  /** Speak the attempt's examiner feedback; falls back to text when no voice is configured. */
  speakAttemptFeedback: (attemptId: string) =>
    request<VoiceArtifact>(`/api/practice/attempts/${attemptId}/speech`, { method: "POST" }),

  getGraph: (courseId: string) => request<GraphSnapshot>(`/api/courses/${courseId}/graph`),

  uploadDocument: (courseId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<IngestAccepted>(`/api/courses/${courseId}/documents`, {
      method: "POST",
      body: form,
    });
  },

  // Unlike uploadDocument this one blocks while the backend fetches the page,
  // so it can take up to URL_FETCH_TIMEOUT_SECONDS to answer. Every refusal --
  // private address, bad scheme, oversized body -- comes back as a 400 whose
  // message is written to be shown to the user as-is.
  ingestDocumentUrl: (courseId: string, url: string) =>
    request<IngestAccepted>(`/api/courses/${courseId}/documents/url`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  getJob: (jobId: string) => request<IngestJob>(`/api/jobs/${jobId}`),

  /** Retry a failed ingest from the document already stored by the backend. */
  retryJob: (jobId: string) =>
    request<IngestAccepted>(`/api/jobs/${jobId}/retry`, { method: "POST" }),

  /** `signal` so a keystroke can abort the request the previous keystroke made. */
  searchCourse: (courseId: string, query: string, signal?: AbortSignal) =>
    request<SearchResults>(`/api/courses/${courseId}/search?q=${encodeURIComponent(query)}`, { signal }),

  askCourse: (courseId: string, question: string, signal?: AbortSignal) =>
    request<AskAnswer>(`/api/courses/${courseId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
      signal,
    }),

  getCoursePath: (courseId: string) => request<CoursePath>(`/api/courses/${courseId}/path`),
  getCourseProgress: (courseId: string) => request<ProgressAnalytics>(`/api/courses/${courseId}/progress`),
  /**
   * Ask a job to stop. Cooperative: a queued job never starts, a running one
   * finishes its current stage and then stops. 409 once it has finished.
   */
  cancelJob: (jobId: string) =>
    request<IngestJob>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),

  /**
   * Rebuild the derived stores from Postgres. Returns a job to poll with
   * `pollJob`, exactly like an upload.
   */
  reindexCourse: (courseId: string, scope: ReindexScope = "all") =>
    request<ReindexAccepted>(
      `/api/admin/courses/${courseId}/reindex?scope=${scope}`,
      { method: "POST" },
    ),

  getProjection: (courseId: string) =>
    request<ProjectionStatus>(`/api/admin/courses/${courseId}/projection`),

  getRejections: (courseId: string, limit = 50, offset = 0) =>
    request<RejectionsPage>(
      `/api/admin/courses/${courseId}/rejections?limit=${limit}&offset=${offset}`,
    ),

  startDrill: (nodeId: string, idempotencyKey: string, questionType: QuestionType = "short_answer") =>
    request<Drill>(`/api/nodes/${nodeId}/drill?question_type=${questionType}`, {
      method: "POST",
      // Makes a retry of THIS request free rather than paying for a second
      // question generation.
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  getQuests: () => request<QuestBoard>("/api/quests/daily"),

  getCourseCost: (courseId: string) => request<CourseCost>(`/api/courses/${courseId}/cost`),

  gradeAttempt: (attemptId: string, answer: string) =>
    request<GradeResult>(`/api/attempts/${attemptId}/grade`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
};

const TERMINAL_STATES = new Set(["succeeded", "failed", "cancelled"]);

/**
 * Poll a job to completion.
 *
 * Backs off from 1.5s to 5s after a minute, because ingesting a real textbook
 * is measured in minutes and hammering the endpoint buys nothing.
 */
export async function pollJob(
  jobId: string,
  onProgress: (job: IngestJob) => void,
  shouldStop: () => boolean = () => false,
): Promise<IngestJob> {
  const startedAt = Date.now();
  let consecutiveFailures = 0;

  for (;;) {
    let job: IngestJob | null = null;
    let pollingError: unknown = null;
    try {
      job = await api.getJob(jobId);
      consecutiveFailures = 0;
    } catch (caught) {
      // A single transient 5xx or network blip must not abandon a long ingest.
      // Keep polling with a small cap; a sustained outage still reaches the UI
      // after five attempts instead of retrying forever.
      pollingError = caught;
      consecutiveFailures += 1;
    }

    if (job !== null) {
      onProgress(job);
      if (TERMINAL_STATES.has(job.state) || shouldStop()) {
        return job;
      }
    } else if (consecutiveFailures >= 5) {
      throw pollingError;
    }

    if (shouldStop()) {
      throw pollingError ?? new Error("Job polling stopped.");
    }

    const elapsed = Date.now() - startedAt;
    const interval = job === null
      ? Math.min(5_000, 1_500 * 2 ** (consecutiveFailures - 1))
      : elapsed > 60_000
        ? 5_000
        : 1_500;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}

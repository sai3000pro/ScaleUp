import {
  VISUAL_ANALYSIS_VERSION,
  collapseVisualHighlights,
  isCountableVisualMetric,
  summarizeVisualFrames,
  type VisualAnalysisSummary,
  type VisualHighlight,
  type VisualObservationFrame,
} from "@/lib/videoAnalysis";

export const VISUAL_ASSESSMENT_VERSION = "visual-assessment-v2";

export type VisualAssessmentOutcome = "pass" | "retry" | "insufficient_evidence";
export type VisualRequirementPassState = "pass" | "retry" | "insufficient_evidence";

export interface VisualAssessmentRequirement {
  metricKey: string;
  label: string;
  weight: number;
  critical: boolean;
  passFloor: number;
}

export interface VisualAssessmentProfile {
  id: string;
  version: string;
  instrument: string;
  skillSlug: string;
  title: string;
  confidenceFloor: number;
  coverageFloor: number;
  overallPassFloor: number;
  requirements: readonly VisualAssessmentRequirement[];
}

export interface VisualRequirementResult {
  metricKey: string;
  label: string;
  weight: number;
  critical: boolean;
  passFloor: number;
  coverage: number;
  countableFrameCount: number;
  totalFrameCount: number;
  medianValue: number | null;
  goodFrameRatio: number | null;
  score: number | null;
  passState: VisualRequirementPassState;
  corrections: VisualHighlight[];
}

export interface VisualAssessmentResult {
  profileId: string;
  profileVersion: string;
  instrument: string;
  skillSlug: string;
  skillTitle: string;
  outcome: VisualAssessmentOutcome;
  overallScore: number | null;
  evidenceCoverage: number;
  thresholds: {
    confidenceFloor: number;
    coverageFloor: number;
    overallPassFloor: number;
  };
  requirements: VisualRequirementResult[];
}

export interface VisualAssessmentExport {
  schemaVersion: string;
  source: {
    kind: "selected-video";
    fileName: string;
    durationMs: number;
  };
  instrument: string;
  profile: VisualAssessmentProfile;
  assessment: VisualAssessmentResult;
  summary: VisualAnalysisSummary;
  frames: VisualObservationFrame[];
}

const DEFAULT_CONFIDENCE_FLOOR = 0.5;
const DEFAULT_COVERAGE_FLOOR = 0.6;
const DEFAULT_OVERALL_PASS_FLOOR = 0.65;
const DEFAULT_REQUIREMENT_PASS_FLOOR = 0.55;
const MEDIAN_SCORE_WEIGHT = 0.8;
const GOOD_FRAME_SCORE_WEIGHT = 0.2;

function requirement(
  metricKey: string,
  label: string,
  weight: number,
  critical = false,
): VisualAssessmentRequirement {
  return { metricKey, label, weight, critical, passFloor: DEFAULT_REQUIREMENT_PASS_FLOOR };
}

function profile(
  instrument: string,
  skillSlug: string,
  title: string,
  requirements: readonly VisualAssessmentRequirement[],
): VisualAssessmentProfile {
  return {
    id: `${instrument}:${skillSlug}`,
    version: VISUAL_ASSESSMENT_VERSION,
    instrument,
    skillSlug,
    title,
    confidenceFloor: DEFAULT_CONFIDENCE_FLOOR,
    coverageFloor: DEFAULT_COVERAGE_FLOOR,
    overallPassFloor: DEFAULT_OVERALL_PASS_FLOOR,
    requirements,
  };
}

/**
 * MVP profiles are tied to shipped curriculum identities, but name only facts
 * the current image-space landmark reducers can observe.
 *
 * @spec OBS-ASSESS-001, OBS-ASSESS-002, OBS-ASSESS-003, OBS-ASSESS-010
 */
export const VISUAL_ASSESSMENT_PROFILES: readonly VisualAssessmentProfile[] = [
  profile("piano", "five-finger-pattern", "Five-Finger Pattern", [
    requirement("wrist_elevation", "Wrist elevation", 3, true),
    requirement("torso_lean", "Torso alignment", 1),
    requirement("shoulder_level", "Shoulder level", 1),
  ]),
  profile("guitar", "basic-strumming", "Basic Strumming", [
    requirement("neck_angle", "Neck angle", 2, true),
    requirement("strumming_arm", "Strumming arm", 2, true),
    requirement("torso_lean", "Torso alignment", 1),
  ]),
  profile("violin", "open-string-bow", "Open-String Bow", [
    requirement("scroll_height", "Scroll height", 2, true),
    requirement("bow_arm_elbow", "Bow-arm elbow", 2, true),
    requirement("chin_tilt", "Chin-rest angle", 1),
    requirement("torso_lean", "Torso alignment", 1),
    requirement("shoulder_level", "Shoulder level", 1),
  ]),
  profile("trumpet", "trumpet-orientation", "Trumpet Orientation", [
    requirement("head_tilt", "Head position", 2, true),
    requirement("elbow_lift", "Elbow lift", 2, true),
    requirement("elbow_symmetry", "Elbow symmetry", 1),
    requirement("torso_lean", "Torso alignment", 1),
    requirement("shoulder_level", "Shoulder level", 1),
  ]),
  profile("drums", "basic-strokes", "Basic Strokes", [
    requirement("wrist_height_symmetry", "Stick-height symmetry", 2, true),
    requirement("seat_posture", "Seated posture", 2, true),
    requirement("shoulder_level", "Shoulder level", 1),
  ]),
  profile("banjo", "banjo-strumming", "Banjo Strumming", [
    requirement("neck_angle", "Neck angle", 2, true),
    requirement("strumming_arm", "Strumming arm", 2, true),
    requirement("torso_lean", "Torso alignment", 1),
  ]),
];

function round(value: number, places = 2): number {
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
}

function median(values: readonly number[]): number {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  if (ordered.length % 2 === 1) return ordered[middle];
  return (ordered[middle - 1] + ordered[middle]) / 2;
}

/**
 * Full-window, skill-aware visual verdict. Missing evidence prevents a grade;
 * it never becomes either a zero or a pass.
 *
 * @spec OBS-ASSESS-004, OBS-ASSESS-005, OBS-ASSESS-006, OBS-ASSESS-007,
 * OBS-ASSESS-008, OBS-ASSESS-009, OBS-ASSESS-010, OBS-ASSESS-011, OBS-ASSESS-012
 */
export function assessVisualFrames(
  selectedProfile: VisualAssessmentProfile,
  inputFrames: readonly VisualObservationFrame[],
): VisualAssessmentResult {
  const frames = [...inputFrames].sort((left, right) => left.timestampMs - right.timestampMs);
  const highlights = collapseVisualHighlights(frames, selectedProfile.confidenceFloor);
  const totalFrameCount = frames.length;

  const requirements = selectedProfile.requirements.map((declared) => {
    const readings = frames.flatMap((item) =>
      item.metrics.filter(
        (reading) =>
          reading.key === declared.metricKey &&
          isCountableVisualMetric(reading, selectedProfile.confidenceFloor),
      ),
    );
    const countableFrameCount = readings.length;
    const coverage = totalFrameCount === 0 ? 0 : round(countableFrameCount / totalFrameCount);
    const hasEvidence = countableFrameCount > 0;
    const medianValue = hasEvidence ? round(median(readings.map((reading) => reading.value))) : null;
    const goodFrameRatio = hasEvidence
      ? round(readings.filter((reading) => reading.status === "good").length / countableFrameCount)
      : null;
    const score = medianValue === null || goodFrameRatio === null
      ? null
      : round((medianValue * MEDIAN_SCORE_WEIGHT) + (goodFrameRatio * GOOD_FRAME_SCORE_WEIGHT));
    const sufficient = score !== null && coverage >= selectedProfile.coverageFloor;
    let passState: VisualRequirementPassState;
    if (!sufficient) {
      passState = "insufficient_evidence";
    } else if (score >= declared.passFloor) {
      passState = "pass";
    } else {
      passState = "retry";
    }
    return {
      ...declared,
      coverage,
      countableFrameCount,
      totalFrameCount,
      medianValue,
      goodFrameRatio,
      score,
      passState,
      corrections: highlights.filter((highlight) => highlight.key === declared.metricKey),
    };
  });

  const evidenceCoverage = requirements.length === 0
    ? 0
    : Math.min(...requirements.map((item) => item.coverage));
  const sufficientEvidence = totalFrameCount > 0 && requirements.length > 0 && requirements.every(
    (item) => item.passState !== "insufficient_evidence",
  );
  const totalWeight = requirements.reduce((total, item) => total + item.weight, 0);
  let overallScore: number | null = null;
  let outcome: VisualAssessmentOutcome = "insufficient_evidence";
  if (sufficientEvidence && totalWeight > 0) {
    overallScore = round(
      requirements.reduce((total, item) => total + (item.score as number) * item.weight, 0) / totalWeight,
    );
    const criticalRequirementsPass = requirements.every(
      (item) => !item.critical || item.passState === "pass",
    );
    outcome = overallScore >= selectedProfile.overallPassFloor && criticalRequirementsPass ? "pass" : "retry";
  }

  return {
    profileId: selectedProfile.id,
    profileVersion: selectedProfile.version,
    instrument: selectedProfile.instrument,
    skillSlug: selectedProfile.skillSlug,
    skillTitle: selectedProfile.title,
    outcome,
    overallScore,
    evidenceCoverage: round(evidenceCoverage),
    thresholds: {
      confidenceFloor: selectedProfile.confidenceFloor,
      coverageFloor: selectedProfile.coverageFloor,
      overallPassFloor: selectedProfile.overallPassFloor,
    },
    requirements,
  };
}

/**
 * Portable local result containing only derived visual evidence.
 *
 * @spec CAP-VID-002, CAP-VID-004, OBS-TIME-005, OBS-TIME-006, OBS-ASSESS-014
 */
export function createVisualAssessmentExport(input: {
  fileName: string;
  durationMs: number;
  profile: VisualAssessmentProfile;
  frames: readonly VisualObservationFrame[];
}): VisualAssessmentExport {
  const frames = [...input.frames].sort((left, right) => left.timestampMs - right.timestampMs);
  return {
    schemaVersion: `${VISUAL_ANALYSIS_VERSION}+${input.profile.version}`,
    source: {
      kind: "selected-video",
      fileName: input.fileName,
      durationMs: Math.max(0, Math.round(input.durationMs)),
    },
    instrument: input.profile.instrument,
    profile: input.profile,
    assessment: assessVisualFrames(input.profile, frames),
    summary: summarizeVisualFrames(frames),
    frames,
  };
}

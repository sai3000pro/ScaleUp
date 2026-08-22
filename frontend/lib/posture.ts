/**
 * Posture metrics from MediaPipe Pose landmarks.
 *
 * Written from scratch. The reference implementation this project was pointed
 * at instantiates Pose, Hands, and FaceMesh and then calls geometry functions
 * that do not exist in any commit — its shipping "posture" score is the mean
 * brightness and Canny edge density of a single grayscale frame, which measures
 * the room rather than the player.
 *
 * Three rules govern everything here, and they are what separate an honest
 * metric from a confident wrong one:
 *
 * 1. **Every distance is normalised by body scale.** Otherwise leaning toward
 *    the camera changes the metric without the learner moving.
 * 2. **A landmark that was not seen is not a bad landmark.** MediaPipe reports
 *    a per-landmark `visibility`, which the reference code never reads once.
 *    A rule whose required landmarks are not visible reports `not_detected` and
 *    contributes nothing — a laptop webcam at a piano usually cannot see hips,
 *    so this is the common case, not the edge case.
 * 3. **No rule is built on `z`.** MediaPipe's depth is a weak relative
 *    estimate, not metric depth. Trumpet chin angle, piano bench distance, and
 *    violin bow straightness are depth-dominated, so they are omitted rather
 *    than approximated. A confident wrong posture correction is worse than
 *    silence.
 *
 * Every threshold below is an initial guess. They are versioned by
 * POSTURE_THRESHOLD_VERSION, the raw geometry is persisted alongside the score,
 * and `calibrateThresholds` shifts them per learner — because a threshold you
 * cannot retune is a threshold you can never find out is wrong.
 */

import type { Landmark, TechniqueMetric, TechniqueMetrics, TechniqueStatus } from "@/lib/technique";

export const POSTURE_VERSION = "posture-v1";
export const POSTURE_THRESHOLD_VERSION = "posture-thresholds-v1";

/** Below this a landmark counts as unseen. MediaPipe's own default gate. */
export const MIN_VISIBILITY = 0.5;
/** Below this fraction of frames with every required landmark, low confidence. */
export const MIN_METRIC_COVERAGE = 0.6;

// BlazePose 33-point indices, only the ones any rule actually uses.
export const NOSE = 0;
export const LEFT_EAR = 7;
export const RIGHT_EAR = 8;
export const LEFT_SHOULDER = 11;
export const RIGHT_SHOULDER = 12;
export const LEFT_ELBOW = 13;
export const RIGHT_ELBOW = 14;
export const LEFT_WRIST = 15;
export const RIGHT_WRIST = 16;
export const LEFT_HIP = 23;
export const RIGHT_HIP = 24;

export interface Band {
  /** Value at or better than this reads as `good`. */
  good: number;
  /** Value at or worse than this reads as `needs_attention` at full strength. */
  fail: number;
}

export interface PostureThresholds {
  [metricKey: string]: Band;
}

/**
 * Initial guesses, every one of them. Angles are degrees; ratios are fractions
 * of body scale. `target` semantics are encoded by the rule, not here.
 */
export const DEFAULT_THRESHOLDS: PostureThresholds = {
  torso_lean: { good: 8, fail: 20 },
  shoulder_level: { good: 5, fail: 14 },
  head_forward: { good: 0.12, fail: 0.3 },
  shoulder_tension: { good: 0.55, fail: 0.38 },
  scroll_height: { good: 0.1, fail: -0.1 },
  bow_arm_elbow: { good: 25, fail: 60 },
  chin_tilt: { good: 10, fail: 25 },
  neck_angle: { good: 12, fail: 30 },
  strumming_arm: { good: 20, fail: 50 },
  strum_shoulder_stability: { good: 0.015, fail: 0.05 },
  head_tilt: { good: 6, fail: 16 },
  elbow_lift: { good: 15, fail: 40 },
  elbow_symmetry: { good: 15, fail: 40 },
  seat_posture: { good: 8, fail: 25 },
  wrist_height_symmetry: { good: 0.08, fail: 0.2 },
  grip_openness: { good: 0.12, fail: 0.35 },
};

function clamp(value: number, lower: number, upper: number): number {
  if (value < lower) return lower;
  if (value > upper) return upper;
  return value;
}

/** Score a measurement where smaller is better, against its band. */
function scoreLowerBetter(raw: number, band: Band): number {
  if (band.fail <= band.good) return raw <= band.good ? 1 : 0;
  return clamp(1 - (raw - band.good) / (band.fail - band.good), 0, 1);
}

/** Score a measurement where larger is better, against its band. */
function scoreHigherBetter(raw: number, band: Band): number {
  if (band.good <= band.fail) return raw >= band.good ? 1 : 0;
  return clamp((raw - band.fail) / (band.good - band.fail), 0, 1);
}

export function visible(landmark: Landmark | undefined): boolean {
  return landmark !== undefined && (landmark.visibility ?? 0) >= MIN_VISIBILITY;
}

export function visibleEnough(pose: readonly Landmark[], indices: readonly number[]): boolean {
  return indices.every((index) => visible(pose[index]));
}

export function midpoint(first: Landmark, second: Landmark): Landmark {
  return {
    x: (first.x + second.x) / 2,
    y: (first.y + second.y) / 2,
    z: (first.z + second.z) / 2,
    visibility: Math.min(first.visibility ?? 1, second.visibility ?? 1),
  };
}

/**
 * A length to divide distances by, so metrics survive the learner sitting
 * closer to the camera. Shoulder-to-hip when the hips are visible; otherwise
 * shoulder width scaled by a typical torso ratio, which is less accurate but
 * available from the framing a laptop webcam actually gives.
 */
export function bodyScale(pose: readonly Landmark[]): number | null {
  if (visibleEnough(pose, [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP])) {
    const shoulders = midpoint(pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]);
    const hips = midpoint(pose[LEFT_HIP], pose[RIGHT_HIP]);
    const span = Math.abs(hips.y - shoulders.y);
    if (span > 1e-4) return span;
  }
  if (visibleEnough(pose, [LEFT_SHOULDER, RIGHT_SHOULDER])) {
    const width = Math.hypot(
      pose[LEFT_SHOULDER].x - pose[RIGHT_SHOULDER].x,
      pose[LEFT_SHOULDER].y - pose[RIGHT_SHOULDER].y,
    );
    if (width > 1e-4) return width * 1.5;
  }
  return null;
}

/** Interior angle at `vertex`, in degrees. */
export function angleDegrees(first: Landmark, vertex: Landmark, second: Landmark): number {
  const ax = first.x - vertex.x;
  const ay = first.y - vertex.y;
  const bx = second.x - vertex.x;
  const by = second.y - vertex.y;
  const dot = ax * bx + ay * by;
  const magnitude = Math.hypot(ax, ay) * Math.hypot(bx, by);
  if (magnitude < 1e-9) return 0;
  return (Math.acos(clamp(dot / magnitude, -1, 1)) * 180) / Math.PI;
}

/** Signed tilt of the line first→second against horizontal, in degrees. */
export function lineTiltDegrees(first: Landmark, second: Landmark): number {
  return (Math.atan2(second.y - first.y, second.x - first.x) * 180) / Math.PI;
}

/** Tilt of a line away from vertical, in degrees, unsigned. */
export function verticalTiltDegrees(top: Landmark, bottom: Landmark): number {
  return (Math.atan2(Math.abs(bottom.x - top.x), Math.abs(bottom.y - top.y)) * 180) / Math.PI;
}

/** Mean displacement of one landmark from its own average, in body-scale units. */
export function temporalStability(
  history: readonly (readonly Landmark[])[],
  index: number,
  scale: number,
): number | null {
  const seen = history.filter((frame) => visible(frame[index]));
  if (seen.length < 2 || scale <= 0) return null;
  const meanX = seen.reduce((total, frame) => total + frame[index].x, 0) / seen.length;
  const meanY = seen.reduce((total, frame) => total + frame[index].y, 0) / seen.length;
  const drift =
    seen.reduce((total, frame) => total + Math.hypot(frame[index].x - meanX, frame[index].y - meanY), 0) /
    seen.length;
  return drift / scale;
}

export interface RuleOutcome {
  value: number;
  raw: number;
  unit: "deg" | "ratio";
  explanation: string;
}

export interface PostureRule {
  key: string;
  requiredLandmarks: readonly number[];
  evaluate(
    pose: readonly Landmark[],
    history: readonly (readonly Landmark[])[],
    scale: number,
    thresholds: PostureThresholds,
  ): RuleOutcome | null;
}

function band(thresholds: PostureThresholds, key: string): Band {
  return thresholds[key] ?? DEFAULT_THRESHOLDS[key];
}

const torsoLean: PostureRule = {
  key: "torso_lean",
  requiredLandmarks: [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP],
  evaluate(pose, _history, _scale, thresholds) {
    const shoulders = midpoint(pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]);
    const hips = midpoint(pose[LEFT_HIP], pose[RIGHT_HIP]);
    const raw = verticalTiltDegrees(shoulders, hips);
    const value = scoreLowerBetter(raw, band(thresholds, "torso_lean"));
    return {
      value,
      raw,
      unit: "deg",
      explanation:
        value >= 0.7
          ? "Your torso is upright over your hips."
          : "You are leaning off your hips — stack your shoulders over them.",
    };
  },
};

const shoulderLevel: PostureRule = {
  key: "shoulder_level",
  requiredLandmarks: [LEFT_SHOULDER, RIGHT_SHOULDER],
  evaluate(pose, _history, _scale, thresholds) {
    const raw = Math.abs(lineTiltDegrees(pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]));
    const value = scoreLowerBetter(raw, band(thresholds, "shoulder_level"));
    return {
      value,
      raw,
      unit: "deg",
      explanation:
        value >= 0.7 ? "Your shoulders are level." : "One shoulder is riding higher than the other.",
    };
  },
};

const headForward: PostureRule = {
  key: "head_forward",
  requiredLandmarks: [NOSE, LEFT_SHOULDER, RIGHT_SHOULDER],
  evaluate(pose, _history, scale, thresholds) {
    const shoulders = midpoint(pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]);
    const raw = Math.abs(pose[NOSE].x - shoulders.x) / scale;
    const value = scoreLowerBetter(raw, band(thresholds, "head_forward"));
    return {
      value,
      raw,
      unit: "ratio",
      explanation:
        value >= 0.7 ? "Your head is centred over your shoulders." : "Your head is pushed out ahead of your shoulders.",
    };
  },
};

const shoulderTension: PostureRule = {
  key: "shoulder_tension",
  requiredLandmarks: [LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER],
  evaluate(pose, _history, scale, thresholds) {
    const ears = midpoint(pose[LEFT_EAR], pose[RIGHT_EAR]);
    const shoulders = midpoint(pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]);
    const raw = (shoulders.y - ears.y) / scale;
    const value = scoreHigherBetter(raw, band(thresholds, "shoulder_tension"));
    return {
      value,
      raw,
      unit: "ratio",
      explanation:
        value >= 0.7 ? "Your shoulders are down and relaxed." : "Your shoulders are creeping up toward your ears.",
    };
  },
};

const scrollHeight: PostureRule = {
  key: "scroll_height",
  requiredLandmarks: [LEFT_WRIST, LEFT_SHOULDER, RIGHT_SHOULDER],
  evaluate(pose, _history, scale, thresholds) {
    const shoulders = midpoint(pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]);
    // Image y grows downward, so a raised wrist gives a positive difference.
    const raw = (shoulders.y - pose[LEFT_WRIST].y) / scale;
    const value = scoreHigherBetter(raw, band(thresholds, "scroll_height"));
    return {
      value,
      raw,
      unit: "ratio",
      explanation: value >= 0.7 ? "The scroll is held up nicely." : "The scroll is drooping — lift the left hand.",
    };
  },
};

/** Angle rules whose target is a range rather than zero. */
function rangeRule(
  key: string,
  required: readonly number[],
  measure: (pose: readonly Landmark[], scale: number) => number,
  target: number,
  goodExplanation: string,
  badExplanation: string,
  unit: "deg" | "ratio" = "deg",
): PostureRule {
  return {
    key,
    requiredLandmarks: required,
    evaluate(pose, _history, scale, thresholds) {
      const raw = measure(pose, scale);
      const value = scoreLowerBetter(Math.abs(raw - target), band(thresholds, key));
      return {
        value,
        raw,
        unit,
        explanation: value >= 0.7 ? goodExplanation : badExplanation,
      };
    },
  };
}

const bowArmElbow = rangeRule(
  "bow_arm_elbow",
  [RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST],
  (pose) => angleDegrees(pose[RIGHT_SHOULDER], pose[RIGHT_ELBOW], pose[RIGHT_WRIST]),
  105,
  "Your bow arm is opening through a healthy range.",
  "Your bow elbow is locked or collapsed — aim for a right-ish angle mid-bow.",
);

// The one rule whose target is deliberately NOT zero: a violinist's head is
// supposed to tilt toward the chin rest. Scoring it as "keep level" would
// correct correct playing.
// @spec OBS-POSE-006
const chinTilt = rangeRule(
  "chin_tilt",
  [LEFT_EAR, RIGHT_EAR],
  (pose) => Math.abs(lineTiltDegrees(pose[LEFT_EAR], pose[RIGHT_EAR])),
  12,
  "Your head is settled onto the chin rest without clamping.",
  "Watch the head angle — either too flat off the chin rest, or clamped down onto it.",
);

const neckAngle = rangeRule(
  "neck_angle",
  [LEFT_WRIST, LEFT_SHOULDER],
  (pose) => Math.abs(lineTiltDegrees(pose[LEFT_SHOULDER], pose[LEFT_WRIST])),
  25,
  "The neck of the guitar is at a comfortable angle.",
  "The guitar neck is very flat or very steep — aim for a slight upward tilt.",
);

const strummingArm = rangeRule(
  "strumming_arm",
  [RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST],
  (pose) => angleDegrees(pose[RIGHT_SHOULDER], pose[RIGHT_ELBOW], pose[RIGHT_WRIST]),
  85,
  "Your strumming arm is hanging in a relaxed position.",
  "Your strumming elbow is very open or very closed.",
);

const headTilt: PostureRule = {
  key: "head_tilt",
  requiredLandmarks: [LEFT_EAR, RIGHT_EAR],
  evaluate(pose, _history, _scale, thresholds) {
    const raw = Math.abs(lineTiltDegrees(pose[LEFT_EAR], pose[RIGHT_EAR]));
    const value = scoreLowerBetter(raw, band(thresholds, "head_tilt"));
    return {
      value,
      raw,
      unit: "deg",
      explanation: value >= 0.7 ? "Your head is square to the instrument." : "Your head is tilted to one side.",
    };
  },
};

const elbowLift = rangeRule(
  "elbow_lift",
  [LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST],
  (pose) =>
    (angleDegrees(pose[LEFT_SHOULDER], pose[LEFT_ELBOW], pose[LEFT_WRIST]) +
      angleDegrees(pose[RIGHT_SHOULDER], pose[RIGHT_ELBOW], pose[RIGHT_WRIST])) /
    2,
  80,
  "Your elbows are carried away from your ribs.",
  "Your elbows are pinned to your ribs — let them hang out a little.",
);

const elbowSymmetry: PostureRule = {
  key: "elbow_symmetry",
  requiredLandmarks: [LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST],
  evaluate(pose, _history, _scale, thresholds) {
    const left = angleDegrees(pose[LEFT_SHOULDER], pose[LEFT_ELBOW], pose[LEFT_WRIST]);
    const right = angleDegrees(pose[RIGHT_SHOULDER], pose[RIGHT_ELBOW], pose[RIGHT_WRIST]);
    const raw = Math.abs(left - right);
    const value = scoreLowerBetter(raw, band(thresholds, "elbow_symmetry"));
    return {
      value,
      raw,
      unit: "deg",
      explanation: value >= 0.7 ? "Both arms are carried evenly." : "One arm is carried much higher than the other.",
    };
  },
};

const seatPosture = rangeRule(
  "seat_posture",
  [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP],
  (pose) =>
    verticalTiltDegrees(midpoint(pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]), midpoint(pose[LEFT_HIP], pose[RIGHT_HIP])),
  8,
  "You are sitting with a slight, workable forward lean.",
  "You are either bolt upright or hunched over the kit.",
);

const wristHeightSymmetry: PostureRule = {
  key: "wrist_height_symmetry",
  requiredLandmarks: [LEFT_WRIST, RIGHT_WRIST],
  evaluate(pose, _history, scale, thresholds) {
    const raw = Math.abs(pose[LEFT_WRIST].y - pose[RIGHT_WRIST].y) / scale;
    const value = scoreLowerBetter(raw, band(thresholds, "wrist_height_symmetry"));
    return {
      value,
      raw,
      unit: "ratio",
      explanation: value >= 0.7 ? "Both sticks are travelling at the same height." : "One stick is sitting much higher than the other.",
    };
  },
};

const strumShoulderStability: PostureRule = {
  key: "strum_shoulder_stability",
  requiredLandmarks: [RIGHT_SHOULDER],
  evaluate(pose, history, scale, thresholds) {
    void pose;
    const raw = temporalStability(history, RIGHT_SHOULDER, scale);
    if (raw === null) return null;
    const value = scoreLowerBetter(raw, band(thresholds, "strum_shoulder_stability"));
    return {
      value,
      raw,
      unit: "ratio",
      explanation:
        value >= 0.7
          ? "The strum is coming from your forearm, not your shoulder."
          : "Your whole shoulder is moving with the strum — let the forearm do it.",
    };
  },
};

const SHARED_RULES: readonly PostureRule[] = [torsoLean, shoulderLevel, headForward];

const FRETTED_AND_STRUMMED: readonly PostureRule[] = [
  ...SHARED_RULES,
  neckAngle,
  strummingArm,
  strumShoulderStability,
];

/**
 * One entry per shipped instrument. A missing entry is not a safe default: it
 * reaches SHARED_RULES and quietly drops every rule that makes an instrument's
 * technique its own, so a new curriculum must land a rule set here too.
 *
 * @spec OBS-POSE-005, OBS-POSE-013
 */
export const POSTURE_RULES: Record<string, readonly PostureRule[]> = {
  piano: [...SHARED_RULES, shoulderTension],
  violin: [...SHARED_RULES, scrollHeight, bowArmElbow, chinTilt],
  guitar: FRETTED_AND_STRUMMED,
  // Held, fretted and strummed like a guitar, so it is measured like one --
  // matching the evaluator routing in backend/app/evaluation/registry.py.
  banjo: FRETTED_AND_STRUMMED,
  trumpet: [...SHARED_RULES, headTilt, elbowLift, elbowSymmetry],
  drums: [seatPosture, shoulderLevel, wristHeightSymmetry],
};

function notDetected(key: string, reason: string): TechniqueMetric {
  return { key, value: 0, confidence: 0, status: "not_detected", explanation: reason, raw: null, unit: null };
}

/**
 * Reduce one frame (plus recent history) to per-metric readings.
 *
 * Coverage is measured over the history, not asserted: a rule whose landmarks
 * were visible in a third of recent frames is reported as `low_confidence`
 * rather than scored, because a posture judgement from a glimpse is a guess
 * wearing a number.
 */
// @spec OBS-POSE-001, OBS-POSE-002, OBS-POSE-003, OBS-POSE-004, OBS-POSE-008, OBS-POSE-009, OBS-POSE-010
export function reducePosture(
  instrument: string,
  pose: readonly Landmark[] | null,
  history: readonly (readonly Landmark[])[],
  thresholds: PostureThresholds = DEFAULT_THRESHOLDS,
): TechniqueMetrics {
  const rules = POSTURE_RULES[instrument] ?? SHARED_RULES;
  if (pose === null || pose.length < 33) {
    return {
      detected: false,
      version: POSTURE_VERSION,
      metrics: rules.map((rule) => notDetected(rule.key, "No one is in view of the camera.")),
    };
  }

  const scale = bodyScale(pose);
  if (scale === null) {
    return {
      detected: false,
      version: POSTURE_VERSION,
      metrics: rules.map((rule) => notDetected(rule.key, "The camera cannot see enough of you to judge posture.")),
    };
  }

  const metrics = rules.map((rule) => {
    if (!visibleEnough(pose, rule.requiredLandmarks)) {
      return notDetected(rule.key, "The camera cannot see the joints this check needs.");
    }
    const covered = history.filter((frame) => visibleEnough(frame, rule.requiredLandmarks)).length;
    const coverage = history.length === 0 ? 1 : covered / history.length;
    const outcome = rule.evaluate(pose, history, scale, thresholds);
    if (outcome === null) {
      return notDetected(rule.key, "Not enough frames yet for this check.");
    }
    const confidence = Math.round(clamp(coverage, 0, 1) * 100) / 100;
    let status: TechniqueStatus;
    if (confidence < MIN_METRIC_COVERAGE) {
      status = "low_confidence";
    } else if (outcome.value >= 0.7) {
      status = "good";
    } else {
      status = "needs_attention";
    }
    return {
      key: rule.key,
      value: Math.round(outcome.value * 100) / 100,
      confidence,
      status,
      explanation:
        status === "low_confidence" ? "You were only intermittently in view for this check." : outcome.explanation,
      raw: Math.round(outcome.raw * 1000) / 1000,
      unit: outcome.unit,
    };
  });

  return { detected: true, version: POSTURE_VERSION, metrics };
}

/**
 * Shift the default bands toward a learner's own captured baseline.
 *
 * Bodies and camera angles differ enough that a single set of numbers cannot
 * be right for everyone. The shift is clamped to half the band width so a
 * baseline captured while slouching cannot quietly make everything pass.
 */
// @spec OBS-POSE-007
export function calibrateThresholds(
  defaults: PostureThresholds,
  baseline: Record<string, number>,
): PostureThresholds {
  const calibrated: PostureThresholds = {};
  for (const [key, band] of Object.entries(defaults)) {
    const measured = baseline[key];
    if (measured === undefined || !Number.isFinite(measured)) {
      calibrated[key] = band;
    } else {
      const width = Math.abs(band.fail - band.good);
      const limit = width / 2;
      const shift = clamp(measured - band.good, -limit, limit);
      calibrated[key] = { good: band.good + shift, fail: band.fail + shift };
    }
  }
  return calibrated;
}

export type PoseVariant =
  | "upright"
  | "slouched"
  | "shoulders-uneven"
  | "occluded-hips"
  | "violin-good"
  | "violin-drooped";

/** Deterministic pose fixtures, mirroring `mockHandLandmarks` in technique.ts. */
export function mockPoseLandmarks(variant: PoseVariant, timeSeconds = 0): readonly Landmark[] {
  const breath = (seed: number) => 0.001 * Math.sin(timeSeconds * 2 + seed);
  const pose: Landmark[] = Array.from({ length: 33 }, (_, index) => ({
    x: 0.5 + breath(index),
    y: 0.5 + breath(index + 1),
    z: 0,
    visibility: 0.95,
  }));

  const hipVisibility = variant === "occluded-hips" ? 0.1 : 0.95;
  const leanX = variant === "slouched" ? 0.12 : 0;
  const shoulderY = 0.42;

  pose[NOSE] = { x: 0.5 + (variant === "slouched" ? 0.16 : 0.005), y: 0.22, z: 0, visibility: 0.95 };
  pose[LEFT_EAR] = { x: 0.46, y: variant.startsWith("violin") ? 0.235 : 0.22, z: 0, visibility: 0.95 };
  pose[RIGHT_EAR] = { x: 0.54, y: variant.startsWith("violin") ? 0.205 : 0.22, z: 0, visibility: 0.95 };
  pose[LEFT_SHOULDER] = {
    x: 0.4 + leanX,
    y: shoulderY + (variant === "shoulders-uneven" ? -0.05 : 0),
    z: 0,
    visibility: 0.95,
  };
  pose[RIGHT_SHOULDER] = { x: 0.6 + leanX, y: shoulderY, z: 0, visibility: 0.95 };
  pose[LEFT_HIP] = { x: 0.42, y: 0.72, z: 0, visibility: hipVisibility };
  pose[RIGHT_HIP] = { x: 0.58, y: 0.72, z: 0, visibility: hipVisibility };
  pose[LEFT_ELBOW] = { x: 0.34, y: 0.56, z: 0, visibility: 0.95 };
  pose[RIGHT_ELBOW] = { x: 0.68, y: 0.56, z: 0, visibility: 0.95 };
  pose[LEFT_WRIST] = {
    x: 0.36,
    y: variant === "violin-good" ? 0.34 : variant === "violin-drooped" ? 0.62 : 0.62,
    z: 0,
    visibility: 0.95,
  };
  pose[RIGHT_WRIST] = { x: 0.72, y: 0.62, z: 0, visibility: 0.95 };
  return pose;
}

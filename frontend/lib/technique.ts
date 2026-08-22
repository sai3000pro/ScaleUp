/**
 * Technique metrics derived from MediaPipe 21-point hand landmarks.
 *
 * Pure and deterministic: the reducer takes landmark arrays (from MediaPipe or
 * from the mock fixture) and returns explainable metrics. It never claims to
 * assess musical quality — it reports observable physical-form signals with a
 * status of `not_detected` / `low_confidence` / `needs_attention` / `good`,
 * and the UI exposes the confidence so the learner knows what to trust.
 *
 * Landmark indices (MediaPipe hand): 0 = wrist, 5/9/13/17 = finger bases (MCP),
 * 8/12/16/20 = finger tips, 4 = thumb tip. Image y grows downward.
 */

export interface Landmark {
  x: number;
  y: number;
  z: number;
  /**
   * MediaPipe's own per-landmark confidence that the point is present and not
   * occluded. Pose landmarks carry it; hand landmarks do not, which is why it
   * is optional. Reading it is the entire difference between an honest posture
   * metric and a confident one derived from a joint the camera never saw.
   */
  visibility?: number;
}

export type TechniqueStatus = "not_detected" | "low_confidence" | "needs_attention" | "good";

export interface TechniqueMetric {
  key: string;
  /** 0..1, higher is better. Meaning is per-metric; see `explanation`. */
  value: number;
  /** 0..1 — how much of the recent history the metric is based on. */
  confidence: number;
  status: TechniqueStatus;
  explanation: string;
  /**
   * The geometric quantity `value` was derived from — an angle in degrees, a
   * ratio of body scale. Persisted with the attempt, because a threshold that
   * cannot be retuned against real measurements is a threshold nobody can ever
   * find out is wrong.
   */
  raw?: number | null;
  unit?: string | null;
}

export interface TechniqueMetrics {
  detected: boolean;
  version: string;
  metrics: TechniqueMetric[];
}

export const TECHNIQUE_VERSION = "technique-v1";

const WRIST = 0;
const FINGER_BASES = [5, 9, 13, 17] as const;
export const HISTORY_SIZE = 12;
// A wrist that sits more than this (in normalized image units) below the line
// of the finger bases is reported as collapsed.
const COLLAPSED_WRIST_DELTA = 0.04;
// Normalized per-frame wrist movement above this reads as an unstable hand.
const STABILITY_JITTER_MAX = 0.015;
// Below this fraction of recent frames with a detected hand, metrics are
// low-confidence rather than trusted.
const MIN_COVERAGE = 0.5;

function clamp(value: number, lower: number, upper: number): number {
  if (value < lower) return lower;
  if (value > upper) return upper;
  return value;
}

function meanY(landmarks: Landmark[], indices: readonly number[]): number {
  let total = 0;
  for (const index of indices) {
    total += landmarks[index].y;
  }
  return total / indices.length;
}

export function wristElevationMetric(landmarks: Landmark[]): TechniqueMetric {
  const fingerBaseY = meanY(landmarks, FINGER_BASES);
  const wristY = landmarks[WRIST].y;
  const drop = wristY - fingerBaseY;
  const value = clamp(1 - (drop / COLLAPSED_WRIST_DELTA), 0, 1);

  let status: TechniqueStatus;
  let explanation: string;
  if (drop > COLLAPSED_WRIST_DELTA) {
    status = "needs_attention";
    explanation = "Wrist is sitting below the finger line — lift it so the hand stays level with the keys.";
  } else if (value >= 0.7) {
    status = "good";
    explanation = "Wrist elevation is level and relaxed.";
  } else {
    status = "needs_attention";
    explanation = "Wrist is drifting low — keep it level with the finger bases.";
  }
  return { key: "wrist_elevation", value: Math.round(value * 100) / 100, confidence: 1, status, explanation };
}

export function handStabilityMetric(history: Landmark[][]): TechniqueMetric {
  if (history.length < 2) {
    return {
      key: "hand_stability",
      value: 0,
      confidence: 0,
      status: "low_confidence",
      explanation: "Not enough frames to judge hand stability yet.",
    };
  }

  let meanX = 0;
  let meanYValue = 0;
  for (const frame of history) {
    meanX += frame[WRIST].x;
    meanYValue += frame[WRIST].y;
  }
  meanX /= history.length;
  meanYValue /= history.length;

  let totalDistance = 0;
  for (const frame of history) {
    totalDistance += Math.hypot(frame[WRIST].x - meanX, frame[WRIST].y - meanYValue);
  }
  const jitter = totalDistance / history.length;
  const value = clamp(1 - jitter / STABILITY_JITTER_MAX, 0, 1);
  const coverage = history.length / HISTORY_SIZE;
  const confidence = clamp(coverage, 0, 1);

  let status: TechniqueStatus;
  let explanation: string;
  if (confidence < MIN_COVERAGE) {
    status = "low_confidence";
    explanation = "The hand was only seen intermittently — hold it in view.";
  } else if (value >= 0.7) {
    status = "good";
    explanation = "Hand position is steady while you play.";
  } else {
    status = "needs_attention";
    explanation = "The hand is moving around more than a relaxed position needs.";
  }
  return {
    key: "hand_stability",
    value: Math.round(value * 100) / 100,
    confidence: Math.round(confidence * 100) / 100,
    status,
    explanation,
  };
}

// @spec OBS-HAND-001, OBS-HAND-002, OBS-HAND-003, OBS-HAND-004
export function reduceTechnique(
  landmarks: Landmark[] | null,
  history: Landmark[][],
): TechniqueMetrics {
  if (landmarks === null || landmarks.length < 21) {
    return {
      detected: false,
      version: TECHNIQUE_VERSION,
      metrics: [
        {
          key: "wrist_elevation",
          value: 0,
          confidence: 0,
          status: "not_detected",
          explanation: "No hand is in view.",
        },
        {
          key: "hand_stability",
          value: 0,
          confidence: 0,
          status: "not_detected",
          explanation: "No hand is in view.",
        },
      ],
    };
  }

  const wrist = wristElevationMetric(landmarks);
  const stability = handStabilityMetric(history);
  // The wrist metric is computed from a single frame, so its confidence is the
  // same coverage signal the stability metric uses.
  const confidence = stability.confidence;
  const wristWithConfidence: TechniqueMetric = {
    ...wrist,
    confidence,
    status: confidence < MIN_COVERAGE ? "low_confidence" : wrist.status,
  };
  return { detected: true, version: TECHNIQUE_VERSION, metrics: [wristWithConfidence, stability] };
}

/**
 * Deterministic mock hand landmarks for demos and tests without a camera.
 *
 * `good` holds the wrist above the finger bases; `collapsed` drops it below.
 * Both breathe slightly over time so the stability metric sees realistic
 * (small) jitter.
 */
export function mockHandLandmarks(variant: "good" | "collapsed", timeSeconds: number): Landmark[] {
  const breath = (seed: number) => 0.002 * Math.sin(timeSeconds * 2 + seed);
  const wristY = variant === "collapsed" ? 0.62 : 0.5;
  const baseY = variant === "collapsed" ? 0.56 : 0.58;
  const landmarks: Landmark[] = [];

  landmarks[WRIST] = { x: 0.5 + breath(1), y: wristY + breath(2), z: 0 };

  for (let index = 1; index < 21; index += 1) {
    let y: number;
    if (FINGER_BASES.includes(index as (typeof FINGER_BASES)[number])) {
      y = baseY + breath(index);
    } else if (index % 4 === 0) {
      y = baseY - 0.18 + breath(index); // finger tips
    } else if (index === 4) {
      y = baseY - 0.05 + breath(index); // thumb tip
    } else {
      y = baseY - 0.09 + breath(index);
    }
    const xSpread = 0.08 * (index % 2 === 0 ? 1 : -1);
    landmarks[index] = { x: 0.5 + xSpread + breath(index + 10), y, z: 0 };
  }

  return landmarks;
}

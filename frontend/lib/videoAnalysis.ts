import {
  POSTURE_THRESHOLD_VERSION,
  reducePosture,
} from "@/lib/posture";
import {
  reduceTechnique,
  type Landmark,
  type TechniqueMetric,
} from "@/lib/technique";

export const VISUAL_ANALYSIS_VERSION = "visual-analysis-v1";
export const MIN_COUNTABLE_CONFIDENCE = 0.5;
export const MAX_VISUAL_FRAMES = 9000;
const HIGHLIGHT_GAP_MS = 600;

export interface VisualReducerVersions {
  hand: string;
  posture: string;
  thresholds: string;
}

export interface VisualObservationFrame {
  timestampMs: number;
  metrics: TechniqueMetric[];
  versions: VisualReducerVersions;
}

export interface VisualMetricSummary {
  key: string;
  medianValue: number;
  meanConfidence: number;
  goodFrameRatio: number;
  measuredFrameCount: number;
  explanation: string;
}

export interface VisualHighlight {
  key: string;
  startMs: number;
  endMs: number;
  confidence: number;
  explanation: string;
}

export interface VisualAnalysisSummary {
  version: string;
  frameCount: number;
  measuredFrameCount: number;
  unmeasured: boolean;
  metrics: VisualMetricSummary[];
  highlights: VisualHighlight[];
}

export interface SelectedVideoDescriptor {
  name: string;
  type: string;
}

function uniqueMetrics(groups: readonly (readonly TechniqueMetric[])[]): TechniqueMetric[] {
  const byKey = new Map<string, TechniqueMetric>();
  for (const group of groups) {
    for (const metric of group) {
      byKey.set(metric.key, metric);
    }
  }
  return [...byKey.values()];
}

/**
 * The pure seam between MediaPipe and every visual consumer. Live camera and
 * selected video supply the same landmarks and histories here, so their
 * feedback cannot drift into separate implementations.
 *
 * @spec CAP-VID-003, CAP-VID-004, OBS-TIME-001, OBS-TIME-005
 */
export function reduceVisualLandmarkFrame(input: {
  instrument: string;
  timestampMs: number;
  hand: Landmark[] | null;
  pose: Landmark[] | null;
  handHistory: Landmark[][];
  poseHistory: Landmark[][];
}): VisualObservationFrame {
  const handMetrics = reduceTechnique(input.hand, input.handHistory);
  const postureMetrics = reducePosture(input.instrument, input.pose, input.poseHistory);
  return {
    timestampMs: Math.max(0, Math.round(input.timestampMs)),
    metrics: uniqueMetrics([handMetrics.metrics, postureMetrics.metrics]),
    versions: {
      hand: handMetrics.version,
      posture: postureMetrics.version,
      thresholds: POSTURE_THRESHOLD_VERSION,
    },
  };
}

/** @spec CAP-VID-001 */
export function isSupportedSelectedVideo(file: SelectedVideoDescriptor): boolean {
  const mp4Name = file.name.toLowerCase().endsWith(".mp4");
  const mp4Type = file.type === "" || file.type === "video/mp4";
  return mp4Name && mp4Type;
}

/**
 * Keep enough observations for thirty minutes at the five-hertz adapter
 * cadence while placing a hard ceiling on browser memory for unusually long
 * files.
 *
 * @spec OBS-RED-003, OBS-TIME-001
 */
export function appendVisualFrame(
  frames: readonly VisualObservationFrame[],
  frame: VisualObservationFrame,
  limit = MAX_VISUAL_FRAMES,
): VisualObservationFrame[] {
  const boundedLimit = Math.max(1, Math.floor(limit));
  return [...frames, frame].slice(-boundedLimit);
}

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

export function isCountableVisualMetric(metric: TechniqueMetric, confidenceFloor = MIN_COUNTABLE_CONFIDENCE): boolean {
  return (
    metric.confidence >= confidenceFloor &&
    (metric.status === "good" || metric.status === "needs_attention")
  );
}

export function collapseVisualHighlights(
  inputFrames: readonly VisualObservationFrame[],
  confidenceFloor = MIN_COUNTABLE_CONFIDENCE,
): VisualHighlight[] {
  const frames = [...inputFrames].sort((left, right) => left.timestampMs - right.timestampMs);
  const highlights: VisualHighlight[] = [];
  for (const frame of frames) {
    for (const metric of frame.metrics) {
      if (metric.status === "needs_attention" && metric.confidence >= confidenceFloor) {
        const previous = highlights[highlights.length - 1];
        if (
          previous !== undefined &&
          previous.key === metric.key &&
          frame.timestampMs - previous.endMs <= HIGHLIGHT_GAP_MS
        ) {
          previous.endMs = frame.timestampMs;
          previous.confidence = round((previous.confidence + metric.confidence) / 2);
          previous.explanation = metric.explanation;
        } else {
          highlights.push({
            key: metric.key,
            startMs: frame.timestampMs,
            endMs: frame.timestampMs,
            confidence: round(metric.confidence),
            explanation: metric.explanation,
          });
        }
      }
    }
  }
  return highlights;
}

/**
 * Pure reduction over timestamped, already-derived visual observations.
 * Missing and low-confidence readings remain evidence about visibility but do
 * not become zero-valued technique scores.
 *
 * @spec OBS-TIME-001, OBS-TIME-002, OBS-TIME-003, OBS-TIME-004, OBS-TIME-006
 */
export function summarizeVisualFrames(inputFrames: readonly VisualObservationFrame[]): VisualAnalysisSummary {
  const frames = [...inputFrames].sort((left, right) => left.timestampMs - right.timestampMs);
  const measuredFrameCount = frames.filter((frame) => frame.metrics.some((metric) => isCountableVisualMetric(metric))).length;
  const byKey = new Map<string, TechniqueMetric[]>();

  for (const frame of frames) {
    for (const metric of frame.metrics) {
      if (isCountableVisualMetric(metric)) {
        const readings = byKey.get(metric.key) ?? [];
        readings.push(metric);
        byKey.set(metric.key, readings);
      }
    }
  }

  const metrics = [...byKey.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, readings]) => ({
      key,
      medianValue: round(median(readings.map((reading) => reading.value))),
      meanConfidence: round(
        readings.reduce((total, reading) => total + reading.confidence, 0) / readings.length,
      ),
      goodFrameRatio: round(readings.filter((reading) => reading.status === "good").length / readings.length),
      measuredFrameCount: readings.length,
      explanation: readings[readings.length - 1].explanation,
    }));

  return {
    version: VISUAL_ANALYSIS_VERSION,
    frameCount: frames.length,
    measuredFrameCount,
    unmeasured: metrics.length === 0,
    metrics,
    highlights: collapseVisualHighlights(frames),
  };
}

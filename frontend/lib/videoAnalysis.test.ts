import { describe, expect, it } from "vitest";

import { mockPoseLandmarks } from "@/lib/posture";
import { HISTORY_SIZE, mockHandLandmarks } from "@/lib/technique";
import {
  appendVisualFrame,
  isSupportedSelectedVideo,
  reduceVisualLandmarkFrame,
  summarizeVisualFrames,
  type VisualObservationFrame,
} from "@/lib/videoAnalysis";
import type { TechniqueMetric } from "@/lib/technique";

function metric(
  key: string,
  value: number,
  status: TechniqueMetric["status"],
  confidence = 0.9,
): TechniqueMetric {
  return {
    key,
    value,
    confidence,
    status,
    explanation: `${key}:${status}`,
    raw: value * 10,
    unit: "ratio",
  };
}

function frame(timestampMs: number, metrics: TechniqueMetric[]): VisualObservationFrame {
  return {
    timestampMs,
    metrics,
    versions: {
      hand: "technique-v1",
      posture: "posture-v1",
      thresholds: "posture-thresholds-v1",
    },
  };
}

// @spec OBS-TIME-001, OBS-TIME-002, OBS-TIME-003, OBS-TIME-004, OBS-TIME-006
describe("selected-video visual summaries", () => {
  it("reports an empty analysis as unmeasured instead of a zero score", () => {
    const summary = summarizeVisualFrames([]);

    expect(summary.unmeasured).toBe(true);
    expect(summary.frameCount).toBe(0);
    expect(summary.measuredFrameCount).toBe(0);
    expect(summary.metrics).toEqual([]);
    expect(summary.highlights).toEqual([]);
  });

  it("excludes not-detected and low-confidence readings from metric values", () => {
    const summary = summarizeVisualFrames([
      frame(0, [metric("wrist_elevation", 0, "not_detected", 0)]),
      frame(200, [metric("wrist_elevation", 0.1, "low_confidence", 0.2)]),
      frame(400, [metric("wrist_elevation", 0.8, "good")]),
    ]);

    expect(summary.unmeasured).toBe(false);
    expect(summary.measuredFrameCount).toBe(1);
    expect(summary.metrics).toEqual([
      expect.objectContaining({
        key: "wrist_elevation",
        medianValue: 0.8,
        meanConfidence: 0.9,
        goodFrameRatio: 1,
        measuredFrameCount: 1,
      }),
    ]);
  });

  it("uses the median, mean confidence, and good-frame ratio", () => {
    const summary = summarizeVisualFrames([
      frame(0, [metric("hand_stability", 0.9, "good", 1)]),
      frame(200, [metric("hand_stability", 0.2, "needs_attention", 0.8)]),
      frame(400, [metric("hand_stability", 0.7, "good", 0.9)]),
    ]);

    expect(summary.metrics[0]).toEqual(
      expect.objectContaining({
        medianValue: 0.7,
        meanConfidence: 0.9,
        goodFrameRatio: 0.67,
        measuredFrameCount: 3,
      }),
    );
  });

  it("collapses adjacent corrections and starts a new highlight after a gap", () => {
    const summary = summarizeVisualFrames([
      frame(1000, [metric("torso_lean", 0.3, "needs_attention")]),
      frame(1200, [metric("torso_lean", 0.25, "needs_attention")]),
      frame(1400, [metric("torso_lean", 0.2, "needs_attention")]),
      frame(3000, [metric("torso_lean", 0.35, "needs_attention")]),
    ]);

    expect(summary.highlights).toHaveLength(2);
    expect(summary.highlights[0]).toEqual(
      expect.objectContaining({ key: "torso_lean", startMs: 1000, endMs: 1400 }),
    );
    expect(summary.highlights[1]).toEqual(
      expect.objectContaining({ key: "torso_lean", startMs: 3000, endMs: 3000 }),
    );
  });

  it("is deterministic regardless of input frame ordering", () => {
    const frames = [
      frame(400, [metric("wrist_elevation", 0.8, "good")]),
      frame(0, [metric("wrist_elevation", 0.2, "needs_attention")]),
      frame(200, [metric("wrist_elevation", 0.6, "good")]),
    ];

    expect(summarizeVisualFrames(frames)).toEqual(summarizeVisualFrames([...frames].reverse()));
  });

  it("bounds retained observations for long selected videos", () => {
    const frames = [frame(0, []), frame(200, [])];
    expect(appendVisualFrame(frames, frame(400, []), 2).map((item) => item.timestampMs)).toEqual([200, 400]);
  });
});

// @spec CAP-VID-001
describe("selected-video validation", () => {
  it("accepts MP4 files even when the browser omits the MIME type", () => {
    expect(isSupportedSelectedVideo({ name: "practice.MP4", type: "" })).toBe(true);
    expect(isSupportedSelectedVideo({ name: "practice.mp4", type: "video/mp4" })).toBe(true);
  });

  it("rejects renamed or unsupported media", () => {
    expect(isSupportedSelectedVideo({ name: "practice.webm", type: "video/webm" })).toBe(false);
    expect(isSupportedSelectedVideo({ name: "practice.mp4", type: "video/quicktime" })).toBe(false);
  });
});

// @spec CAP-VID-003, CAP-VID-004, OBS-TIME-001, OBS-TIME-005
describe("shared live and selected-video visual reduction", () => {
  it("combines hand and body observations with media time and reducer versions", () => {
    const handHistory = Array.from({ length: HISTORY_SIZE }, (_, index) => mockHandLandmarks("good", index / 5));
    const poseHistory = Array.from({ length: HISTORY_SIZE }, (_, index) => [...mockPoseLandmarks("upright", index / 5)]);
    const result = reduceVisualLandmarkFrame({
      instrument: "piano",
      timestampMs: 1234.4,
      hand: handHistory[handHistory.length - 1],
      pose: poseHistory[poseHistory.length - 1],
      handHistory,
      poseHistory,
    });

    expect(result.timestampMs).toBe(1234);
    expect(result.metrics.map((item) => item.key)).toEqual(
      expect.arrayContaining(["wrist_elevation", "hand_stability", "torso_lean", "shoulder_tension"]),
    );
    expect(result.versions).toEqual({
      hand: "technique-v1",
      posture: "posture-v1",
      thresholds: "posture-thresholds-v1",
    });
    expect(JSON.stringify(result)).not.toMatch(/landmarks|videoBytes|audio|pitch|rhythm|musicxml|dtw/i);
  });
});

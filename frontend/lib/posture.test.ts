import { describe, expect, it } from "vitest";

import {
  DEFAULT_THRESHOLDS,
  LEFT_HIP,
  LEFT_SHOULDER,
  POSTURE_RULES,
  RIGHT_HIP,
  RIGHT_SHOULDER,
  angleDegrees,
  bodyScale,
  calibrateThresholds,
  mockPoseLandmarks,
  reducePosture,
} from "@/lib/posture";
import type { Landmark } from "@/lib/technique";

function metric(instrument: string, variant: Parameters<typeof mockPoseLandmarks>[0], key: string) {
  const pose = mockPoseLandmarks(variant);
  const history = Array.from({ length: 12 }, () => pose);
  const result = reducePosture(instrument, pose, history);
  const found = result.metrics.find((item) => item.key === key);
  if (found === undefined) throw new Error(`no metric ${key} for ${instrument}`);
  return found;
}

describe("posture geometry", () => {
  it("measures an interior angle", () => {
    const vertex: Landmark = { x: 0, y: 0, z: 0, visibility: 1 };
    const right: Landmark = { x: 1, y: 0, z: 0, visibility: 1 };
    const up: Landmark = { x: 0, y: 1, z: 0, visibility: 1 };
    expect(angleDegrees(right, vertex, up)).toBeCloseTo(90, 5);
  });

  it("is invariant to how close the learner sits to the camera", () => {
    // The property the reference implementation lacks entirely: without scale
    // normalisation, leaning in changes every metric without the learner moving.
    const pose = mockPoseLandmarks("upright");
    const scaled = pose.map((landmark) => ({ ...landmark, x: landmark.x * 0.5, y: landmark.y * 0.5 }));
    const near = reducePosture("piano", pose, [pose]);
    const far = reducePosture("piano", scaled, [scaled]);
    expect(far.metrics.map((item) => item.value)).toEqual(near.metrics.map((item) => item.value));
  });

  it("falls back to shoulder width when the hips are not visible", () => {
    const pose = mockPoseLandmarks("occluded-hips");
    expect(bodyScale(pose)).not.toBeNull();
  });
});

describe("honest reporting", () => {
  it("reports a rule as not_detected rather than failing it", () => {
    // A laptop webcam at a piano usually cannot see hips. Scoring that as bad
    // posture tells a learner their playing is wrong because their camera is low.
    const reading = metric("piano", "occluded-hips", "torso_lean");
    expect(reading.status).toBe("not_detected");
    expect(reading.confidence).toBe(0);
    expect(reading.value).toBe(0);
  });

  it("reports low confidence when the learner was only intermittently in view", () => {
    const good = mockPoseLandmarks("upright");
    const hidden = good.map((landmark) => ({ ...landmark, visibility: 0.1 }));
    const history = [good, hidden, hidden, hidden, hidden, hidden];
    const result = reducePosture("piano", good, history);
    expect(result.metrics.every((item) => item.status === "low_confidence" || item.status === "not_detected")).toBe(
      true,
    );
  });

  it("detects nothing when nobody is in frame", () => {
    const result = reducePosture("piano", null, []);
    expect(result.detected).toBe(false);
    expect(result.metrics.every((item) => item.status === "not_detected")).toBe(true);
  });

  it("keeps the raw geometry so thresholds can be retuned later", () => {
    const reading = metric("piano", "upright", "shoulder_level");
    expect(reading.raw).not.toBeNull();
    expect(reading.unit).toBe("deg");
  });
});

describe("rules", () => {
  it("passes an upright torso and fails a slouched one", () => {
    expect(metric("piano", "upright", "torso_lean").status).toBe("good");
    expect(metric("piano", "slouched", "torso_lean").value).toBeLessThan(
      metric("piano", "upright", "torso_lean").value,
    );
  });

  it("notices an uneven shoulder line", () => {
    expect(metric("piano", "upright", "shoulder_level").status).toBe("good");
    expect(metric("piano", "shoulders-uneven", "shoulder_level").status).toBe("needs_attention");
  });

  it("scores a lifted violin scroll above a drooping one", () => {
    expect(metric("violin", "violin-good", "scroll_height").value).toBeGreaterThan(
      metric("violin", "violin-drooped", "scroll_height").value,
    );
  });

  it("wants a violin head tilt rather than a level one", () => {
    // The one rule whose target is deliberately not zero: a violinist's head is
    // supposed to tilt onto the chin rest, so "keep level" would correct
    // correct playing.
    expect(metric("violin", "violin-good", "chin_tilt").value).toBeGreaterThan(
      metric("violin", "upright", "chin_tilt").value,
    );
  });

  it("gives every instrument its own rule set", () => {
    for (const instrument of ["piano", "violin", "guitar", "trumpet", "drums"]) {
      expect(POSTURE_RULES[instrument].length).toBeGreaterThan(0);
    }
    expect(POSTURE_RULES.violin.map((rule) => rule.key)).toContain("bow_arm_elbow");
    expect(POSTURE_RULES.drums.map((rule) => rule.key)).toContain("seat_posture");
    expect(POSTURE_RULES.piano.map((rule) => rule.key)).not.toContain("bow_arm_elbow");
  });

  it("builds no rule on the depth axis", () => {
    // MediaPipe z is a weak relative estimate, not metric depth. A rule that
    // reads it would produce a confident number from noise.
    const pose = mockPoseLandmarks("upright");
    const withDepth = pose.map((landmark) => ({ ...landmark, z: landmark.z + 0.4 }));
    expect(reducePosture("piano", withDepth, [withDepth]).metrics).toEqual(
      reducePosture("piano", pose, [pose]).metrics,
    );
  });
});

describe("calibration", () => {
  it("shifts a band toward the learner's own baseline", () => {
    const calibrated = calibrateThresholds(DEFAULT_THRESHOLDS, { shoulder_level: 8 });
    expect(calibrated.shoulder_level.good).toBeGreaterThan(DEFAULT_THRESHOLDS.shoulder_level.good);
  });

  it("clamps a wild baseline so nothing can be calibrated into always passing", () => {
    const calibrated = calibrateThresholds(DEFAULT_THRESHOLDS, { shoulder_level: 900 });
    const width = Math.abs(DEFAULT_THRESHOLDS.shoulder_level.fail - DEFAULT_THRESHOLDS.shoulder_level.good);
    expect(calibrated.shoulder_level.good).toBeLessThanOrEqual(DEFAULT_THRESHOLDS.shoulder_level.good + width / 2);
  });

  it("leaves bands alone when there is no baseline for them", () => {
    expect(calibrateThresholds(DEFAULT_THRESHOLDS, {})).toEqual(DEFAULT_THRESHOLDS);
  });
});

describe("body scale", () => {
  it("is null when neither hips nor shoulders are visible", () => {
    const pose = mockPoseLandmarks("upright").map((landmark, index) =>
      [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP].includes(index)
        ? { ...landmark, visibility: 0 }
        : landmark,
    );
    expect(bodyScale(pose)).toBeNull();
  });
});

describe("rule-set coverage", () => {
  // Every shipped curriculum, mirrored from backend/app/curricula/*.json. An
  // instrument added there without an entry here would silently receive the
  // three shared rules and none of the ones that make its technique its own.
  const SHIPPED = ["piano", "guitar", "violin", "trumpet", "drums", "banjo"];

  // @spec OBS-POSE-013
  it("declares a rule set for every shipped instrument", () => {
    const missing = SHIPPED.filter((instrument) => POSTURE_RULES[instrument] === undefined);
    expect(missing).toEqual([]);
  });

  // @spec OBS-POSE-005, OBS-POSE-013
  it("gives the banjo the rules its technique actually needs", () => {
    const banjo = (POSTURE_RULES.banjo ?? []).map((rule) => rule.key);
    // It is strummed and fretted, so it is measured the way a guitar is.
    expect(banjo).toEqual((POSTURE_RULES.guitar ?? []).map((rule) => rule.key));
  });
});

import { describe, expect, it } from "vitest";

import type { TechniqueMetric } from "@/lib/technique";
import type { VisualObservationFrame } from "@/lib/videoAnalysis";
import {
  VISUAL_ASSESSMENT_PROFILES,
  assessVisualFrames,
  createVisualAssessmentExport,
  type VisualAssessmentProfile,
} from "@/lib/visualAssessment";

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

function profile(instrument = "piano"): VisualAssessmentProfile {
  const found = VISUAL_ASSESSMENT_PROFILES.find((candidate) => candidate.instrument === instrument);
  if (found === undefined) throw new Error(`Missing profile for ${instrument}`);
  return found;
}

function goodFrames(selected: VisualAssessmentProfile, count = 10): VisualObservationFrame[] {
  return Array.from({ length: count }, (_, index) =>
    frame(
      index * 200,
      selected.requirements.map((requirement) => metric(requirement.metricKey, 0.9, "good")),
    ),
  );
}

// @spec OBS-ASSESS-001, OBS-ASSESS-002, OBS-ASSESS-003, OBS-ASSESS-010
describe("visual assessment profiles", () => {
  it("declares one explicit curriculum skill profile for every shipped instrument", () => {
    expect(VISUAL_ASSESSMENT_PROFILES.map(({ instrument, skillSlug }) => [instrument, skillSlug])).toEqual([
      ["piano", "five-finger-pattern"],
      ["guitar", "basic-strumming"],
      ["violin", "open-string-bow"],
      ["trumpet", "trumpet-orientation"],
      ["drums", "basic-strokes"],
      ["banjo", "banjo-strumming"],
    ]);

    for (const selected of VISUAL_ASSESSMENT_PROFILES) {
      expect(selected.id).toBeTruthy();
      expect(selected.version).toBe("visual-assessment-v2");
      expect(selected.requirements.length).toBeGreaterThan(0);
      expect(selected.requirements.every((requirement) => requirement.weight > 0)).toBe(true);
    }
    expect(profile("piano").requirements.map((requirement) => requirement.metricKey)).not.toContain("hand_stability");
    expect(profile("guitar").requirements.map((requirement) => requirement.metricKey)).not.toContain("strum_shoulder_stability");
    expect(profile("banjo").requirements.map((requirement) => requirement.metricKey)).not.toContain("strum_shoulder_stability");
  });

  it("does not let undeclared diagnostic metrics change a skill verdict", () => {
    const selected = profile();
    const frames = goodFrames(selected).map((item) => ({
      ...item,
      metrics: [...item.metrics, metric("unrelated_metric", 0, "needs_attention")],
    }));

    expect(assessVisualFrames(selected, frames).outcome).toBe("pass");
    expect(assessVisualFrames(selected, frames).requirements.some((item) => item.metricKey === "unrelated_metric")).toBe(false);
  });
});

// @spec OBS-ASSESS-004, OBS-ASSESS-005, OBS-ASSESS-006, OBS-ASSESS-008, OBS-ASSESS-009
describe("visual assessment aggregation", () => {
  it("passes a consistently good take and exposes its complete aggregate", () => {
    const selected = profile();
    const result = assessVisualFrames(selected, goodFrames(selected));

    expect(result.outcome).toBe("pass");
    expect(result.overallScore).toBe(0.92);
    expect(result.evidenceCoverage).toBe(1);
    expect(result.requirements.every((requirement) => requirement.passState === "pass")).toBe(true);
    expect(result.requirements[0]).toEqual(
      expect.objectContaining({
        countableFrameCount: 10,
        totalFrameCount: 10,
        medianValue: 0.9,
        goodFrameRatio: 1,
        score: 0.92,
      }),
    );
  });

  it("does not let one bad frame override an otherwise good take", () => {
    const selected = profile();
    const frames = goodFrames(selected);
    const key = selected.requirements[0].metricKey;
    frames[4] = frame(
      frames[4].timestampMs,
      selected.requirements.map((requirement) =>
        requirement.metricKey === key ? metric(key, 0.1, "needs_attention") : metric(requirement.metricKey, 0.9, "good"),
      ),
    );

    const result = assessVisualFrames(selected, frames);
    expect(result.outcome).toBe("pass");
    expect(result.requirements[0].goodFrameRatio).toBe(0.9);
    expect(result.requirements[0].corrections).toHaveLength(1);
  });

  it("does not double-penalise a borderline critical metric when the rest of the take is strong", () => {
    const selected = profile();
    const criticalKey = selected.requirements.find((requirement) => requirement.critical)?.metricKey;
    if (criticalKey === undefined) throw new Error("Fixture profile requires a critical metric");
    const frames = goodFrames(selected).map((item) => ({
      ...item,
      metrics: item.metrics.map((reading) =>
        reading.key === criticalKey ? metric(criticalKey, 0.69, "needs_attention") : reading,
      ),
    }));

    const result = assessVisualFrames(selected, frames);
    expect(result.requirements.find((requirement) => requirement.metricKey === criticalKey)?.score).toBe(0.55);
    expect(result.outcome).toBe("pass");
  });

  it("returns retry when a critical requirement misses its floor despite a passing overall score", () => {
    const selected = profile();
    const criticalKey = selected.requirements.find((requirement) => requirement.critical)?.metricKey;
    if (criticalKey === undefined) throw new Error("Fixture profile requires a critical metric");
    const frames = goodFrames(selected).map((item, index) => ({
      ...item,
      metrics: item.metrics.map((reading) =>
        reading.key === criticalKey && index < 7 ? metric(criticalKey, 0.6, "needs_attention") : reading,
      ),
    }));

    const result = assessVisualFrames(selected, frames);
    expect(result.overallScore).not.toBeNull();
    expect(result.overallScore as number).toBeGreaterThanOrEqual(selected.overallPassFloor);
    expect(result.requirements.find((requirement) => requirement.metricKey === criticalKey)?.passState).toBe("retry");
    expect(result.outcome).toBe("retry");
  });
});

// @spec OBS-ASSESS-007
describe("visual assessment evidence gating", () => {
  it("keeps empty, missing, and low-coverage takes ungraded", () => {
    const selected = profile();
    const empty = assessVisualFrames(selected, []);
    expect(empty).toEqual(expect.objectContaining({ outcome: "insufficient_evidence", overallScore: null, evidenceCoverage: 0 }));

    const missingRequired = assessVisualFrames(selected, [frame(0, [metric("unrelated_metric", 1, "good")])]);
    expect(missingRequired.outcome).toBe("insufficient_evidence");

    const partial = goodFrames(selected).map((item, index) => ({
      ...item,
      metrics: item.metrics.map((reading) =>
        index < 5 && reading.key === selected.requirements[0].metricKey
          ? metric(reading.key, 0, "low_confidence", 0.2)
          : reading,
      ),
    }));
    const lowCoverage = assessVisualFrames(selected, partial);
    expect(lowCoverage.outcome).toBe("insufficient_evidence");
    expect(lowCoverage.overallScore).toBeNull();
    expect(lowCoverage.evidenceCoverage).toBe(0.5);
  });
});

// @spec OBS-ASSESS-011, OBS-ASSESS-012
describe("visual assessment result contract", () => {
  it("is deterministic over input ordering and retains the profile thresholds", () => {
    const selected = profile("violin");
    const frames = goodFrames(selected);
    const forward = assessVisualFrames(selected, frames);
    const reverse = assessVisualFrames(selected, [...frames].reverse());

    expect(reverse).toEqual(forward);
    expect(forward).toEqual(
      expect.objectContaining({
        profileId: selected.id,
        profileVersion: selected.version,
        instrument: "violin",
        skillSlug: "open-string-bow",
        thresholds: {
          confidenceFloor: 0.5,
          coverageFloor: 0.6,
          overallPassFloor: 0.65,
        },
      }),
    );
  });
});

// @spec CAP-VID-002, CAP-VID-004, OBS-TIME-005, OBS-TIME-006, OBS-ASSESS-014
describe("selected-video assessment export", () => {
  it("contains the profile and aggregate without media, landmarks, or audio facts", () => {
    const selected = profile();
    const frames = goodFrames(selected, 2);
    const exported = createVisualAssessmentExport({
      fileName: "practice.mp4",
      durationMs: 1000,
      profile: selected,
      frames,
    });
    const serialized = JSON.stringify(exported);

    expect(exported.source).toEqual({ kind: "selected-video", fileName: "practice.mp4", durationMs: 1000 });
    expect(exported.profile.id).toBe(selected.id);
    expect(exported.assessment.outcome).toBe("pass");
    expect(exported.frames[0].timestampMs).toBe(0);
    expect(serialized).not.toMatch(/landmarks|videoBytes|audio|pitch|rhythm|musicxml|dtw/i);
  });
});

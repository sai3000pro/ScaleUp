import { describe, expect, it } from "vitest";

import { canOpenLesson, canTraverseLesson } from "@/lib/lesson";
import type { GraphNode, NodeState } from "@/lib/types";

function node(
  state: NodeState,
  assessable = true,
): Pick<GraphNode, "assessable" | "progress"> {
  return {
    assessable,
    progress: {
      state,
      level: 1,
      exp: 0,
      mastery: 0.2,
      proficiency: 0.2,
      interval_days: 1,
      ease: 2.5,
      reviews: 0,
      overdue_days: 0,
      last_reviewed_at: null,
      due_at: null,
    } as GraphNode["progress"],
  };
}

describe("opening a lesson", () => {
  // @spec PROG-DRILL-001
  it("opens for a skill the learner can actually work on", () => {
    expect(canOpenLesson(node("available"))).toBe(true);
    expect(canOpenLesson(node("learning"))).toBe(true);
    expect(canOpenLesson(node("decaying"))).toBe(true);
    expect(canOpenLesson(node("mastered"))).toBe(true);
  });

  // @spec PROG-DRILL-004
  it("refuses a skill whose prerequisites are unmet", () => {
    // The tree says this is locked. Starting a lesson anyway would contradict
    // the thing the learner is looking at.
    expect(canOpenLesson(node("locked"))).toBe(false);
  });

  // @spec PROG-DRILL-003
  it("refuses a structural heading, which owns no skill to drill", () => {
    expect(canOpenLesson(node("available", false))).toBe(false);
  });

  it("refuses nothing at all rather than throwing", () => {
    expect(canOpenLesson(null)).toBe(false);
    expect(canOpenLesson(undefined)).toBe(false);
  });
});

describe("walking a lesson realm", () => {
  // @spec UI-GRAPH3D-023, UI-GRAPH3D-025, UI-GRAPH3D-030
  it("allows traversal only after the target lesson is cleared", () => {
    expect(canTraverseLesson({ cleared: true })).toBe(true);
    expect(canTraverseLesson({ cleared: false })).toBe(false);
    expect(canTraverseLesson(null)).toBe(false);
    expect(canTraverseLesson(undefined)).toBe(false);
  });

  // @spec UI-GRAPH3D-030
  it("does not confuse practice access with traversal access", () => {
    expect(canTraverseLesson({ cleared: false })).toBe(false);
    expect(canTraverseLesson({ cleared: true })).toBe(true);
  });
});

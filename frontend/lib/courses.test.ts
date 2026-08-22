import { describe, expect, it } from "vitest";

import { learnerCourses, prebuiltCourses } from "@/lib/courses";
import type { Course } from "@/lib/types";

function course(id: string, shelf: Course["shelf"]): Course {
  return {
    id,
    title: id,
    description: null,
    status: "ready",
    shelf,
    graph_version: 1,
    node_count: 7,
    edge_count: 8,
    mastered_count: 0,
    created_at: "2026-08-21T00:00:00Z",
  };
}

const ALL: Course[] = [
  course("mine", "learner"),
  course("guitar", "prebuilt"),
  course("trumpet", "internal"),
];

describe("what stands in the learner's list", () => {
  // @spec CURR-SHELF-002
  it("shows only what the learner made", () => {
    expect(learnerCourses(ALL).map((c) => c.id)).toEqual(["mine"]);
  });

  // @spec CURR-SHELF-003
  it("offers the prebuilt set as a separate view", () => {
    expect(prebuiltCourses(ALL).map((c) => c.id)).toEqual(["guitar"]);
  });

  // @spec CURR-SHELF-005
  it("puts an internal course on neither", () => {
    const shown = [...learnerCourses(ALL), ...prebuiltCourses(ALL)];
    expect(shown.some((c) => c.id === "trumpet")).toBe(false);
  });

  // @spec CURR-SHELF-001
  it("treats a shelf it has never heard of as the learner's own", () => {
    // `shelf` is a bare string over the wire. A shelf added after this build
    // must not make a learner's course vanish from the only list that shows it.
    const future = [...ALL, { ...course("new", "learner"), shelf: "syllabus" as Course["shelf"] }];
    expect(learnerCourses(future).map((c) => c.id)).toEqual(["mine", "new"]);
  });
});

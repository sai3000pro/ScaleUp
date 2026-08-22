/**
 * Which courses stand in which list.
 *
 * Three kinds of course arrive on one payload, and only one of them is the
 * learner's. Pure and separate from the page because "my list should contain what
 * I made" is a rule about the product, not about a component — and the failure it
 * guards against is silent: a learner's own tree disappearing into a wall of
 * seeded ones is not an error anybody sees.
 *
 * `shelf` is a bare string over the wire, so an unrecognised value falls to the
 * learner rather than nowhere. A shelf added after this build must not make a
 * course vanish from the only list that would have shown it.
 */

import type { Course } from "@/lib/types";

// @spec CURR-SHELF-002, CURR-SHELF-005
export function learnerCourses(courses: Course[]): Course[] {
  return courses.filter((course) => course.shelf !== "prebuilt" && course.shelf !== "internal");
}

// @spec CURR-SHELF-003
export function prebuiltCourses(courses: Course[]): Course[] {
  return courses.filter((course) => course.shelf === "prebuilt");
}

/**
 * Whether a skill can be worked on right now.
 *
 * Pure, and separate from the page, because "double-clicking this orb should
 * start a lesson" is a rule about the tree rather than about a component — and
 * a rule nothing can test is a rule that drifts.
 *
 * Two skills refuse, for different reasons. A structural heading owns no skill
 * to drill; it is scaffolding the tree needs for gating, not something anyone
 * plays. A locked skill has unmet prerequisites the inspector already names, and
 * quietly starting a lesson there would contradict the tree the learner is
 * looking at.
 *
 * Both refusals still select. Refusing to begin is not refusing to explain.
 */

import type { GraphNode, Lesson } from "@/lib/types";

// @spec PROG-DRILL-003, PROG-DRILL-004
export function canOpenLesson(
  node: Pick<GraphNode, "assessable" | "progress"> | null | undefined,
): boolean {
  if (!node) return false;
  if (!node.assessable) return false;
  return node.progress.state !== "locked";
}

/**
 * A lesson can be a POV destination only after that lesson is complete.
 * Practice uses the server's `open` flag separately, so an open future lesson
 * may be started from its card without moving the camera onto its node first.
 */
// @spec UI-GRAPH3D-023, UI-GRAPH3D-025, UI-GRAPH3D-030
export function canTraverseLesson(
  lesson: Pick<Lesson, "cleared"> | null | undefined,
): boolean {
  return lesson?.cleared === true;
}

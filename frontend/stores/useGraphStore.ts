"use client";

import { create } from "zustand";

import { api } from "@/lib/api";
import { graphShapeKey, layoutGraph, type PositionMap } from "@/lib/layout";
import type { GraphSnapshot } from "@/lib/types";

/**
 * A request to move the viewport onto a node.
 *
 * The nonce is load-bearing: focusing the node that is already focused is a
 * legitimate thing to ask for (re-running the same search, clicking the same
 * citation twice after panning away), and a plain `focusNodeId` string would
 * make that a no-op because the value never changed.
 */
export interface FocusRequest {
  nodeId: string;
  nonce: number;
}

interface GraphState {
  courseId: string | null;
  snapshot: GraphSnapshot | null;
  positions: PositionMap;
  shapeKey: string;
  status: "idle" | "loading" | "ready" | "error";
  error: string | null;
  selectedNodeId: string | null;
  focusRequest: FocusRequest | null;
  /**
   * The skill whose lesson the learner asked to open, from the tree itself.
   *
   * Separate from `selectedNodeId` because selecting a skill and asking to work
   * on it are different intents: clicking reads, double-clicking begins. Cleared
   * once consumed so re-selecting the same node later does not silently reopen
   * a lesson nobody asked for.
   */
  lessonFor: string | null;
  load: (courseId: string) => Promise<void>;
  select: (nodeId: string | null) => void;
  /**
   * Select a node AND pan the canvas to it.
   *
   * The seam for anything outside the React Flow provider -- quest deep-links,
   * search hits, answer citations, a guided-path stepper. `FocusController`
   * inside SkillTree consumes the request; see components/skill-tree/useFocusNode.ts.
   */
  focusNode: (nodeId: string) => void;
  /** Select a skill and open its lesson. */
  openLesson: (nodeId: string) => void;
  clearLesson: () => void;
}

export const useGraphStore = create<GraphState>((set, get) => ({
  courseId: null,
  snapshot: null,
  positions: {},
  shapeKey: "",
  status: "idle",
  error: null,
  selectedNodeId: null,
  focusRequest: null,
  lessonFor: null,

  load: async (courseId) => {
    // "loading" only on a COLD load. The course page renders the tree solely
    // under status === "ready", and DrillPanel refreshes after every grade, so
    // flipping to "loading" unconditionally unmounted React Flow on each
    // answer -- re-running fitView and throwing away the user's pan and zoom.
    // A refetch of the course already on screen swaps the snapshot in place.
    const cold = get().snapshot === null || get().courseId !== courseId;
    if (get().courseId !== courseId) {
      // A selection from the previous course would otherwise survive and index
      // into a graph it does not belong to.
      set({
        selectedNodeId: null,
        focusRequest: null,
        lessonFor: null,
        snapshot: null,
        positions: {},
        shapeKey: "",
      });
    }
    set({ status: cold ? "loading" : get().status, error: null, courseId });
    try {
      const snapshot = await api.getGraph(courseId);
      const key = graphShapeKey(snapshot.nodes, snapshot.edges);

      // Only relayout when the graph's SHAPE changed. A grade mutates progress
      // on one or two nodes and must not shuffle the tree under the user.
      const positions =
        key === get().shapeKey && Object.keys(get().positions).length > 0
          ? get().positions
          : layoutGraph(snapshot.nodes, snapshot.edges);

      set({ snapshot, positions, shapeKey: key, status: "ready" });
    } catch (error) {
      // A failed refresh of a tree already on screen must not blank it. Keep
      // the last good snapshot and surface the message; only a cold load has
      // nothing to fall back to.
      set({
        status: get().snapshot ? "ready" : "error",
        error: (error as Error).message,
      });
    }
  },

  select: (nodeId) => set({ selectedNodeId: nodeId, lessonFor: null }),

  openLesson: (nodeId) => set({ selectedNodeId: nodeId, lessonFor: nodeId }),

  clearLesson: () => set({ lessonFor: null }),

  focusNode: (nodeId) =>
    set((state) => ({
      selectedNodeId: nodeId,
      focusRequest: { nodeId, nonce: (state.focusRequest?.nonce ?? 0) + 1 },
    })),
}));

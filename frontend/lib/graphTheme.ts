/**
 * The graph's palette: the five node states and the section heading, drawn on
 * the graph's own dark ground rather than on the light page.
 *
 * The graph is a window into the curriculum, and it is the one place the light
 * page deliberately goes dark — near-black space, so a lit orb glows. Its
 * colours are the reference scheme this design follows: gold for what is ready,
 * slate for what is locked, blue for what is in hand, purple for what is done,
 * and orange for the one state the reference does not have — fading — taken
 * from its own urgency hue.
 *
 * ## Why a second palette, and why the mapping is declared once
 *
 * A colour carrying state on a non-text element must clear 3:1 against the
 * surface it sits on (UI-A11Y-009). The app's node-state palette is tuned
 * against the light page and cannot clear 3:1 on dark — the reference's own
 * gold against the warm page measures about 1.6:1 — so the graph declares its
 * own palette. The mapping from state to colour is this one function; meaning
 * never forks even though colour does.
 *
 * Locked and section sit below the 3:1 line on purpose (UI-GRAPH3D-017): they
 * are the "what is still ahead" part of the tree, and their state is carried
 * by the projected title, the hover card and the keyboard list rather than by
 * colour alone.
 *
 * The literals mirror the `--color-graph-*` tokens in app/globals.css. Change
 * one, change both — lib/theme.test.ts fails if they diverge.
 *
 * @spec UI-GRAPH3D-013, UI-GRAPH3D-017, UI-GRAPH3D-019
 */

import type { GraphNode, KnownNodeState, NodeState } from "@/lib/types";
import { nodeStyle, stateStyle } from "@/lib/nodeState";

export interface GraphStyle {
  label: string;
  /** Literal hex, for the WebGL scene, which takes colour values not classes. */
  accent: string;
  hint: string;
}

/** The graph's ground: near-black space, the one dark surface in a light app. */
export const GRAPH_GROUND = "#0b0e14";

/** The five node states, in the reference scheme. */
export const GRAPH_ACCENTS: Record<KnownNodeState, string> = {
  locked: "#334155",
  available: "#facc15",
  learning: "#38bdf8",
  decaying: "#f97316",
  mastered: "#a78bfa",
};

/** The section heading: scaffolding, hollow, and quieter than the frontier. */
export const GRAPH_STRUCTURAL_ACCENT = "#475569";

/** Shown for a state this build has never heard of. See lib/types.ts. */
const GRAPH_UNKNOWN_ACCENT = "#64748b";

/**
 * The only supported way to look a state's graph colour up.
 *
 * Labels and hints come from the app palette — a state's name and meaning do
 * not change with the ground it is drawn on; only its colour does.
 */
export function graphStateStyle(state: NodeState): GraphStyle {
  const base = stateStyle(state);
  return {
    ...base,
    accent: GRAPH_ACCENTS[state as KnownNodeState] ?? GRAPH_UNKNOWN_ACCENT,
  };
}

/** What a node's orb shows on the graph: its state, unless it is a heading. */
export function graphNodeStyle(node: Pick<GraphNode, "assessable" | "progress">): GraphStyle {
  const base = nodeStyle(node);
  return node.assessable
    ? graphStateStyle(node.progress.state)
    : { ...base, accent: GRAPH_STRUCTURAL_ACCENT };
}

/**
 * The edge into a skill, coloured by what it leads TO.
 *
 * One palette for nodes and routes, so a lit path and its destination agree:
 * into a ready skill the edge is gold and bright — the way on; into what is in
 * hand or done it is gold and dimmed; into a fading skill it is orange; into
 * the locked future it is slate.
 */
export interface GraphEdgeStyle {
  accent: string;
  opacity: number;
}

export function graphEdgeStyle(target: GraphNode): GraphEdgeStyle {
  if (!target.assessable || target.progress.state === "locked") {
    return { accent: GRAPH_ACCENTS.locked, opacity: 0.5 };
  }
  switch (target.progress.state) {
    case "available":
      return { accent: GRAPH_ACCENTS.available, opacity: 1 };
    case "decaying":
      return { accent: GRAPH_ACCENTS.decaying, opacity: 0.85 };
    default:
      // Learning or mastered: ground already covered, gold but no longer lit.
      return { accent: GRAPH_ACCENTS.available, opacity: 0.55 };
  }
}

/** The ring drawn around the selected skill. Neutral, so it never collides with a state hue. */
export const GRAPH_SELECTED = "#94a3b8";

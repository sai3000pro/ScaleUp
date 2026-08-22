/**
 * The graph palette: the five node states and the section heading, drawn with
 * the same warm light surfaces and plum-led accents as the rest of the site.
 *
 * The graph is a window into the curriculum, but it is still part of the
 * product's visual world. Its state colours therefore mirror nodeState.ts:
 * green for ready, violet for learning, amber for fading, blue for mastered,
 * and a quiet warm neutral for locked and structural nodes.
 *
 * ## Why the mapping is declared once
 *
 * A colour carrying state on a non-text element must clear 3:1 against the
 * surface it sits on (UI-A11Y-009). The graph's actionable accents are tuned
 * against the light graph ground, while locked and structural states recede and
 * remain explicitly labelled. The mapping from state to colour is this one
 * function; meaning never forks even though WebGL and DOM consume it
 * differently.
 *
 * The literals mirror the `--color-graph-*` tokens in app/globals.css. Change
 * one, change both — lib/theme.test.ts fails if they diverge.
 *
 * @spec UI-GRAPH3D-013, UI-GRAPH3D-017, UI-GRAPH3D-019, UI-GRAPH3D-029
 */

import type { GraphNode, KnownNodeState, NodeState } from "@/lib/types";
import { nodeStyle, stateStyle } from "@/lib/nodeState";

export interface GraphStyle {
  label: string;
  /** Literal hex, for the WebGL scene, which takes colour values not classes. */
  accent: string;
  hint: string;
}

/** The graph's ground: the same warm near-white used by the page. */
export const GRAPH_GROUND = "#fdfbfb";

/** The five node states, mirrored from the site's node-state palette. */
export const GRAPH_ACCENTS: Record<KnownNodeState, string> = {
  locked: "#96898d",
  available: "#1f7a54",
  learning: "#6547b8",
  decaying: "#8a6206",
  mastered: "#2b6f9e",
};

/** Section scaffolding: quiet and intentionally lower-contrast than a skill. */
export const GRAPH_STRUCTURAL_ACCENT = "#96898d";

/** Shown for a state this build has never heard of. See lib/types.ts. */
const GRAPH_UNKNOWN_ACCENT = "#96898d";

/**
 * The only supported way to look a state's graph colour up.
 *
 * Labels and hints come from the app palette — a state's name and meaning do
 * not change with the surface it is drawn on; only its colour does.
 */
export function graphStateStyle(state: NodeState): GraphStyle {
  const base = stateStyle(state);
  return {
    ...base,
    accent: GRAPH_ACCENTS[state as KnownNodeState] ?? GRAPH_UNKNOWN_ACCENT,
  };
}

/** What a node's orb shows on the graph: its state, unless it is a heading. */
export function graphNodeStyle(
  node: Pick<GraphNode, "assessable" | "progress">,
): GraphStyle {
  const base = nodeStyle(node);
  return node.assessable
    ? graphStateStyle(node.progress.state)
    : { ...base, accent: GRAPH_STRUCTURAL_ACCENT };
}

/**
 * The edge into a skill, coloured by what it leads TO.
 *
 * One palette for nodes and routes, so a lit path and its destination agree:
 * into a ready skill the edge is green and bright — the way on; into what is in
 * hand or done it is green and dimmed; into a fading skill it is amber; into
 * the locked future it is a quiet warm neutral.
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
      // Learning or mastered: ground already covered, green but no longer lit.
      return { accent: GRAPH_ACCENTS.available, opacity: 0.55 };
  }
}

/** The ring drawn around the selected skill, using the site's plum accent. */
export const GRAPH_SELECTED = "#c2557a";

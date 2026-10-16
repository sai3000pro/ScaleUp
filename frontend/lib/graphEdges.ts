import type { GraphEdge, GraphNode } from "@/lib/types";
import { GRAPH_GROUND, graphEdgeStyle } from "@/lib/graphTheme";
import type { PositionMap3D } from "@/lib/layout3d";

/**
 * Every prerequisite route in one vertex buffer.
 *
 * One `Line` per edge is one draw call per edge, which is fine for a curriculum
 * of a dozen skills and is what makes a compiled textbook's few hundred edges
 * stutter. Packed as line segments with a colour per vertex, the whole set of
 * routes is a single draw call however many there are. Opacity cannot ride on
 * a vertex, so each route's fade is baked into its colour by blending toward
 * the graph ground — the same appearance over an opaque ground, no blending
 * pass needed.
 *
 * @spec UI-GRAPH3D-010
 */
export interface EdgeBuffers {
  /** xyz per vertex, two vertices per edge. */
  positions: Float32Array;
  /** rgb per vertex in 0..1. */
  colors: Float32Array;
  /** How many edges were packed (edges with a missing endpoint are skipped). */
  count: number;
}

function channels(hex: string): [number, number, number] {
  const value = parseInt(hex.replace("#", ""), 16);
  return [
    ((value >> 16) & 255) / 255,
    ((value >> 8) & 255) / 255,
    (value & 255) / 255,
  ];
}

const GROUND = channels(GRAPH_GROUND);

/** `accent` at `opacity` over the ground, as the flat colour the eye would see. */
export function fadedTowardGround(
  accent: string,
  opacity: number,
): [number, number, number] {
  const rgb = channels(accent);
  return [0, 1, 2].map((i) => GROUND[i] + (rgb[i] - GROUND[i]) * opacity) as [
    number,
    number,
    number,
  ];
}

export function packEdges(
  edges: readonly GraphEdge[],
  positions: PositionMap3D,
  nodeById: ReadonlyMap<string, GraphNode>,
): EdgeBuffers {
  const kept = edges.filter(
    (edge) =>
      positions[edge.source] !== undefined &&
      positions[edge.target] !== undefined &&
      nodeById.has(edge.target),
  );
  const out: EdgeBuffers = {
    positions: new Float32Array(kept.length * 6),
    colors: new Float32Array(kept.length * 6),
    count: kept.length,
  };
  kept.forEach((edge, index) => {
    const from = positions[edge.source];
    const to = positions[edge.target];
    const style = graphEdgeStyle(nodeById.get(edge.target) as GraphNode);
    const [r, g, b] = fadedTowardGround(style.accent, style.opacity);
    const base = index * 6;
    out.positions.set([from.x, from.y, from.z, to.x, to.y, to.z], base);
    out.colors.set([r, g, b, r, g, b], base);
  });
  return out;
}

/**
 * The most titles worth projecting into the DOM on one frame. Past this, a
 * tree is a cloud of overlapping text whatever the collision pass does, and
 * the pass itself is quadratic in the candidate count; the nearest skills are
 * the ones being looked at, so they are the ones that keep their titles.
 */
export const MAX_PROJECTED_LABELS = 120;

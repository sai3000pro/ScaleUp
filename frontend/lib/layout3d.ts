/**
 * Where each skill sits in space.
 *
 * Pure, and separate from the canvas, because a layout is the one part of a 3D
 * view that can be wrong in ways nobody sees. A camera bug is obvious the moment
 * you look at it; two nodes occupying the same point, or a prerequisite floating
 * below the skill it unlocks, reads as "the graph is a bit messy" and stays.
 *
 * Depth is the backend's, computed by Kahn's algorithm over real prerequisites,
 * so a skill is never above the thing it depends on. That is the one property
 * the arrangement must not be free to choose.
 *
 * The tree is laid out flat — tiers stacked, siblings spread across, everything
 * on one plane — and a skill with several prerequisites is centred over them, so
 * a convergence looks like a convergence rather than a long diagonal. A tree you
 * can read at a glance is worth more than one that fills three dimensions
 * because it can; the depth is there to be moved through, not to scatter the
 * graph into a constellation nobody can trace.
 *
 * The exception is a tier too wide to read. Past a dozen siblings a single row
 * becomes a mile-wide line with the ends off screen, so the tier wraps into rows
 * set back in depth — which is the one case where the third dimension earns its
 * place.
 */

import type { GraphEdge, GraphNode } from "@/lib/types";

/** Vertical distance between prerequisite depths. */
export const TIER_HEIGHT = 40;

/** Horizontal gap between siblings. */
export const SIBLING_SPACING = 68;

/** Depth gap between the rows of a tier too wide for one line. */
export const ROW_DEPTH = 58;

/** How many siblings fit on one row before a tier wraps. */
export const MAX_ROW = 12;

export interface Point3 {
  x: number;
  y: number;
  z: number;
}

export type PositionMap3D = Record<string, Point3>;

/**
 * Lay the graph out.
 *
 * Tiers are walked shallowest-first so a skill's prerequisites are already
 * placed when it is centred over them. Ordering within a tier is the node
 * array's own, which is the backend's — stable across renders, so a skill does
 * not jump when its state changes.
 */
// @spec UI-GRAPH3D-002, UI-GRAPH3D-003
export function layoutGraph3D(nodes: GraphNode[], edges: GraphEdge[]): PositionMap3D {
  const byDepth = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const tier = byDepth.get(node.depth);
    if (tier) {
      tier.push(node);
    } else {
      byDepth.set(node.depth, [node]);
    }
  }

  // Prerequisites per skill, from the edges rather than from `blocked_by`:
  // `blocked_by` lists only the prerequisites still UNMET, so a learner who
  // completes one would see the tree shift under them.
  const parents = new Map<string, string[]>();
  const present = new Set(nodes.map((node) => node.id));
  for (const edge of edges) {
    if (present.has(edge.source) && present.has(edge.target)) {
      const known = parents.get(edge.target);
      if (known) {
        known.push(edge.source);
      } else {
        parents.set(edge.target, [edge.source]);
      }
    }
  }

  const positions: PositionMap3D = {};
  const depths = [...byDepth.keys()].sort((a, b) => a - b);

  for (const depth of depths) {
    const tier = byDepth.get(depth)!;
    const rows = Math.ceil(tier.length / MAX_ROW);
    const perRow = Math.ceil(tier.length / rows);

    tier.forEach((node, index) => {
      const row = Math.floor(index / perRow);
      const slot = index % perRow;
      const rowSize = Math.min(perRow, tier.length - row * perRow);
      const spread = (rowSize - 1) * SIBLING_SPACING;

      let x = slot * SIBLING_SPACING - spread / 2;

      // Centred over its prerequisites where they are all already placed, which
      // is what makes a convergence read as one.
      const above = (parents.get(node.id) ?? [])
        .map((id) => positions[id])
        .filter((point): point is Point3 => point !== undefined);
      if (above.length > 1) {
        x = above.reduce((sum, point) => sum + point.x, 0) / above.length;
      }

      positions[node.id] = {
        x,
        // Deeper skills sit lower, so the tree reads downward like the outline
        // and "further in" keeps meaning the same thing in both.
        y: -depth * TIER_HEIGHT,
        z: (row - (rows - 1) / 2) * ROW_DEPTH,
      };
    });

    // Centring on parents can land two siblings on the same spot. Nudge them
    // apart along the row rather than leaving one hidden behind the other.
    separate(tier, positions);
  }

  return positions;
}

/** Push apart any two skills in a tier that ended up too close to distinguish. */
function separate(tier: GraphNode[], positions: PositionMap3D): void {
  const placed = tier
    .map((node) => ({ id: node.id, point: positions[node.id] }))
    .filter((entry) => entry.point !== undefined)
    .sort((a, b) => a.point.x - b.point.x);

  for (let i = 1; i < placed.length; i += 1) {
    const previous = placed[i - 1].point;
    const current = placed[i].point;
    const gap = current.x - previous.x;
    if (Math.abs(current.z - previous.z) < 1 && gap < SIBLING_SPACING * 0.6) {
      current.x = previous.x + SIBLING_SPACING * 0.6;
    }
  }
}

/** How far the camera has to sit back to hold the whole tree in frame. */
// @spec UI-GRAPH3D-004
export function framingDistance(positions: PositionMap3D): number {
  const points = Object.values(positions);
  if (points.length === 0) return 160;

  let widest = 0;
  let lowest = 0;
  for (const point of points) {
    widest = Math.max(widest, Math.abs(point.x), Math.abs(point.z));
    lowest = Math.min(lowest, point.y);
  }
  // Whichever of height and width does not fit is the one that decides the
  // framing, so both are measured and the larger wins. A tree is usually much
  // taller than it is wide, so height carries the smaller multiplier -- the
  // panel is wider than it is tall and has room to spare sideways.
  //
  // The constant is headroom for the titles. They hang below the deepest skill,
  // so framing to the skills alone crops the last row's labels off the bottom.
  return Math.max(160, Math.abs(lowest) * 1.15 + 95, widest * 1.9);
}

/** The point the camera looks at: the middle of the tree, not its top. */
export function framingCentre(positions: PositionMap3D): Point3 {
  const points = Object.values(positions);
  if (points.length === 0) return { x: 0, y: 0, z: 0 };

  let lowest = 0;
  let highest = -Infinity;
  for (const point of points) {
    lowest = Math.min(lowest, point.y);
    highest = Math.max(highest, point.y);
  }
  return { x: 0, y: (lowest + highest) / 2, z: 0 };
}

/**
 * Dagre layout for the skill tree.
 *
 * dagre rather than elkjs: this is a layered DAG, which is precisely dagre's
 * Sugiyama model; it is synchronous (elkjs is worker-based, which would force a
 * loading state into the tree render) and a fraction of the bundle size. elkjs
 * earns its place if we later want orthogonal edge routing or thousands of
 * nodes -- this module is the one file that would change.
 *
 * Ranks are pinned from the backend's `depth`, computed by Kahn's algorithm, so
 * the tree layers by genuine prerequisite depth rather than by whatever order
 * the layout engine happened to walk.
 */

import dagre from "@dagrejs/dagre";

import type { GraphEdge, GraphNode } from "@/lib/types";

// Orbs, not cards. Much narrower than the old 220px box, which lets a
// 79-node graph read as a constellation instead of a wall of text.
export const NODE_WIDTH = 132;
export const NODE_HEIGHT = 112;

export type PositionMap = Record<string, { x: number; y: number }>;

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): PositionMap {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "TB", nodesep: 28, ranksep: 74, ranker: "network-simplex" });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT, rank: node.depth });
  }
  for (const edge of edges) {
    // Only draw between nodes we actually have; a dangling edge crashes dagre.
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
      graph.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(graph);

  const positions: PositionMap = {};
  for (const node of nodes) {
    const laid = graph.node(node.id);
    // dagre centres nodes; React Flow positions by top-left.
    positions[node.id] = { x: laid.x - NODE_WIDTH / 2, y: laid.y - NODE_HEIGHT / 2 };
  }
  return positions;
}

/** Stable key for memoising a layout: recompute only when the shape changes. */
export function graphShapeKey(nodes: GraphNode[], edges: GraphEdge[]): string {
  return `${nodes.map((n) => n.id).join(",")}|${edges.map((e) => e.id).join(",")}`;
}

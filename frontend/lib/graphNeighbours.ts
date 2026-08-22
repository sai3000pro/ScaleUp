/**
 * A skill's neighbours: the prerequisites that converge on it and the skills it
 * unlocks.
 *
 * Pure, and separate from the canvas, because traversal depends on it and a
 * wrong answer is invisible until the learner clicks a card and lands somewhere
 * they did not mean to. Edges are read rather than `blocked_by`, which lists
 * only prerequisites still UNMET — a learner who completes one would see the
 * tree's cards shift under them.
 *
 * @spec UI-GRAPH3D-020, UI-GRAPH3D-021
 */

import type { GraphEdge, GraphNode } from "@/lib/types";

export interface GraphNeighbours {
  parents: GraphNode[];
  children: GraphNode[];
}

export function neighboursOf(nodes: GraphNode[], edges: GraphEdge[], nodeId: string): GraphNeighbours {
  const present = new Set(nodes.map((node) => node.id));
  const byId = new Map(nodes.map((node) => [node.id, node] as const));

  const parents: GraphNode[] = [];
  const children: GraphNode[] = [];
  for (const edge of edges) {
    if (present.has(edge.source) && present.has(edge.target)) {
      const parent = edge.target === nodeId ? byId.get(edge.source) : undefined;
      if (parent) {
        parents.push(parent);
      }
      const child = edge.source === nodeId ? byId.get(edge.target) : undefined;
      if (child) {
        children.push(child);
      }
    }
  }
  return { parents, children };
}

import { describe, expect, it } from "vitest";

import {
  fadedTowardGround,
  MAX_PROJECTED_LABELS,
  packEdges,
} from "@/lib/graphEdges";
import { GRAPH_ACCENTS, GRAPH_GROUND } from "@/lib/graphTheme";
import { framingDistance, layoutGraph3D } from "@/lib/layout3d";
import type { GraphEdge, GraphNode } from "@/lib/types";

function node(
  id: string,
  depth: number,
  state: GraphNode["progress"]["state"] = "available",
): GraphNode {
  return {
    id,
    slug: id,
    title: id,
    summary: "",
    difficulty: 2,
    depth,
    assessable: true,
    section: null,
    blocked_by: [],
    sources: [],
    progress: {
      state,
      level: 1,
      exp: 0,
      mastery: 0.2,
    } as GraphNode["progress"],
  };
}

function edge(source: string, target: string): GraphEdge {
  return { id: `${source}->${target}`, source, target } as GraphEdge;
}

/** A tree the size a compiled textbook produces: `tiers` levels, `width` skills each, chained. */
function textbook(
  tiers: number,
  width: number,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  for (let tier = 0; tier < tiers; tier += 1) {
    for (let i = 0; i < width; i += 1) {
      nodes.push(
        node(`n${tier}-${i}`, tier, tier === 0 ? "available" : "locked"),
      );
      if (tier > 0) {
        edges.push(edge(`n${tier - 1}-${i}`, `n${tier}-${i}`));
        edges.push(edge(`n${tier - 1}-${(i + 1) % width}`, `n${tier}-${i}`));
      }
    }
  }
  return { nodes, edges };
}

// @spec UI-GRAPH3D-010
describe("packing the routes into one buffer", () => {
  it("writes two vertices per edge, coloured by the skill the route leads to", () => {
    const nodes = [node("a", 0), node("b", 1), node("c", 1, "locked")];
    const positions = layoutGraph3D(nodes, [edge("a", "b"), edge("a", "c")]);
    const packed = packEdges(
      [edge("a", "b"), edge("a", "c")],
      positions,
      new Map(nodes.map((n) => [n.id, n])),
    );
    expect(packed.count).toBe(2);
    expect(packed.positions.length).toBe(12);
    expect(Array.from(packed.positions.slice(0, 3))).toEqual([
      positions.a.x,
      positions.a.y,
      positions.a.z,
    ]);
    const lit = Array.from(packed.colors.slice(0, 3));
    const locked = Array.from(packed.colors.slice(6, 9));
    const close = (got: number[], want: number[]) =>
      got.forEach((c, i) => expect(c).toBeCloseTo(want[i], 5));
    close(lit, fadedTowardGround(GRAPH_ACCENTS.available, 1));
    close(locked, fadedTowardGround(GRAPH_ACCENTS.locked, 0.5));
    expect(lit).not.toEqual(locked);
  });

  it("skips an edge whose endpoint was not laid out rather than drawing it to the origin", () => {
    const nodes = [node("a", 0), node("b", 1)];
    const positions = layoutGraph3D(nodes, [edge("a", "b")]);
    const packed = packEdges(
      [edge("a", "b"), edge("a", "ghost")],
      positions,
      new Map(nodes.map((n) => [n.id, n])),
    );
    expect(packed.count).toBe(1);
  });

  it("fades a route by blending it toward the ground, so a faded route needs no blend pass", () => {
    const ground = fadedTowardGround(GRAPH_ACCENTS.available, 0);
    const [r, g, b] = fadedTowardGround(GRAPH_GROUND, 1);
    expect(ground.map((c) => Math.round(c * 255))).toEqual(
      [r, g, b].map((c) => Math.round(c * 255)),
    );
    expect(fadedTowardGround(GRAPH_ACCENTS.available, 1)).not.toEqual(ground);
  });
});

// @spec UI-GRAPH3D-010
describe("a tree the size a compiled textbook produces", () => {
  const { nodes, edges } = textbook(12, 30);

  it("lays out 360 skills and 660 routes in one buffer well inside a frame budget", () => {
    const started = performance.now();
    const positions = layoutGraph3D(nodes, edges);
    const packed = packEdges(
      edges,
      positions,
      new Map(nodes.map((n) => [n.id, n])),
    );
    const elapsed = performance.now() - started;
    expect(packed.count).toBe(edges.length);
    expect(Object.keys(positions).length).toBe(nodes.length);
    expect(Number.isFinite(framingDistance(positions))).toBe(true);
    expect(elapsed).toBeLessThan(250);
  });

  it("keeps every skill at a distinct point", () => {
    const positions = layoutGraph3D(nodes, edges);
    const seen = new Set(
      Object.values(positions).map((p) => `${p.x},${p.y},${p.z}`),
    );
    expect(seen.size).toBe(nodes.length);
  });

  it("caps the titles projected into the DOM below the skill count", () => {
    expect(MAX_PROJECTED_LABELS).toBeLessThan(nodes.length);
    expect(MAX_PROJECTED_LABELS).toBeGreaterThan(0);
  });
});

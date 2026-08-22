import { describe, expect, it } from "vitest";

import { framingCentre, framingDistance, layoutGraph3D, MAX_ROW, SIBLING_SPACING, TIER_HEIGHT } from "@/lib/layout3d";
import type { GraphEdge, GraphNode } from "@/lib/types";

function node(id: string, depth: number): GraphNode {
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
    progress: { state: "available", level: 1, exp: 0, mastery: 0.2 } as GraphNode["progress"],
  };
}

function edge(id: string, source: string, target: string): GraphEdge {
  return { id, source, target } as GraphEdge;
}

describe("laying the tree out in space", () => {
  // @spec UI-GRAPH3D-002
  it("puts a prerequisite above everything that depends on it", () => {
    const nodes = [node("root", 0), node("mid", 1), node("leaf", 2)];
    const positions = layoutGraph3D(nodes, [edge("e1", "root", "mid"), edge("e2", "mid", "leaf")]);

    expect(positions.root.y).toBeGreaterThan(positions.mid.y);
    expect(positions.mid.y).toBeGreaterThan(positions.leaf.y);
  });

  // @spec UI-GRAPH3D-002
  it("puts every skill at the same depth on the same level", () => {
    const nodes = [node("a", 1), node("b", 1), node("c", 1)];
    const positions = layoutGraph3D(nodes, []);
    const heights = new Set(Object.values(positions).map((p) => p.y));

    expect(heights.size).toBe(1);
    expect(positions.a.y).toBe(-TIER_HEIGHT);
  });

  // @spec UI-GRAPH3D-003
  it("never places two skills at the same point", () => {
    // The failure this guards is silent: one orb hidden exactly behind another
    // looks like a graph with fewer skills in it, not like a bug.
    const nodes = [...Array(12)].map((_, i) => node(`n${i}`, i % 3));
    const positions = layoutGraph3D(nodes, []);
    const seen = new Set(Object.values(positions).map((p) => `${p.x.toFixed(3)},${p.y},${p.z.toFixed(3)}`));

    expect(seen.size).toBe(nodes.length);
  });

  // @spec UI-GRAPH3D-003
  it("sits a lone skill on the axis rather than off to one side", () => {
    const positions = layoutGraph3D([node("only", 0)], []);

    expect(positions.only.x).toBeCloseTo(0);
    expect(positions.only.z).toBeCloseTo(0);
  });

  // @spec UI-GRAPH3D-011
  it("keeps a readable tree on one plane", () => {
    // The reason to spend a third dimension is to move through the tree, not to
    // scatter it. A tree small enough to read stays flat.
    const nodes = [node("root", 0), node("a", 1), node("b", 1), node("c", 2)];
    const positions = layoutGraph3D(nodes, []);

    expect(Object.values(positions).every((p) => p.z === 0)).toBe(true);
  });

  // @spec UI-GRAPH3D-011
  it("wraps a tier too wide to read into rows set back in depth", () => {
    const wide = [...Array(MAX_ROW * 2)].map((_, i) => node(`w${i}`, 1));
    const positions = layoutGraph3D(wide, []);
    const depths = new Set(Object.values(positions).map((p) => p.z));

    expect(depths.size).toBeGreaterThan(1);
  });

  // @spec UI-GRAPH3D-012
  it("centres a skill over the prerequisites that converge on it", () => {
    // Two parents wide apart, one child. Anywhere but the middle reads as a
    // long diagonal from one parent rather than as a convergence.
    const nodes = [node("left", 0), node("right", 0), node("joined", 1)];
    const positions = layoutGraph3D(nodes, [
      edge("e1", "left", "joined"),
      edge("e2", "right", "joined"),
    ]);

    expect(positions.joined.x).toBeCloseTo((positions.left.x + positions.right.x) / 2);
  });

  // @spec UI-GRAPH3D-003
  it("pushes apart siblings that centring landed on the same spot", () => {
    // Both children converge on the same pair of parents, so both want the
    // midpoint. One hidden behind the other looks like a smaller tree.
    const nodes = [node("l", 0), node("r", 0), node("x", 1), node("y", 1)];
    const positions = layoutGraph3D(nodes, [
      edge("a", "l", "x"), edge("b", "r", "x"),
      edge("c", "l", "y"), edge("d", "r", "y"),
    ]);

    expect(Math.abs(positions.x.x - positions.y.x)).toBeGreaterThan(SIBLING_SPACING * 0.5);
  });

  // @spec UI-GRAPH3D-002
  it("is stable: the same graph lays out the same way twice", () => {
    // A layout that shifts between renders is one nobody can point at on a call.
    const nodes = [node("a", 0), node("b", 1), node("c", 1)];
    expect(layoutGraph3D(nodes, [])).toEqual(layoutGraph3D(nodes, []));
  });

  it("ignores an edge naming a skill the snapshot does not carry", () => {
    const nodes = [node("a", 0)];
    expect(() => layoutGraph3D(nodes, [edge("e", "a", "ghost")])).not.toThrow();
  });

  it("lays out an empty graph without throwing", () => {
    expect(layoutGraph3D([], [])).toEqual({});
    expect(framingDistance({})).toBeGreaterThan(0);
  });

  // @spec UI-GRAPH3D-004
  it("looks at the middle of the tree, not its top", () => {
    const nodes = [...Array(6)].map((_, i) => node(`n${i}`, i));
    const centre = framingCentre(layoutGraph3D(nodes, []));

    expect(centre.y).toBeLessThan(0);
    expect(centre.y).toBeGreaterThan(-5 * TIER_HEIGHT);
  });

  // @spec UI-GRAPH3D-004
  it("frames a deeper tree from further back", () => {
    const shallow = layoutGraph3D([node("a", 0), node("b", 1)], []);
    const deep = layoutGraph3D([...Array(20)].map((_, i) => node(`n${i}`, i)), []);

    expect(framingDistance(deep)).toBeGreaterThan(framingDistance(shallow));
  });
});

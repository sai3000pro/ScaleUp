import { describe, expect, it } from "vitest";

import { neighboursOf } from "@/lib/graphNeighbours";
import type { GraphEdge, GraphNode } from "@/lib/types";

function node(id: string, depth = 0): GraphNode {
  return {
    id,
    slug: id,
    title: id,
    summary: "",
    section: null,
    depth,
    assessable: true,
    difficulty: 1,
    sources: [],
    blocked_by: [],
    progress: {
      state: "available",
      level: 0,
      exp: 0,
      mastery: 0,
      proficiency: 1,
      due_at: null,
      overdue_days: 0,
    },
  };
}

function edge(id: string, source: string, target: string): GraphEdge {
  return { id, source, target, confidence: 1, support: 1, rationale: null, sources: [] };
}

describe("neighboursOf", () => {
  // @spec UI-GRAPH3D-020, UI-GRAPH3D-021
  it("separates the prerequisites from the unlocked skills", () => {
    const nodes = [node("root"), node("chords"), node("strumming")];
    const edges = [
      edge("e1", "root", "chords"),
      edge("e2", "chords", "strumming"),
    ];
    const atChords = neighboursOf(nodes, edges, "chords");
    expect(atChords.parents.map((n) => n.id)).toEqual(["root"]);
    expect(atChords.children.map((n) => n.id)).toEqual(["strumming"]);
  });

  // @spec UI-GRAPH3D-021
  it("returns a skill with several prerequisites as their common child", () => {
    const nodes = [node("a"), node("b"), node("c")];
    const edges = [edge("e1", "a", "c"), edge("e2", "b", "c")];
    const atC = neighboursOf(nodes, edges, "c");
    expect(atC.parents.map((n) => n.id).sort()).toEqual(["a", "b"]);
    expect(atC.children).toEqual([]);
  });

  it("returns nothing for an isolated skill", () => {
    const nodes = [node("solo")];
    const atSolo = neighboursOf(nodes, [], "solo");
    expect(atSolo.parents).toEqual([]);
    expect(atSolo.children).toEqual([]);
  });

  it("ignores edges that reference skills outside the snapshot", () => {
    const nodes = [node("here")];
    const edges = [edge("e1", "ghost", "here"), edge("e2", "here", "ghost")];
    const atHere = neighboursOf(nodes, edges, "here");
    expect(atHere.parents).toEqual([]);
    expect(atHere.children).toEqual([]);
  });
});

"use client";

import { useMemo, useRef } from "react";

import { difficultyLabel, nodeAriaLabel, nodeStyle } from "@/lib/nodeState";
import type { GraphNode, GraphSnapshot } from "@/lib/types";
import { FOCUS_RING } from "@/lib/ui";

interface Props {
  snapshot: GraphSnapshot;
  selectedNodeId: string | null;
  onSelect: (nodeId: string | null) => void;
}

function outlineOrder(nodes: GraphNode[]): GraphNode[] {
  return [...nodes].sort((left, right) => {
    const depth = left.depth - right.depth;
    return depth === 0 ? left.title.localeCompare(right.title) : depth;
  });
}

/**
 * A non-canvas representation of the graph for phones and assistive technology.
 *
 * React Flow is excellent at showing the shape of a large graph, but it is a
 * poor phone surface: zooming and panning compete with scrolling, and a canvas
 * does not expose the prerequisite order to a screen reader. This outline is
 * intentionally plain HTML. The same selection callback feeds the inspector,
 * so mobile and desktop still enter the identical drill loop.
 */
export function SkillTreeOutline({ snapshot, selectedNodeId, onSelect }: Props) {
  const orderedNodes = useMemo(() => outlineOrder(snapshot.nodes), [snapshot.nodes]);
  const buttonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const selected = snapshot.nodes.find((node) => node.id === selectedNodeId) ?? null;

  function moveFocus(index: number, delta: number): void {
    const nextIndex = Math.min(orderedNodes.length - 1, Math.max(0, index + delta));
    const nextNode = orderedNodes[nextIndex];
    if (nextNode) {
      buttonRefs.current[nextNode.id]?.focus();
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, index: number): void {
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      moveFocus(index, 1);
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      moveFocus(index, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      moveFocus(index, -index);
    } else if (event.key === "End") {
      event.preventDefault();
      moveFocus(index, orderedNodes.length - 1 - index);
    }
  }

  return (
    <section aria-labelledby="skill-outline-heading" className="rounded-xl border border-slate-800 bg-slate-950 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <h2 id="skill-outline-heading" className="font-display text-sm font-semibold">Skill outline</h2>
          <p className="mt-1 text-[11px] text-slate-400">
            Select a skill to inspect it. Use arrow keys to move through the outline.
          </p>
        </div>
        <span className="shrink-0 text-[11px] text-slate-500">{orderedNodes.length} nodes</span>
      </div>

      <p className="sr-only" aria-live="polite">
        {selected ? `${selected.title} selected.` : "No skill selected."}
      </p>

      <div className="mt-3 max-h-[60vh] overflow-y-auto pr-1" role="list" aria-label="Course skills">
        {orderedNodes.map((node, index) => {
          const structural = !node.assessable;
          const style = nodeStyle(node);
          const selectedNode = node.id === selectedNodeId;
          const status = structural ? style.label : style.label;
          const details = structural
            ? "Section heading"
            : `${status} · ${difficultyLabel(node.difficulty)}`;

          return (
            <div key={node.id} role="listitem" className="border-b border-slate-900 last:border-b-0">
              <button
                ref={(element) => {
                  buttonRefs.current[node.id] = element;
                }}
                type="button"
                role="button"
                aria-pressed={selectedNode}
                aria-label={nodeAriaLabel(node)}
                onClick={() => onSelect(node.id)}
                onKeyDown={(event) => handleKeyDown(event, index)}
                className={`flex w-full items-start gap-3 rounded-lg px-2.5 py-2.5 text-left transition hover:bg-slate-900 ${FOCUS_RING} ${
                  selectedNode ? "bg-slate-900 ring-1 ring-sky-400/70" : ""
                }`}
              >
                <span
                  aria-hidden
                  className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: style.accent }}
                />
                <span className="min-w-0 flex-1">
                  <span className={`block truncate font-display text-xs font-semibold ${structural ? "text-slate-400" : "text-slate-100"}`}>
                    {node.title}
                  </span>
                  <span className="mt-0.5 block text-[10px] text-slate-400">{details}</span>
                  {node.blocked_by.length > 0 && (
                    <span className="mt-0.5 block truncate text-[10px] text-slate-500">
                      Needs {node.blocked_by.map((blocker) => blocker.title).join(", ")}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-[10px] text-slate-500">Depth {node.depth}</span>
              </button>
            </div>
          );
        })}
      </div>

      {selected && selected.blocked_by.length > 0 && (
        <div className="mt-3 border-t border-slate-800 pt-3" aria-labelledby="outline-prerequisites-heading">
          <h3 id="outline-prerequisites-heading" className="text-[11px] font-semibold text-slate-300">
            Prerequisites for {selected.title}
          </h3>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {selected.blocked_by.map((blocker) => (
              <button
                key={blocker.id}
                type="button"
                onClick={() => onSelect(blocker.id)}
                className={`rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:border-sky-400 hover:text-slate-100 ${FOCUS_RING}`}
              >
                {blocker.title}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

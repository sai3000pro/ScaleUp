"use client";

import { useCallback } from "react";
import { useReactFlow } from "@xyflow/react";

/**
 * Pan and zoom the canvas onto one node.
 *
 * ## Why this exists
 *
 * Selecting a node and *showing* it are two different things, and until now
 * only the first happened. A Daily Quest links to
 * `/courses/{id}?node={nodeId}`; the page selected the node so the inspector
 * filled in, but the canvas never moved. On a 79-node tree at `minZoom: 0.15`
 * that means arriving zoomed out with a 72px orb selected somewhere off screen,
 * marked by a 1.5px white ring you cannot see. The board's primary
 * call-to-action landed you nowhere.
 *
 * ## For other callers
 *
 * **This hook must be called inside a `ReactFlowProvider`** -- `useReactFlow`
 * throws otherwise -- which in practice means inside `SkillTree`. Anything
 * outside the canvas (the quest deep-link effect, a search box, a citation
 * link, a guided-path "next" button) should instead call
 * `useGraphStore.focusNode(id)`, which selects the node and posts a focus
 * request that `FocusController` inside the canvas picks up. That indirection
 * is the whole point: it lets a component that is not a descendant of the
 * provider still move the viewport.
 *
 *     const focusNode = useGraphStore((s) => s.focusNode);
 *     focusNode(hit.node_id);   // selects it AND pans to it
 *
 * `fitView({ nodes: [...] })` rather than `setCenter(x, y)`: the caller knows an
 * id, not a position, and positions live in the dagre layout map rather than in
 * the snapshot. `maxZoom` is capped so that focusing a single node zooms *in*
 * to a readable scale instead of filling the viewport with one orb.
 */
export function useFocusNode(): (nodeId: string, options?: { animate?: boolean }) => void {
  const flow = useReactFlow();

  return useCallback(
    (nodeId: string, options?: { animate?: boolean }) => {
      void flow.fitView({
        nodes: [{ id: nodeId }],
        duration: options?.animate === false ? 0 : 600,
        maxZoom: 1,
        // Generous, so the node lands in context with its neighbours rather
        // than alone in an empty viewport.
        padding: 0.6,
      });
    },
    [flow],
  );
}

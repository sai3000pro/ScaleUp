"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from "@xyflow/react";

import { nodeAriaLabel, nodeStyle, stateStyle } from "@/lib/nodeState";
import type { GraphSnapshot } from "@/lib/types";
import type { PositionMap } from "@/lib/layout";
import { BLOCKING_ACCENT, SkillNodeCard, type SkillNodeData } from "@/components/skill-tree/SkillNodeCard";
import { useFocusNode } from "@/components/skill-tree/useFocusNode";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { useGraphStore } from "@/stores/useGraphStore";

// Defined once outside the component: a fresh object each render makes React
// Flow tear down and remount every custom node.
const NODE_TYPES = { skill: SkillNodeCard };

/**
 * Consumes focus requests posted from outside the canvas.
 *
 * Rendered as a child of `<ReactFlow>` purely for the provider context --
 * `useReactFlow` needs it, and the components that want to pan (the quest
 * deep-link effect on the course page, a search box, a citation link) all sit
 * above it in the tree. It draws nothing.
 */
function FocusController({ animate }: { animate: boolean }) {
  const focusRequest = useGraphStore((state) => state.focusRequest);
  const focusNode = useFocusNode();
  const handled = useRef(0);

  useEffect(() => {
    if (focusRequest && focusRequest.nonce !== handled.current) {
      handled.current = focusRequest.nonce;
      focusNode(focusRequest.nodeId, { animate });
    }
  }, [focusRequest, focusNode, animate]);

  return null;
}

interface Props {
  snapshot: GraphSnapshot;
  positions: PositionMap;
  selectedNodeId: string | null;
  onSelect: (nodeId: string | null) => void;
  /**
   * The learner asked to work on this skill, not merely to read about it.
   *
   * Double-click on the canvas, or Enter on a skill that is already selected --
   * the second press, so the first still just selects. Both are the same intent
   * and both land here.
   */
  onOpenLesson: (nodeId: string) => void;
  /**
   * Node ids matching the active search, or `null` when none is running.
   *
   * Applied as opacity on React Flow's own node wrapper rather than inside
   * `SkillNodeCard`: the card owns what an orb MEANS (its state, its level, its
   * ring), and "is it in the current search" is a property of the canvas, not of
   * the skill. An empty set is a real answer -- a search that matched nothing
   * dims everything, which is the honest picture.
   */
  matchedNodeIds?: ReadonlySet<string> | null;
}

// Enough contrast that a match reads instantly, not so little that the shape of
// the tree around it disappears -- the neighbours are why the match means
// anything.
const UNMATCHED_OPACITY = 0.18;

function SkillTreeCanvas({ snapshot, positions, selectedNodeId, onSelect, onOpenLesson, matchedNodeIds }: Props) {
  const prefersReducedMotion = usePrefersReducedMotion();

  /**
   * Keyboard selection.
   *
   * React Flow gives each node `tabIndex=0`, but selection here is driven by
   * the `selectedNodeId` prop, so pressing Enter only moved React Flow's
   * internal selection and never opened the inspector -- the drill loop was
   * mouse-only.
   *
   * Deliberately NOT `onSelectionChange`: that prop fires from React Flow's own
   * StoreUpdater effect, which reacts to the `nodes` prop. Calling back into
   * our store from it re-derives `nodes`, which re-enters StoreUpdater, and
   * React aborts with "maximum update depth exceeded" -- a blank page. Reading
   * the focused node from the DOM on keydown keeps the data flow one-way.
   */
  const handleNodeKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const nodeElement = (event.target as HTMLElement).closest<HTMLElement>(".react-flow__node");
    const nodeId = nodeElement?.getAttribute("data-id");
    if (nodeId && nodeId !== selectedNodeId) {
      event.preventDefault();
      onSelect(nodeId);
    } else if (nodeId && event.key === "Enter") {
      // Already selected: the learner is asking to begin, not to re-select.
      event.preventDefault();
      onOpenLesson(nodeId);
    }
  };

  /**
   * The prerequisites of the selected node, when that node is locked.
   *
   * A locked orb previously said "Locked" and nothing else, which states the
   * problem and withholds the answer -- the learner has to read the blocked-by
   * list in the sidebar and then hunt the canvas for those names by eye. Naming
   * them on the map turns a dead end into a route.
   *
   * `blocked_by` rather than every inbound edge: the backend already filtered it
   * to the prerequisites that are actually still unmet, so a prerequisite the
   * learner has already mastered does not get highlighted as work to do.
   */
  const blockingNodeIds = useMemo(() => {
    const selected = snapshot.nodes.find((node) => node.id === selectedNodeId);
    if (!selected || selected.progress.state !== "locked") return null;
    return new Set(selected.blocked_by.map((ref) => ref.id));
  }, [snapshot.nodes, selectedNodeId]);

  const nodes = useMemo<Node<SkillNodeData>[]>(
    () =>
      snapshot.nodes.map((node) => ({
        id: node.id,
        type: "skill",
        position: positions[node.id] ?? { x: 0, y: 0 },
        data: { node, blocking: blockingNodeIds?.has(node.id) ?? false },
        selected: node.id === selectedNodeId,
        draggable: false,
        // React Flow owns focus: the wrapper it renders around SkillNodeCard is
        // what gets `tabIndex=0`, and it takes its accessible name from here.
        // Leaving this unset left every node in the tree announced as an unnamed
        // group, while the carefully written label sat on a non-focusable child
        // where no assistive technology could reach it.
        ariaLabel: nodeAriaLabel(node),
        ariaRole: "button",
        domAttributes: { "aria-pressed": node.id === selectedNodeId },
        style:
          matchedNodeIds && !matchedNodeIds.has(node.id) && !blockingNodeIds?.has(node.id)
            ? { opacity: UNMATCHED_OPACITY, transition: "opacity 200ms" }
            : { transition: "opacity 200ms" },
      })),
    [snapshot.nodes, positions, selectedNodeId, matchedNodeIds, blockingNodeIds],
  );

  const edges = useMemo<Edge[]>(() => {
    const nodeById = new Map(snapshot.nodes.map((node) => [node.id, node]));
    return snapshot.edges.map((edge) => {
      // Colour the edge by what it leads TO, so a route into a fading node reads
      // as urgent at a glance. A route into a section heading is drawn in the
      // heading's own slate, for the same reason the orb is: it is structure,
      // not a lit path to something you can do.
      const targetNode = nodeById.get(edge.target);
      // The route into the locked node the learner is looking at, drawn as the
      // one thing on the canvas that answers "so what do I do?".
      const isBlockingRoute =
        edge.target === selectedNodeId && (blockingNodeIds?.has(edge.source) ?? false);
      const accent = isBlockingRoute
        ? BLOCKING_ACCENT
        : (targetNode ? nodeStyle(targetNode) : stateStyle("locked")).accent;
      // An edge into a node the search excluded recedes with it, or the tree
      // stays a hairball of bright lines over dimmed orbs.
      const filteredOut = Boolean(matchedNodeIds) && !matchedNodeIds?.has(edge.target);
      const dim =
        !isBlockingRoute &&
        (filteredOut || !targetNode || (targetNode.assessable && targetNode.progress.state === "locked"));
      const animated = targetNode?.assessable === true && targetNode.progress.state === "decaying";
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "smoothstep",
        // Respect prefers-reduced-motion: a tree with many overdue nodes is
        // otherwise continuous full-canvas movement.
        animated: animated && !prefersReducedMotion,
        style: {
          stroke: accent,
          // A lit path is the strongest signal of "you unlocked this route".
          // Locked branches stay visible but recede to bare structure.
          strokeWidth: dim ? 1 : isBlockingRoute ? 3 : 2.25,
          opacity: dim ? 0.22 : 0.9,
          filter: dim ? undefined : `drop-shadow(0 0 4px ${accent})`,
        },
      };
    });
  }, [snapshot.edges, snapshot.nodes, prefersReducedMotion, matchedNodeIds, blockingNodeIds, selectedNodeId]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.15}
      maxZoom={1.6}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      onNodeClick={(_, node) => onSelect(node.id)}
      // @spec PROG-DRILL-001, PROG-DRILL-002
      onNodeDoubleClick={(_, node) => onOpenLesson(node.id)}
      /* React Flow zooms on double-click by default, which cannot coexist with
         double-click meaning "open this lesson": the zoom moves the node out
         from under the cursor between the two clicks, so the second lands on the
         pane and deselects the skill the learner just asked to work on. The
         zoom controls and scroll both still zoom. */
      zoomOnDoubleClick={false}
      onKeyDownCapture={handleNodeKeyDown}
      onPaneClick={() => onSelect(null)}
      proOptions={{ hideAttribution: true }}
    >
      <FocusController animate={!prefersReducedMotion} />
      <Background variant={BackgroundVariant.Dots} gap={30} size={1} color="#d8cdd0" />
      <Controls showInteractive={false} className="!bg-white !text-slate-100 !shadow-sm" />
      <MiniMap
        pannable
        zoomable
        // The mask dims everything outside the viewport, so on a light canvas it
        // has to be a light wash -- a dark one reads as an opaque slab.
        maskColor="rgba(253, 251, 251, 0.68)"
        bgColor="#f8f5f5"
        nodeStrokeWidth={3}
        style={{ border: "1px solid #e2dadc", borderRadius: 8 }}
        nodeColor={(node) => {
          const data = node.data as SkillNodeData;
          // Via nodeStyle, not STATE_STYLES: the minimap is the zoomed-out read
          // of the same canvas, so a section heading must recede there too.
          return nodeStyle(data.node).accent;
        }}
      />
    </ReactFlow>
  );
}

/**
 * `ReactFlowProvider` so that `useReactFlow` works inside the canvas.
 *
 * Without it there is no way to move the viewport programmatically at all --
 * the instance only exists in context, and `<ReactFlow>` creates its own
 * private one when no provider wraps it.
 */
export function SkillTree(props: Props) {
  return (
    <ReactFlowProvider>
      <SkillTreeCanvas {...props} />
    </ReactFlowProvider>
  );
}

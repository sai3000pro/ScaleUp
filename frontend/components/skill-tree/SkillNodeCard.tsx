"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { difficultyLabel, nodeStyle } from "@/lib/nodeState";
import { dueLabelShort, isDueSoon } from "@/lib/time";
import type { GraphNode } from "@/lib/types";

export interface SkillNodeData extends Record<string, unknown> {
  node: GraphNode;
  /**
   * This node is one of the things standing between the learner and the node
   * they just selected. Set only while a LOCKED node is selected, so the canvas
   * answers "what do I do about it?" instead of only "you cannot do this".
   */
  blocking?: boolean;
}

// Amber, matching the "Prerequisite evidence" panel in the inspector. Exported
// so the edges into a locked node are drawn in the same colour as the orbs they
// come from -- one highlight, not two that happen to co-occur.
export const BLOCKING_ACCENT = "#b8860b";

const SIZE = 72;
const CENTER = SIZE / 2;
const RADIUS = 27;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * One skill in the tree, drawn as a glowing orb rather than a card.
 *
 * The orb shape is doing real work, not decoration. A skill tree is read by
 * *shape* first -- which constellation is lit, where the frontier is -- and only
 * then by name. Rectangular cards forced a 220px-wide box per node, so a
 * 79-node graph became a wall of text where every node looked identical at a
 * glance and the structure was invisible.
 *
 * The ring shows **proficiency**, not mastery: proficiency decays with time and
 * halves every review interval, so an orb visibly drains as it approaches its
 * due date. That draining is the retention mechanic made visible.
 *
 * ## Structural nodes
 *
 * `assessable === false` marks a chapter or section heading that owns no prose
 * of its own. It cannot be drilled -- `POST /drill` returns 409 -- and this card
 * used to ignore the flag entirely, so a container took the branch below marked
 * "the frontier must still read as live": a full green rim, a green glow, a `0`
 * in the middle and the caption `Ready · Intro`.
 *
 * That is not a cosmetic slip. Containers own no chunks, so they sit at graph
 * depth 0, and `difficulty_from_depth` maps depth 0 to difficulty 1, which is
 * labelled `Intro`. The top rank of a freshly ingested textbook is therefore
 * *entirely* containers -- a row of glowing green "Ready · Intro" orbs, every
 * one of them a dead end, positioned exactly where a new user starts reading.
 * Invisible in development because `seed.py` leaves `assessable` at its default.
 *
 * So a container is drawn as a hollow dashed slate ring: no fill, no glow, no
 * level digit, no proficiency arc, captioned `Section`. Dashed because an
 * incomplete outline is the one shape in this canvas that cannot be mistaken
 * for something to fill in.
 */
export function SkillNodeCard({ data, selected }: NodeProps) {
  const { node, blocking = false } = data as SkillNodeData;
  const structural = !node.assessable;
  const style = nodeStyle(node);
  const state = node.progress.state;
  const locked = !structural && state === "locked";
  const decaying = !structural && state === "decaying";

  const proficiency = structural ? 0 : Math.min(1, Math.max(0, node.progress.proficiency));
  const filled = CIRCUMFERENCE * proficiency;

  // Locked nodes recede rather than disappear: the shape of what is still ahead
  // of you is the part of a skill tree that creates the pull to keep going.
  // A container gets no glow at all -- glow is the signal for "there is
  // something here for you", and there is not.
  const glow = blocking
    ? `drop-shadow(0 0 12px ${BLOCKING_ACCENT})`
    : locked || structural
      ? "none"
      : `drop-shadow(0 0 ${selected ? 14 : 8}px ${style.accent})`;

  const dueSoon = !structural && !locked && isDueSoon(node.progress.due_at);
  const caption = structural
    ? style.label
    : decaying && node.progress.overdue_days > 0
      ? `${Math.floor(node.progress.overdue_days)}d overdue`
      : // Surface the schedule while it can still be acted on, not only once
        // the node has already fallen over. Falls back to the state and
        // difficulty for anything not due in the next week.
        (dueSoon ? dueLabelShort(node.progress.due_at) : null) ??
        `${style.label} · ${difficultyLabel(node.difficulty)}`;

  return (
    <div
      className="flex w-[132px] flex-col items-center"
      // The accessible name lives on React Flow's node wrapper, which is the
      // element that actually receives focus (`tabIndex=0`, `role` from
      // `Node.ariaRole`). It is set from `nodeAriaLabel` in SkillTree. This card
      // is a non-focusable child, so a `role="button"` and an `aria-label` here
      // named nothing that could ever be reached -- and an unfocusable button is
      // an ARIA violation in its own right. Hidden so the wrapper's name is not
      // read twice.
      aria-hidden
      title={
        structural
          ? `${node.title} — ${style.hint}`
          : locked
            ? `Blocked by: ${node.blocked_by.map((b) => b.title).join(", ")}`
            : node.summary
      }
    >
      <Handle type="target" position={Position.Top} className="!h-1 !w-1 !border-0 !bg-transparent" />

      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        // `motion-safe:` so a continuously pulsing canvas of overdue nodes
        // respects prefers-reduced-motion.
        className={decaying ? "motion-safe:animate-pulse" : undefined}
        style={{ filter: glow }}
      >
        {/* Filled disc, so the orb reads as an object rather than an outline.
            A container is deliberately hollow instead: it is a boundary drawn
            around other skills, not an object you can act on. */}
        {!structural && (
          <>
            <circle cx={CENTER} cy={CENTER} r={RADIUS - 3} fill="#ffffff" />
            <circle
              cx={CENTER}
              cy={CENTER}
              r={RADIUS - 3}
              fill={style.accent}
              opacity={locked ? 0.04 : 0.14}
            />
          </>
        )}

        {structural ? (
          <circle
            cx={CENTER}
            cy={CENTER}
            r={RADIUS}
            fill="none"
            stroke={style.accent}
            strokeWidth="1.5"
            strokeDasharray="4 5"
            opacity="0.85"
          />
        ) : (
          <>
            {/* Track, then the proficiency arc drawn over it. */}
            <circle cx={CENTER} cy={CENTER} r={RADIUS} fill="none" stroke="#e2dadc" strokeWidth="4" />
            {proficiency > 0 && (
              <circle
                cx={CENTER}
                cy={CENTER}
                r={RADIUS}
                fill="none"
                stroke={style.accent}
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray={`${filled} ${CIRCUMFERENCE - filled}`}
                transform={`rotate(-90 ${CENTER} ${CENTER})`}
              />
            )}

            {/* An unreviewed-but-reachable node has zero proficiency and would
                otherwise show no accent at all -- the frontier must still read
                as live, so give it a full thin rim. */}
            {proficiency === 0 && !locked && (
              <circle cx={CENTER} cy={CENTER} r={RADIUS} fill="none" stroke={style.accent} strokeWidth="2" opacity="0.75" />
            )}
          </>
        )}

        {selected && (
          <circle cx={CENTER} cy={CENTER} r={RADIUS + 5} fill="none" stroke="#2c2629" strokeWidth="1.5" opacity="0.55" />
        )}

        {/* The route out of a locked node. Drawn in the same amber the
            inspector uses for prerequisite evidence, so the two read as one
            answer to the same question. */}
        {blocking && !selected && (
          <circle
            cx={CENTER}
            cy={CENTER}
            r={RADIUS + 5}
            fill="none"
            stroke={BLOCKING_ACCENT}
            strokeWidth="2"
            strokeDasharray="3 4"
            opacity="0.95"
          />
        )}

        {/* No level digit on a container. A `0` there read as "level 0 of 5",
            which promises a progression that does not exist for this node. */}
        {!structural && (
          <text
            x={CENTER}
            y={CENTER + 5}
            textAnchor="middle"
            fill={locked ? "#a89fa2" : "#2c2629"}
            // SVG text does not inherit the Tailwind font utility, so without
            // this the level digit renders in the body face while the title
            // 6px below it is Sora.
            style={{ fontSize: 15, fontWeight: 700, fontFamily: "var(--font-sora), system-ui, sans-serif" }}
          >
            {locked ? "\u{1F512}" : node.progress.level}
          </text>
        )}
      </svg>

      {/* Where this skill was printed, not what it requires. The outline used
          to be rendered as nodes and edges, which put the book's contents page
          on the canvas in place of the dependency structure. It is provenance,
          so it is shown as provenance: quiet, above the name, gating nothing. */}
      {node.section && !structural && (
        <p className="mt-1.5 max-w-[132px] truncate text-center font-body text-[8px] uppercase tracking-wider text-slate-500">
          {node.section}
        </p>
      )}

      <p
        className={[
          "max-w-[132px] text-center font-display text-[11px] leading-tight",
          node.section && !structural ? "" : "mt-1.5",
          // A heading is still a real label -- it is how you find your way
          // around -- so it stays legible, but at normal weight and one step
          // dimmer, so a rank of them does not out-shout the skills below.
          structural ? "font-medium text-slate-400" : "font-semibold",
          locked ? "text-slate-600" : structural ? "" : "text-slate-100",
        ].join(" ")}
      >
        {node.title}
      </p>
      <p className="text-center font-body text-[9px] uppercase tracking-wide text-slate-400">{caption}</p>

      <Handle type="source" position={Position.Bottom} className="!h-1 !w-1 !border-0 !bg-transparent" />
    </div>
  );
}

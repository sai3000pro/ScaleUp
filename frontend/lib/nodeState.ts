/**
 * Presentation for the five node states.
 *
 * Presentation only: the states themselves are derived server-side, in
 * backend/app/domain/states.py, and arrive on every `GraphNode.progress`.
 *
 * React Flow edge strokes and the SVG proficiency ring take literal colour
 * values, not Tailwind classes, so the palette lives here as hex AND in the
 * `@theme` block in app/globals.css. Change one, change both.
 *
 * The five accents are deliberately five distinct HUES, not five shades. An
 * earlier palette put `decaying` and `mastered` a few percent apart on the same
 * yellow, for the two states that mean the exact opposite things ("rescue this
 * now" and "you are done"). At node size, in a tree of eighty, they were the
 * same colour.
 *
 * Each accent also clears 3:1 against the page, since it carries state on a
 * non-text element. lib/theme.test.ts asserts both that and the mirror above.
 *
 * @spec UI-THEME-002, UI-A11Y-006, UI-A11Y-009
 */

import type { GraphNode, KnownNodeState, NodeState } from "@/lib/types";

export interface StateStyle {
  label: string;
  /** Literal hex, for SVG and React Flow, which take colour values not classes. */
  accent: string;
  /** One line explaining what this state means, for legends and tooltips. */
  hint: string;
}

export const STATE_STYLES: Record<KnownNodeState, StateStyle> = {
  locked: {
    label: "Locked",
    accent: "#96898d",
    hint: "Finish its prerequisites first",
  },
  available: {
    label: "Ready",
    accent: "#1f7a54",
    hint: "Ready to drill",
  },
  learning: {
    label: "Learning",
    accent: "#6547b8",
    hint: "In progress",
  },
  decaying: {
    label: "Fading",
    accent: "#8a6206",
    hint: "Overdue — rescue it for bonus EXP",
  },
  mastered: {
    label: "Mastered",
    accent: "#2b6f9e",
    hint: "Mastered — level 5 with mastery above 85%",
  },
};

/**
 * A structural node -- a chapter or section heading that owns no prose of its
 * own, so there is nothing in it to be asked about.
 *
 * It is NOT a sixth backend state. `assessable` is an independent axis: the
 * server still derives a real state for these nodes (and deliberately so --
 * `gating_masteries` walks *through* them, so they must be able to be
 * `available` or the whole subtree behind one would be permanently locked).
 * That is exactly why they need their own presentation: a container is almost
 * always in state `available`, and an `available` orb says "Ready" in green,
 * with a glow, at the top of the tree, where it is the first thing clicked.
 *
 * Slate rather than a sixth hue on purpose. The five accents are five things
 * you can DO; a heading is scaffolding, and should recede toward the canvas
 * rather than compete with the frontier for attention.
 */
export const STRUCTURAL_STYLE: StateStyle = {
  label: "Section",
  accent: "#64748b",
  hint: "A heading, not a skill — drill the skills underneath it",
};

/** Shown for a state this build has never heard of. See lib/types.ts. */
const UNKNOWN_STYLE: StateStyle = {
  label: "Unknown",
  accent: "#64748b",
  hint: "This build does not recognise this state",
};

/**
 * The only supported way to look a state up.
 *
 * `STATE_STYLES[state]` on a state added to the backend after this build was
 * cut returns `undefined`, and the very next `.accent` takes down the entire
 * canvas with a TypeError. Every node in the tree runs through this.
 */
export function stateStyle(state: NodeState): StateStyle {
  return STATE_STYLES[state as KnownNodeState] ?? UNKNOWN_STYLE;
}

/** What a node's orb is showing: its state, unless it is a heading. */
export function nodeStyle(node: Pick<GraphNode, "assessable" | "progress">): StateStyle {
  return node.assessable ? stateStyle(node.progress.state) : STRUCTURAL_STYLE;
}

/**
 * The accessible name for one node.
 *
 * Lives here rather than in SkillNodeCard because it belongs on React Flow's
 * node WRAPPER, which is the element that actually takes focus -- the card is
 * a non-focusable child of it. SkillTree passes this as `Node.ariaLabel`.
 */
export function nodeAriaLabel(node: GraphNode): string {
  if (!node.assessable) {
    return `${node.title}. Section heading, not a drillable skill.`;
  }
  if (node.progress.state === "locked") {
    const blockers = node.blocked_by.map((b) => b.title).join(", ");
    return `${node.title}. Locked. Needs ${blockers || "prerequisites"}.`;
  }
  return `${node.title}. ${stateStyle(node.progress.state).label}. Level ${node.progress.level} of 5.`;
}

/**
 * NOTE: a `deriveState()` mirror of backend/app/domain/states.py used to live
 * here, for optimistic recolouring after a grade. It was deleted rather than
 * kept: nothing ever imported it, so it never executed, and a hand-maintained
 * copy of the state machine that is never run is guaranteed to drift silently
 * from the server. It had already fallen behind -- it knew nothing about
 * structural nodes being transparent for gating.
 *
 * The app refetches the graph after each grade instead. If optimistic updates
 * become worth it, generate this from the backend rather than retyping it.
 */

export function difficultyLabel(difficulty: number): string {
  return ["", "Intro", "Easy", "Moderate", "Hard", "Advanced"][difficulty] ?? "Moderate";
}

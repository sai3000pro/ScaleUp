/**
 * The theme layer, checked as measurements rather than as opinions.
 *
 * Every finding this file covers survived a full palette rewrite and a browser
 * walkthrough, because none of them look like bugs: text at 4.37:1 looks like
 * text, and a gradient into a superseded palette looks like a gradient.
 * They are all computable from source, so they are computed here.
 *
 * This reads app/globals.css off disk rather than importing it. The token block
 * is CSS, and the point is to assert on what actually ships.
 */

import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  GRAPH_ACCENTS,
  GRAPH_GROUND,
  GRAPH_SELECTED,
  GRAPH_STRUCTURAL_ACCENT,
} from "@/lib/graphTheme";
import { STATE_STYLES } from "@/lib/nodeState";
import { BUTTON_PRIMARY, MUTED } from "@/lib/ui";

const CSS = readFileSync(
  fileURLToPath(new URL("../app/globals.css", import.meta.url)),
  "utf-8",
);

/** WCAG relative luminance. */
function luminance(r: number, g: number, b: number): number {
  const linear = [r, g, b].map((channel) => {
    const v = channel / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function hexLuminance(hex: string): number {
  const h = hex.replace("#", "");
  return luminance(
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  );
}

/** WCAG contrast ratio between two opaque hex colours. */
export function contrast(a: string, b: string): number {
  const [la, lb] = [hexLuminance(a), hexLuminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** Every `--color-*` declaration in the @theme block. */
function tokens(): Record<string, string> {
  const found: Record<string, string> = {};
  for (const match of CSS.matchAll(
    /--color-([a-z0-9-]+):\s*(#[0-9a-f]{6})\s*;/gi,
  )) {
    found[match[1]] = match[2].toLowerCase();
  }
  return found;
}

const TOKENS = tokens();

/**
 * The two surfaces text is placed on. The card is the one that matters: it is
 * where most muted text in the app sits, and it is lighter-on-lighter, so a
 * colour tuned against the page alone lands short here.
 */
const PAGE = () => TOKENS["slate-950"];
const CARD = () => TOKENS["slate-900"];

/** Ratio required of body and secondary text. */
const AA_TEXT = 4.5;
/** Ratio required of a colour carrying state on a non-text element. */
const AA_NON_TEXT = 3;

describe("token layer", () => {
  // @spec UI-THEME-001
  it("declares the palette as tokens", () => {
    expect(Object.keys(TOKENS).length).toBeGreaterThan(20);
    expect(PAGE()).toBeDefined();
    expect(CARD()).toBeDefined();
  });

  // @spec UI-THEME-004
  it("keeps the neutral ramp monotonic, so a component written against any point on it holds", () => {
    const ramp = [950, 900, 800, 700, 600, 500, 400, 300, 200, 100, 50].map(
      (step) => {
        const hex = TOKENS[`slate-${step}`];
        if (hex === undefined) throw new Error(`no token for slate-${step}`);
        return { step, hex, lum: hexLuminance(hex) };
      },
    );
    const descending = ramp.every(
      (entry, i) => i === 0 || entry.lum < ramp[i - 1].lum,
    );
    expect(
      descending,
      `ramp out of order: ${ramp.map((r) => `${r.step}=${r.lum.toFixed(3)}`).join(" ")}`,
    ).toBe(true);
  });

  // @spec UI-THEME-002
  it("keeps the node-state literals in step with their tokens", () => {
    for (const [state, style] of Object.entries(STATE_STYLES)) {
      expect(
        style.accent.toLowerCase(),
        `nodeState.${state} has drifted from --color-node-${state}`,
      ).toBe(TOKENS[`node-${state}`]);
    }
  });

  // @spec UI-THEME-007
  it("retains no opaque colour from the superseded palette", () => {
    // A light theme has no surface dark enough to want one. Low alpha is
    // excluded: the page ink is legitimately used at 0.3 for hairline borders.
    const offenders: string[] = [];
    for (const match of CSS.matchAll(
      /rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:\/\s*([\d.]+)\s*)?\)/g,
    )) {
      const [r, g, b] = [Number(match[1]), Number(match[2]), Number(match[3])];
      const alpha = match[4] === undefined ? 1 : Number(match[4]);
      if (luminance(r, g, b) < 0.06 && alpha >= 0.5) {
        offenders.push(match[0]);
      }
    }
    expect(offenders).toEqual([]);
  });

  // @spec UI-THEME-007
  it("sets no white text, having no surface dark enough to carry it", () => {
    expect(CSS.match(/color:\s*(white|#fff\b|#ffffff\b)/gi)).toBeNull();
  });

  // @spec UI-THEME-006
  it("paints the page background and ink explicitly", () => {
    expect(CSS).toMatch(/body\s*\{[^}]*background-color:/);
    expect(CSS).toMatch(/body\s*\{[^}]*color:/);
  });

  // @spec UI-THEME-005
  it("declares its colour scheme to the browser", () => {
    expect(CSS).toMatch(/color-scheme:\s*light/);
  });
});

describe("contrast", () => {
  /** Pull the one `text-slate-N` / `bg-sky-N` a shared constant resolves to. */
  function classToken(constant: string, prefix: string): string {
    const match = constant.match(new RegExp(`${prefix}-([a-z]+-\\d+)`));
    if (match === null) throw new Error(`no ${prefix}-* class in ${constant}`);
    const hex = TOKENS[match[1]];
    if (hex === undefined) throw new Error(`no token for ${match[1]}`);
    return hex;
  }

  // @spec UI-A11Y-007
  it("clears AA for muted text on the page AND on a raised card", () => {
    const ink = classToken(MUTED, "text");
    expect(contrast(ink, PAGE())).toBeGreaterThanOrEqual(AA_TEXT);
    expect(contrast(ink, CARD())).toBeGreaterThanOrEqual(AA_TEXT);
  });

  // @spec UI-A11Y-007
  it("clears AA for every neutral used as text on either surface", () => {
    // 500 and 400 are the two quiet inks; anything darker is stronger still.
    for (const step of [500, 400, 300, 200, 100, 50]) {
      const hex = TOKENS[`slate-${step}`];
      expect(
        contrast(hex, PAGE()),
        `slate-${step} on the page`,
      ).toBeGreaterThanOrEqual(AA_TEXT);
      expect(
        contrast(hex, CARD()),
        `slate-${step} on a card`,
      ).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  // @spec UI-A11Y-008
  it("clears AA for the primary button's label against its own fill", () => {
    const fill = classToken(BUTTON_PRIMARY, "bg");
    const label = classToken(BUTTON_PRIMARY, "text");
    expect(contrast(label, fill)).toBeGreaterThanOrEqual(AA_TEXT);
  });

  // @spec UI-A11Y-008
  it("clears AA for a page-white label on any accent fill it can land on", () => {
    for (const step of [500, 400, 300]) {
      const hex = TOKENS[`sky-${step}`];
      expect(
        contrast(PAGE(), hex),
        `page white on sky-${step}`,
      ).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  // @spec UI-A11Y-009
  it("clears the non-text minimum for every node-state colour", () => {
    for (const [state, style] of Object.entries(STATE_STYLES)) {
      expect(
        contrast(style.accent, PAGE()),
        `node state ${state}`,
      ).toBeGreaterThanOrEqual(AA_NON_TEXT);
    }
  });
});

describe("graph palette", () => {
  // @spec UI-GRAPH3D-017
  it("keeps the graph-state literals in step with their tokens", () => {
    for (const [state, accent] of Object.entries(GRAPH_ACCENTS)) {
      expect(
        accent.toLowerCase(),
        `graphTheme.${state} has drifted from --color-graph-${state}`,
      ).toBe(TOKENS[`graph-${state}`]);
    }
    expect(GRAPH_STRUCTURAL_ACCENT.toLowerCase()).toBe(
      TOKENS["graph-structural"],
    );
    expect(GRAPH_GROUND.toLowerCase()).toBe(TOKENS["graph-ground"]);
    expect(GRAPH_SELECTED.toLowerCase()).toBe(TOKENS["graph-selected"]);
  });

  // @spec UI-GRAPH3D-017, UI-GRAPH3D-029
  it("clears the non-text minimum for every graph state on the light ground", () => {
    const ground = TOKENS["graph-ground"];
    for (const [state, accent] of Object.entries(GRAPH_ACCENTS)) {
      expect(
        contrast(accent, ground),
        `graph state ${state}`,
      ).toBeGreaterThanOrEqual(AA_NON_TEXT);
    }
    expect(
      contrast(GRAPH_STRUCTURAL_ACCENT, ground),
      "graph structural",
    ).toBeGreaterThanOrEqual(AA_NON_TEXT);
  });

  // @spec UI-GRAPH3D-029
  it("keeps graph state values aligned with the shared site state palette", () => {
    for (const [state, style] of Object.entries(STATE_STYLES)) {
      expect(GRAPH_ACCENTS[state as keyof typeof GRAPH_ACCENTS]).toBe(
        style.accent,
      );
    }
    expect(GRAPH_STRUCTURAL_ACCENT).toBe(TOKENS["node-locked"]);
    expect(GRAPH_SELECTED).toBe(TOKENS["graph-selected"]);
    expect(
      contrast(GRAPH_SELECTED, TOKENS["graph-ground"]),
    ).toBeGreaterThanOrEqual(AA_NON_TEXT);
  });
});

/**
 * The failure this file existed to catch and did not.
 *
 * globals.css inverts the Tailwind ramps rather than editing 30 component
 * files, which works exactly as far as the list of ramps it inverts. `cyan` was
 * never on that list, and neither were a dozen individual shades of ramps that
 * were -- `rose-200`, `emerald-100`, `amber-500`. Tailwind still resolves them,
 * to its own values, which are chosen to sit on a near-black page. So
 * `text-cyan-200` rendered as #a5f3fc on white and the practice panel's Record
 * button was pale ice on pale ice; `text-rose-200` made "Stop and score
 * recording" pale pink on pale pink.
 *
 * Nothing threw, nothing failed to build, and the classes read correctly in
 * source. The only way to see it was to look at the right screen in the right
 * state -- so it is computed here instead.
 */
describe("ramp coverage", () => {
  const COMPONENT_GLOBS = ["app", "components", "lib"];
  /** Ramps globals.css takes ownership of by inverting any part of them. */
  const THEMED = ["slate", "sky", "emerald", "amber", "violet", "rose", "cyan"];
  /**
   * `red` is deliberately NOT themed. It survives only in the two instrument
   * drawings, where it paints a physical object -- an active piano key is the
   * same red whichever way the page runs -- alongside literal `bg-white` and
   * `bg-neutral-950`. Those files are the documented exception, so the rule is
   * enforced everywhere else rather than weakened for them.
   */
  const LITERAL_COLOUR_FILES = [
    "components/instrument/PianoKeyboard.tsx",
    "components/instrument/GuitarFretboard.tsx",
  ];

  function sourceFiles(): string[] {
    const found: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = `${dir}/${entry.name}`;
        if (entry.isDirectory()) {
          if (entry.name !== "node_modules") walk(full);
        } else if (entry.name.endsWith(".test.ts") || entry.name.endsWith(".test.tsx")) {
          // A test that names a class in prose is not a component using it --
          // this very file quotes `text-cyan-200` while explaining the bug.
        } else if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) {
          found.push(full);
        }
      }
    };
    for (const root of COMPONENT_GLOBS) {
      walk(fileURLToPath(new URL(`../${root}`, import.meta.url)));
    }
    return found;
  }

  // @spec UI-THEME-002
  it("declares every shade a component actually names", () => {
    const pattern = new RegExp(
      String.raw`\b(?:text|bg|border|ring|from|to|via|fill|stroke|decoration|divide|shadow|outline|accent|caret)-((?:${THEMED.join("|")})-\d+)`,
      "g",
    );
    const undeclared = new Map<string, string[]>();

    for (const file of sourceFiles()) {
      const posix = file.split("\\").join("/");
      const exempt = LITERAL_COLOUR_FILES.some((allowed) => posix.endsWith(allowed));
      if (exempt) {
        // The instrument drawings paint a physical object; see above.
      } else {
        const source = readFileSync(file, "utf-8");
        for (const match of source.matchAll(pattern)) {
          const shade = match[1];
          if (TOKENS[shade] === undefined) {
            const seen = undeclared.get(shade) ?? [];
            seen.push(posix.slice(posix.indexOf("/frontend/") + 1));
            undeclared.set(shade, seen);
          } else {
            // Declared, so it carries this theme's value rather than Tailwind's.
          }
        }
      }
    }

    const report = [...undeclared.entries()]
      .map(([shade, files]) => `  ${shade} — ${files[0]}${files.length > 1 ? ` (+${files.length - 1} more)` : ""}`)
      .join("\n");
    expect(
      undeclared.size,
      `these shades keep Tailwind's dark-theme value on a light page:\n${report}`,
    ).toBe(0);
  });

  // @spec UI-A11Y-007
  it("keeps every accent ink readable on the page and on a card", () => {
    // The -100..-400 end of an inverted accent ramp is ink; it has to clear AA
    // on both surfaces, exactly as the neutral ramp does.
    for (const ramp of THEMED.filter((name) => name !== "slate")) {
      for (const step of [100, 200, 300, 400]) {
        const hex = TOKENS[`${ramp}-${step}`];
        if (hex === undefined) {
          // Not every ramp spans every step; an absent one is not a failure.
        } else {
          expect(contrast(hex, PAGE()), `${ramp}-${step} on the page`).toBeGreaterThanOrEqual(AA_TEXT);
          expect(contrast(hex, CARD()), `${ramp}-${step} on a card`).toBeGreaterThanOrEqual(AA_TEXT);
        }
      }
    }
  });

  // @spec UI-A11Y-008
  it("keeps a page-white label readable on every accent fill", () => {
    for (const ramp of THEMED.filter((name) => name !== "slate")) {
      for (const step of [500, 600]) {
        const hex = TOKENS[`${ramp}-${step}`];
        if (hex === undefined) {
          // Not every ramp declares a solid fill.
        } else {
          expect(contrast(PAGE(), hex), `page white on ${ramp}-${step}`).toBeGreaterThanOrEqual(AA_TEXT);
        }
      }
    }
  });
});

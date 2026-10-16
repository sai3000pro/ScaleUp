/**
 * The design system's two adoption rules, checked against the source tree
 * rather than against a rendered page: shared constants are used where they
 * exist, and type sizes come from the declared scale.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const root = join(__dirname, "..");

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (name === "node_modules" || name === ".next" || name === "scripts") {
      // generated or tooling, not components
    } else if (statSync(path).isDirectory()) {
      sources(path, out);
    } else if (
      /\.tsx?$/.test(name) &&
      !/\.test\.tsx?$/.test(name) &&
      !path.endsWith("lib/ui.ts")
    ) {
      out.push(path);
    }
  }
  return out;
}

const files = ["app", "components", "lib", "stores"].flatMap((dir) =>
  sources(join(root, dir)),
);
const offenders = (pattern: RegExp) =>
  files
    .filter((f) => pattern.test(readFileSync(f, "utf-8")))
    .map((f) => f.slice(root.length + 1));

// @spec UI-SYS-004
describe("shared UI constants", () => {
  it("are named rather than restated: no component spells out the muted-ink class", () => {
    expect(offenders(/text-slate-400/)).toEqual([]);
  });

  it("are used: MUTED reaches components", () => {
    expect(offenders(/\bMUTED\b/).length).toBeGreaterThan(20);
  });
});

// @spec UI-TYPE-004
describe("the type scale", () => {
  it("is the only source of sizes in components: no arbitrary pixel sizes", () => {
    expect(offenders(/text-\[\d+px\]/)).toEqual([]);
  });

  it("is the only source of sizes in the stylesheet: every fixed font-size is a scale step", () => {
    const css = readFileSync(join(root, "app/globals.css"), "utf-8");
    const body = css.slice(css.indexOf("\n}\n", css.indexOf("@theme {")));
    const fixed = body.match(/font-size:\s*[0-9.]+(rem|px)/g) ?? [];
    expect(fixed).toEqual([]);
    expect(css).toMatch(/--text-mini: 0\.6875rem/);
  });
});

// @spec UI-SHELL-007
describe("the page body", () => {
  it("clips sideways overflow while the HUD nav keeps its own scroll", () => {
    const css = readFileSync(join(root, "app/globals.css"), "utf-8");
    const body = css.match(/\nbody \{[^}]*\}/)?.[0] ?? "";
    expect(body).toMatch(/overflow-x: clip/);
    expect(css.match(/\.hud-nav \{[^}]*\}/)?.[0]).toMatch(/overflow-x: auto/);
  });
});

// @spec UI-PAGE-007
describe("panels visible together", () => {
  it("do not both report the mastered count: the Guided path owns it", () => {
    const panel = readFileSync(
      join(root, "components/course/ProgressPanel.tsx"),
      "utf-8",
    );
    expect(panel).not.toMatch(/<dt[^>]*>Mastered<\/dt>/);
    expect(panel).not.toMatch(/mastered_skills\}/);
  });
});

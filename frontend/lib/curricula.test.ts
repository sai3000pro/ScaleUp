/**
 * The committed curricula manifest is derived, not typed: it must match what a
 * fresh read of backend/app/curricula/ derives, and the landing page's
 * instrument and skill figures must be read from it.
 */
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { PUBLISHED_CURRICULA } from "@/lib/curricula";
import { publishedCurricula } from "@/lib/curriculaSource";
import { SYSTEM_FIGURES } from "@/lib/landingEvidence";

const dir = fileURLToPath(
  new URL("../../backend/app/curricula/", import.meta.url),
);

// @spec LAND-STORY-010
describe("the curricula manifest", () => {
  it("matches a fresh derivation from the backend's curriculum files", () => {
    const files = Object.fromEntries(
      readdirSync(dir)
        .filter((name) => name.endsWith(".json"))
        .map((name) => [name, readFileSync(`${dir}${name}`, "utf-8")]),
    );
    expect(PUBLISHED_CURRICULA).toEqual(publishedCurricula(files));
  });

  it("is what the landing page counts", () => {
    const instruments = SYSTEM_FIGURES.find((f) => f.id === "instruments");
    const skills = SYSTEM_FIGURES.find((f) => f.id === "skills");
    expect(instruments?.value).toBe(String(PUBLISHED_CURRICULA.length));
    expect(skills?.value).toBe(
      String(PUBLISHED_CURRICULA.reduce((n, c) => n + c.skillCount, 0)),
    );
  });

  it("skips the catalogue and the violin's source textbook", () => {
    const names = PUBLISHED_CURRICULA.map((c) => c.instrument);
    expect(names).toEqual([...names].sort());
    expect(new Set(names).size).toBe(names.length);
    expect(names).not.toContain("catalogue");
    for (const name of names) expect(name).not.toMatch(/source/);
  });
});

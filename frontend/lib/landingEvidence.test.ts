/**
 * The landing page's claims, and the two rules that keep them honest.
 *
 * A public page is the one place in this codebase where the cost of a wrong
 * claim is paid entirely by someone who cannot check it. Two rules apply, and
 * both are asserted here rather than trusted:
 *
 *   Every stated quantity carries a source.
 *   The page names nobody.
 *
 * The second is the one worth a test. It is easy to argue that a problem is
 * hard by pointing at somebody who did it badly, the argument is genuinely more
 * concrete that way, and it is still not something to put on a page about your
 * own product.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { EVIDENCE, HARD_PARTS, SYSTEM_FIGURES } from "@/lib/landingEvidence";

// @spec LAND-CLAIM-002
describe("every figure", () => {
  it("carries a source with something in it", () => {
    expect(EVIDENCE.length).toBeGreaterThan(0);
    for (const figure of EVIDENCE) {
      expect(figure.source.trim().length, `${figure.id} has an empty source`).toBeGreaterThan(0);
      expect(figure.value.trim().length, `${figure.id} has an empty value`).toBeGreaterThan(0);
      expect(figure.label.trim().length, `${figure.id} has an empty label`).toBeGreaterThan(0);
    }
  });

  it("has an id nothing else uses, so a claim can be traced from the page back to here", () => {
    const ids = [...EVIDENCE.map((f) => f.id), ...HARD_PARTS.map((h) => h.id)];
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// @spec LAND-CLAIM-001, LAND-CLAIM-003
describe("every difficulty the page states", () => {
  it("says what goes wrong and what this system does instead", () => {
    expect(HARD_PARTS.length).toBeGreaterThan(0);
    for (const part of HARD_PARTS) {
      expect(part.title.trim().length, `${part.id} has no title`).toBeGreaterThan(0);
      // A difficulty with no stated answer is a complaint, not an argument.
      expect(part.problem.trim().length, `${part.id} states no problem`).toBeGreaterThan(0);
      expect(part.answer.trim().length, `${part.id} states no answer`).toBeGreaterThan(0);
    }
  });

  it("cites the file its answer can be checked in", () => {
    for (const part of HARD_PARTS) {
      expect(part.source, `${part.id} cites no file`).toMatch(/^(backend|frontend|docs)\/.+\.[a-z]+$/);
    }
  });
});

// @spec LAND-CLAIM-007
describe("the page names nobody", () => {
  /**
   * Read as text rather than through the exports: a name could be added to a
   * doc comment, a new field, or an entry this test does not know to walk, and
   * all three would render or ship.
   */
  const source = readFileSync(fileURLToPath(new URL("./landingEvidence.ts", import.meta.url)), "utf8");

  it("mentions no other project by name", () => {
    // The three read while this page was written, plus the shapes a name takes.
    const named = /music-maestro|MusicTeacher|vocal-ai|VocalAI|Maestro\b/i;
    expect(source, "landingEvidence.ts names another project").not.toMatch(named);
  });

  it("does not reach for a competitor framing at all", () => {
    const framing = /\b(competitor|rival|unlike other|other (?:apps|tools|products)|prior art|they (?:failed|could not))\b/i;
    expect(source).not.toMatch(framing);
  });
});

// @spec LAND-CLAIM-006
describe("figures about this system", () => {
  it("are sourced to this repository rather than to an outside estimate", () => {
    for (const figure of SYSTEM_FIGURES) {
      expect(
        figure.source,
        `${figure.id} claims something about this system but does not cite it`,
      ).toMatch(/(backend|frontend|docs)\//);
    }
  });

  it("states no market statistic, since none is sourced", () => {
    // The deliberate non-want, pinned. A lesson price, a teacher-supply figure
    // or an attrition rate does not go on the page until it has a citable
    // source -- and the failure mode is somebody adding a plausible-looking one.
    const currency = /[$£€]\s?\d|\bper hour\b|\bhourly rate\b/i;
    for (const figure of EVIDENCE) {
      expect(
        `${figure.value} ${figure.label}`,
        `${figure.id} states a price; LAND-CLAIM-006 wants a citable source first`,
      ).not.toMatch(currency);
    }
  });
});

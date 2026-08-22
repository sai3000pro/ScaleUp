/**
 * The landing page's figures, and the rule that keeps them honest.
 *
 * A marketing surface is the one place in this codebase where the cost of a
 * wrong number is paid entirely by someone who cannot check it. The project's
 * tenet is that the public page claims only what the product already does, and
 * this is where that tenet stops being a sentence in a document.
 *
 * The type already refuses a figure with no source, so these assert the part a
 * type cannot: that the source is a real one, that a claim about another
 * codebase says which file it can be checked in, and that nothing on the page
 * quietly became a round number nobody can trace.
 */
import { describe, expect, it } from "vitest";

import { EVIDENCE, PRIOR_ART, SYSTEM_FIGURES } from "@/lib/landingEvidence";

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
    const ids = EVIDENCE.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// @spec LAND-CLAIM-003
describe("a claim about another codebase", () => {
  it("names the repository and the file it can be checked in", () => {
    expect(PRIOR_ART.length).toBeGreaterThan(0);
    for (const entry of PRIOR_ART) {
      expect(entry.repo.trim().length, `${entry.repo} has no name`).toBeGreaterThan(0);
      // A path with an extension is the difference between "we looked at their
      // code" and a reader being able to open the line themselves.
      expect(entry.file, `${entry.repo} cites no file`).toMatch(/\.[a-z]+$/);
      expect(entry.finding.trim().length).toBeGreaterThan(0);
      // The section exists to say what each attempt could not measure. An entry
      // that only says it was limited is the assertion the evidence replaces.
      expect(entry.missing.trim().length, `${entry.repo} does not say what was missing`).toBeGreaterThan(0);
    }
  });
});

// @spec LAND-CLAIM-001, LAND-CLAIM-006
describe("figures about this system", () => {
  it("are sourced to this repository rather than to an outside estimate", () => {
    for (const figure of SYSTEM_FIGURES) {
      expect(
        figure.source,
        `${figure.id} claims something about this system but does not cite it`,
      ).toMatch(/(backend|frontend|docs)\//);
    }
  });

  it("states no market statistic, since none of the sources carries one", () => {
    // The deliberate non-want, pinned. `LAND-CLAIM-006` says a lesson price, a
    // teacher-supply figure or an attrition rate does not go on the page until
    // it has a citable outside source -- and the failure mode is that somebody
    // adds a plausible-looking one to fill the slot.
    const currency = /[$£€]\s?\d|\bper hour\b|\bhourly rate\b/i;
    for (const figure of EVIDENCE) {
      expect(
        `${figure.value} ${figure.label}`,
        `${figure.id} states a price; LAND-CLAIM-006 wants a citable source first`,
      ).not.toMatch(currency);
    }
  });
});

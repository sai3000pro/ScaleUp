/**
 * What ScaleUp asks a learner to supply.
 *
 * This project began as a textbook ingester, and the learner's course drawer
 * still carried its front door: an upload control, a browser of source
 * documents, and two empty states reading "Upload a PDF and the tree will build
 * itself." None of that is how someone learns an instrument here — they name an
 * instrument and get a tree — and none of it broke anything by being there,
 * which is exactly why it survived a rename, a rebrand and a pivot.
 *
 * The engine behind it is deliberately kept: it is the curriculum compiler's
 * source path, and it is how the violin tree is generated with no
 * violin-specific code. What is removed is the *surface*. Compiling a tree from
 * source material is an authoring capability, and this asserts it stays one.
 *
 * @spec UI-PAGE-008
 */

import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/** Every learner-facing source file. */
function learnerSurfaces(): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = `${dir}/${entry.name}`;
      if (entry.isDirectory()) {
        if (entry.name !== "node_modules") walk(full);
      } else if (entry.name.endsWith(".test.ts") || entry.name.endsWith(".test.tsx")) {
        // A test that quotes a phrase is not a surface offering it.
      } else if (entry.name.endsWith(".tsx")) {
        found.push(full);
      }
    }
  };
  for (const root of ["app", "components"]) {
    walk(fileURLToPath(new URL(`../${root}`, import.meta.url)));
  }
  return found;
}

describe("the learner surface", () => {
  // @spec UI-PAGE-008
  it("offers no way to supply a source document", () => {
    // The upload control and the source browser, by the names they had. A
    // reinstated panel would almost certainly carry one of them back.
    const gone = ["UploadCard", "SourceList"];
    const offenders: string[] = [];
    for (const file of learnerSurfaces()) {
      const source = readFileSync(file, "utf-8");
      for (const name of gone) {
        if (source.includes(name)) offenders.push(`${name} in ${file.split("/").slice(-2).join("/")}`);
      }
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });

  // @spec UI-PAGE-008
  it("does not tell a learner that a document builds their tree", () => {
    // Copy is the half that outlives the component. Both empty states kept
    // saying "Upload a PDF" long after this stopped being a textbook product.
    const forbidden = [/upload a pdf/i, /upload a document/i, /ingest a course/i];
    const offenders: string[] = [];
    for (const file of learnerSurfaces()) {
      const source = readFileSync(file, "utf-8");
      for (const phrase of forbidden) {
        const hit = source.match(phrase);
        if (hit !== null) offenders.push(`"${hit[0]}" in ${file.split("/").slice(-2).join("/")}`);
      }
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });
});

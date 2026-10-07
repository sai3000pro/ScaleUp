/**
 * Writes lib/curricula.ts from the backend's published curricula.
 *
 *   npm run build:curricula
 *
 * The landing page states how many instruments ship with a curriculum and how
 * many skills those curricula hold. Those are facts about files in
 * backend/app/curricula/, and the frontend cannot read that directory at
 * runtime — it is outside the deployed root. So the figures are derived here,
 * at authoring time, into a committed module; lib/curricula.test.ts re-derives
 * them from the same files and fails when the module has gone stale.
 *
 * A curriculum is "published" when its file sits in the directory with a
 * positive `version`; `violin-source.json` is the textbook the violin tree is
 * compiled from, not a curriculum, and is skipped by its suffix.
 *
 * @spec LAND-STORY-010
 */
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  publishedCurricula,
  renderCurriculaModule,
} from "../lib/curriculaSource";

const dir = fileURLToPath(
  new URL("../../backend/app/curricula/", import.meta.url),
);
const files = Object.fromEntries(
  readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => [name, readFileSync(`${dir}${name}`, "utf-8")]),
);
const out = fileURLToPath(new URL("../lib/curricula.ts", import.meta.url));
writeFileSync(out, renderCurriculaModule(publishedCurricula(files)));
console.log(`wrote ${out}`);

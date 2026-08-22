/**
 * The generated sprite manifest, checked against the files it describes.
 *
 * The manifest is written by `npm run build:sprites` and the frames are written
 * beside it, so the two can only disagree if someone edits one by hand or
 * commits half a run. Both failures are silent in a browser -- a missing frame
 * is an empty box, and a wrong cell geometry is a mascot that drifts as it
 * animates -- so they are worth an assertion that runs in CI.
 *
 * These read the committed `.webp` headers directly rather than decoding them.
 * A WebP header carries dimensions and an alpha flag, which is all that has to
 * be true here, and reading it keeps the test in the node environment the rest
 * of this suite runs in.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { QUARTZ_CELL, QUARTZ_CLIPS, QUARTZ_FRAMES, quartzSprite } from "@/lib/quartzSprites";

const NAMES = Object.keys(QUARTZ_FRAMES) as (keyof typeof QUARTZ_FRAMES)[];

/** Where a public URL from the manifest actually lives on disk. */
function fileFor(url: string): string {
  return fileURLToPath(new URL(".." + "/public" + url, import.meta.url));
}

/**
 * Dimensions and alpha out of a WebP header.
 *
 * Only the lossy form (`VP8 `) and the extended form (`VP8X`) appear here; the
 * encoder emits one or the other depending on whether the frame needed an alpha
 * chunk, and a frame that came back as neither is itself the failure.
 */
function readWebp(bytes: Buffer): { width: number; height: number; alpha: boolean; format: string } {
  expect(bytes.subarray(0, 4).toString("ascii")).toBe("RIFF");
  expect(bytes.subarray(8, 12).toString("ascii")).toBe("WEBP");
  const format = bytes.subarray(12, 16).toString("ascii");
  if (format === "VP8X") {
    return {
      format,
      alpha: (bytes[20] & 0x10) !== 0,
      width: 1 + (bytes[24] | (bytes[25] << 8) | (bytes[26] << 16)),
      height: 1 + (bytes[27] | (bytes[28] << 8) | (bytes[29] << 16)),
    };
  } else if (format === "VP8L") {
    const b = bytes.readUInt32LE(21);
    return { format, alpha: (bytes[24] & 0x08) !== 0, width: 1 + (b & 0x3fff), height: 1 + ((b >> 14) & 0x3fff) };
  } else {
    return {
      format,
      alpha: false,
      width: bytes.readUInt16LE(26) & 0x3fff,
      height: bytes.readUInt16LE(28) & 0x3fff,
    };
  }
}

// @spec UI-SPRITE-013
describe("the cell contract", () => {
  it("puts the ground line inside the cell, near its foot", () => {
    expect(QUARTZ_CELL.footY).toBeGreaterThan(0.5);
    expect(QUARTZ_CELL.footY).toBeLessThanOrEqual(1);
  });

  it("makes the character most of the cell but not all of it", () => {
    // All of it would mean no headroom for the poses that reach -- the raised
    // hands, the flare -- and those are exactly the frames that need it.
    expect(QUARTZ_CELL.bodyH).toBeGreaterThan(0.5);
    expect(QUARTZ_CELL.bodyH).toBeLessThan(1);
  });

  it("declares an aspect that matches its own dimensions", () => {
    expect(QUARTZ_CELL.aspect).toBeCloseTo(QUARTZ_CELL.width / QUARTZ_CELL.height, 3);
  });
});

// @spec UI-SPRITE-009, UI-SPRITE-015
describe("every frame on disk", () => {
  it("exists, carries transparency, and is the cell's own size", () => {
    expect(NAMES.length).toBeGreaterThan(0);
    for (const name of NAMES) {
      const header = readWebp(readFileSync(fileFor(quartzSprite(name))));
      expect(header.format, `${name} is not an extended WebP, so it carries no alpha chunk`).toBe("VP8X");
      expect(header.alpha, `${name} has no alpha`).toBe(true);
      // One size for every frame is the whole reason a swap is invisible.
      expect(header.width, `${name} width`).toBe(QUARTZ_CELL.width);
      expect(header.height, `${name} height`).toBe(QUARTZ_CELL.height);
    }
  });
});

// @spec UI-SPRITE-012
describe("facing", () => {
  it("agrees with the name the artist gave the frame", () => {
    for (const name of NAMES) {
      const facing = QUARTZ_FRAMES[name].facing;
      if (/-l[0-9]*$/.test(name)) expect(facing, name).toBe("left");
      else if (/-r[0-9]*$/.test(name)) expect(facing, name).toBe("right");
      else expect(facing, name).toBe("front");
    }
  });

  it("ships both facings of every pose that has one, so nothing needs mirroring", () => {
    const left = NAMES.filter((n) => QUARTZ_FRAMES[n].facing === "left");
    expect(left.length).toBeGreaterThan(0);
    for (const name of left) {
      const mirror = name.replace(/-l([0-9]*)$/, "-r$1");
      expect(NAMES, `${name} has no right-facing counterpart`).toContain(mirror);
    }
  });
});

// @spec UI-SPRITE-016
describe("every clip", () => {
  it("names only frames the sheet contains", () => {
    for (const [clip, spec] of Object.entries(QUARTZ_CLIPS)) {
      for (const frame of spec.frames) {
        expect(NAMES, `clip ${clip} names a frame that does not exist`).toContain(frame);
      }
    }
  });

  it("keeps a travelling clip to one facing, so the character does not turn mid-stride", () => {
    for (const [clip, spec] of Object.entries(QUARTZ_CLIPS)) {
      if (spec.loop) {
        const facings = new Set(spec.frames.map((f) => QUARTZ_FRAMES[f].facing));
        expect(facings.size, `clip ${clip} mixes facings`).toBe(1);
      }
    }
  });
});

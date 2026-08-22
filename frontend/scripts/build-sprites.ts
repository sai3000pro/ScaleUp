/**
 * Cuts Quartz's art sheet into one registered sprite library.
 *
 *   npm run build:sprites     # writes lib/quartzSprites.ts, public/sprites/quartz/*
 *
 * WHAT THE SOURCE IS. One 2048x2048 JPEG, `design/sprite_sheet.jpg`: twenty
 * poses of the mascot in a 4x5 grid, each drawn on flat neutral grey with its
 * name lettered underneath in black. The lettering is part of the image.
 *
 * FRAMES ARE FOUND BY PROJECTION, NOT BY DIVIDING INTO TWENTIETHS. The grid
 * looks tidy but is not: the poses are drawn at different widths, and the two
 * `sing` frames throw a pair of quaver glyphs clear of the body with a gap in
 * between. Projecting ink onto each axis finds the real bands, and merging
 * column runs closer together than any true inter-frame gap re-attaches those
 * quavers to the frame that threw them. Both counts are gated -- five rows of
 * drawings, four frames each -- so an art revision that breaks the assumption
 * fails here rather than shipping a sheared drawing.
 *
 * THE LETTERING IS DROPPED BY HEIGHT. Row projection yields eleven bands: a
 * title, then five bands of drawings alternating with five caption bands. The
 * drawings measure 305-318px tall and the captions 49-55, so one threshold
 * separates them with a factor of six in hand. Nothing reads the text.
 *
 * BACKGROUND IS FLOOD-FILLED FROM THE BORDER, not thresholded in place. The
 * gloves and shoes are painted a near-white that sits about twenty levels off
 * the grey ground -- close enough that any threshold loose enough to absorb the
 * sheet's JPEG noise also punches holes through both. Filling inward from the
 * cell border instead keeps an enclosed region because it is enclosed, whatever
 * colour it happens to be, and the same pass absorbs the ground's slight
 * corner-to-corner drift for free.
 *
 * EVERY FRAME LANDS ON ONE GROUND LINE AND ONE ANCHOR. The ground line is
 * measured per row as the lowest ink in it; the horizontal anchor is the
 * centroid of the frame's own purple. The centroid is what makes the run cycle
 * work -- `run-l1` and `run-l2` sit within a pixel of each other by it, where
 * their bounding-box centres differ by nine. Registering on the row's ground
 * rather than on each frame's own bottom is what keeps `jump` and `fall` in the
 * air: the lift the artist drew survives into the cell as transparent padding,
 * so nothing has to add it back at runtime.
 *
 * NO FRAME IS EVER MIRRORED. The sheet draws its own left- and right-facing
 * variants of every pose that has one, so a flop would be a second, worse copy
 * of a drawing that already exists -- and the microphone and the quavers are
 * drawn objects that read as reversed when flipped.
 *
 * This is NOT part of the Next build graph: nothing under app/ or lib/ imports
 * scripts/, every output is committed, and sharp stays a devDependency.
 *
 * @spec UI-SPRITE-001, UI-SPRITE-002, UI-SPRITE-003, UI-SPRITE-004
 * @spec UI-SPRITE-005, UI-SPRITE-006, UI-SPRITE-007, UI-SPRITE-008
 * @spec UI-SPRITE-009, UI-SPRITE-010, UI-SPRITE-011, UI-SPRITE-012
 * @spec UI-SPRITE-013, UI-SPRITE-014, UI-SPRITE-015, UI-SPRITE-016
 */
import { existsSync, mkdirSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHEET = join(HERE, "..", "..", "design", "sprite_sheet.jpg");
const OUT_DIR = join(HERE, "..", "public", "sprites", "quartz");
const MANIFEST = join(HERE, "..", "lib", "quartzSprites.ts");
const PUBLIC_PREFIX = "/sprites/quartz";

/** The sheet this pipeline was measured against. A different one must be re-measured. */
const EXPECT = { width: 2048, height: 2048 };

/** Ink is anything this far off the ground colour, per channel. */
const INK_TOLERANCE = 20;
/** A row band taller than this is a row of drawings; anything shorter is lettering. */
const ART_BAND_MIN_H = 150;
/** Column runs closer than this belong to one frame. True inter-frame gaps measure 111px and up. */
const RUN_MERGE_GAP = 60;
/** Rows of drawings, and frames per row. Both gated -- see the header. */
const ART_ROWS = 5;
const FRAMES_PER_ROW = 4;

/** Transparent margin inside the cell, in source px. */
const CELL_PAD = 10;
/**
 * The character ships this tall, measured on its purple.
 *
 * The source draws it about 265px tall, so this is a slight downscale rather
 * than an upscale: it buys the one resample that turns the sheet's hard,
 * JPEG-ringed edges into clean anti-aliasing, and it invents no detail the
 * artwork does not have. Displayed much above 240 CSS px the frames go soft.
 * That is the sheet's ceiling, not the pipeline's.
 */
const OUT_BODY_PX = 240;
/** Alpha blur before the resample, in source px. The sheet's edges measure hard. */
const FEATHER = 1.1;
/** How far the character's colour is grown past the cut, in source px, before feathering. */
const BLEED_PASSES = 3;

/** The artist's own names, in reading order, row by row. */
const NAMES: readonly (readonly string[])[] = [
  ["idle-l", "run-l1", "run-l2", "sing-l"],
  ["idle-r", "run-r1", "run-r2", "sing-r"],
  ["idle-front", "happy", "wink", "surprise"],
  ["jump", "fall", "hurt", "death"],
  ["attack", "victory", "bow", "applause"],
];

interface ClipSpec {
  note: string;
  frames: readonly string[];
  fps: number;
  loop: boolean;
  rest: number;
}

/**
 * Named sequences.
 *
 * `fps`, `loop` and `rest` are DECLARED, not measured -- frame timing is not in
 * the artwork. `rest` is how many extra frame slots the clip holds its last
 * frame for, which is what stops a short clip reading as a twitch.
 */
const CLIPS: Record<string, ClipSpec> = {
  idle: { note: "front, facing the reader", frames: ["idle-front"], fps: 1, loop: false, rest: 0 },
  blink: { note: "a wink, then back to front", frames: ["wink", "idle-front"], fps: 5, loop: false, rest: 0 },
  "run-left": { note: "two-frame gait, travelling left", frames: ["run-l1", "run-l2"], fps: 8, loop: true, rest: 0 },
  "run-right": { note: "two-frame gait, travelling right", frames: ["run-r1", "run-r2"], fps: 8, loop: true, rest: 0 },
  sing: { note: "eyes shut, into the microphone", frames: ["sing-r"], fps: 1, loop: false, rest: 0 },
  belt: { note: "the note lands -- flare, stars and all", frames: ["attack"], fps: 1, loop: false, rest: 0 },
  cheer: { note: "delight, then both hands up", frames: ["happy", "victory"], fps: 3, loop: false, rest: 4 },
  leap: { note: "up, over, and down", frames: ["jump", "fall"], fps: 6, loop: false, rest: 2 },
  stumble: { note: "off the note, then flat on the floor", frames: ["hurt", "death"], fps: 2.5, loop: false, rest: 5 },
  bow: { note: "taking the applause", frames: ["bow", "applause"], fps: 2.5, loop: false, rest: 4 },
  startled: { note: "caught out", frames: ["surprise"], fps: 1, loop: false, rest: 0 },
};

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

function fail(message: string): never {
  console.error("\n  build-sprites: " + message + "\n");
  process.exit(1);
}

/** Which way a frame looks, from the artist's own suffix. */
function facingOf(name: string): "left" | "right" | "front" {
  if (/-l[0-9]*$/.test(name)) return "left";
  else if (/-r[0-9]*$/.test(name)) return "right";
  else return "front";
}

async function main() {
  if (!existsSync(SHEET)) fail("no sheet at " + SHEET);

  const { data, info } = await sharp(SHEET).raw().toBuffer({ resolveWithObject: true });
  const { width: W, height: H, channels: C } = info;
  if (W !== EXPECT.width || H !== EXPECT.height) {
    fail("sheet is " + W + "x" + H + "; this pipeline was measured against "
      + EXPECT.width + "x" + EXPECT.height + ". Re-measure before trusting the cut.");
  }

  // ── The ground colour, read off the border rather than assumed ─────────────
  const rgb = (x: number, y: number) => {
    const i = (y * W + x) * C;
    return [data[i], data[i + 1], data[i + 2]] as const;
  };
  const corners = [rgb(2, 2), rgb(W - 3, 2), rgb(2, H - 3), rgb(W - 3, H - 3)];
  const GROUND = [0, 1, 2].map((k) => Math.round(corners.reduce((s, c) => s + c[k], 0) / corners.length));
  const spread = Math.max(...corners.flatMap((c) => c.map((v, k) => Math.abs(v - GROUND[k]))));
  if (spread > 12) fail("the sheet's corners disagree by " + spread + " levels; it is not painted on one flat ground.");

  const isInk = (x: number, y: number) => {
    const [r, g, b] = rgb(x, y);
    return Math.max(Math.abs(r - GROUND[0]), Math.abs(g - GROUND[1]), Math.abs(b - GROUND[2])) > INK_TOLERANCE;
  };
  /** The character's own colour. Nothing else on the sheet is purple. */
  const isBody = (x: number, y: number) => {
    const [r, g, b] = rgb(x, y);
    return isInk(x, y) && b > r + 12 && b > g + 20;
  };

  const runsOf = (n: number, on: (i: number) => boolean, minLen: number) => {
    const out: [number, number][] = [];
    let start = -1;
    for (let i = 0; i < n; i++) {
      if (on(i)) {
        if (start < 0) start = i;
      } else if (start >= 0) {
        if (i - start > minLen) out.push([start, i - 1]);
        start = -1;
      }
    }
    if (start >= 0 && n - start > minLen) out.push([start, n - 1]);
    return out;
  };

  // ── Bands ─────────────────────────────────────────────────────────────────
  const rowInk: number[] = [];
  for (let y = 0; y < H; y++) {
    let n = 0;
    for (let x = 0; x < W; x++) {
      if (isInk(x, y)) n++;
    }
    rowInk.push(n);
  }
  const bands = runsOf(H, (y) => rowInk[y] > 3, 4);
  const artBands = bands.filter(([a, b]) => b - a + 1 >= ART_BAND_MIN_H);
  if (artBands.length !== ART_ROWS) {
    fail("found " + artBands.length + " rows of drawings, expected " + ART_ROWS
      + ". Bands: " + bands.map(([a, b]) => a + "-" + b).join(" "));
  }

  // ── Frames ────────────────────────────────────────────────────────────────
  interface Cut {
    name: string;
    row: number;
    col: number;
    box: Box;
    /** The row of drawings this frame was cut from. Nothing outside it is this frame's. */
    bandY0: number;
    bandY1: number;
    anchorX: number;
    groundY: number;
    bodyH: number;
  }
  const cuts: Cut[] = [];

  artBands.forEach(([y0, y1], row) => {
    const colInk: number[] = [];
    for (let x = 0; x < W; x++) {
      let n = 0;
      for (let y = y0; y <= y1; y++) {
        if (isInk(x, y)) n++;
      }
      colInk.push(n);
    }
    const raw = runsOf(W, (x) => colInk[x] > 2, 6);
    const merged: [number, number][] = [];
    for (const run of raw) {
      const last = merged[merged.length - 1];
      if (last && run[0] - last[1] < RUN_MERGE_GAP) last[1] = run[1];
      else merged.push([run[0], run[1]]);
    }
    if (merged.length !== FRAMES_PER_ROW) {
      fail("row " + row + " cut into " + merged.length + " frames, expected " + FRAMES_PER_ROW
        + ": " + merged.map(([a, b]) => a + "-" + b).join(" "));
    }

    const rowCuts: Cut[] = merged.map(([x0, x1], col) => {
      const box: Box = { x0, y0: y1, x1, y1: y0 };
      let sx = 0;
      let bodyN = 0;
      let bodyTop = y1;
      let bodyBottom = y0;
      for (let y = y0; y <= y1; y++) {
        for (let x = x0; x <= x1; x++) {
          if (isInk(x, y)) {
            box.y0 = Math.min(box.y0, y);
            box.y1 = Math.max(box.y1, y);
            if (isBody(x, y)) {
              sx += x;
              bodyN++;
              bodyTop = Math.min(bodyTop, y);
              bodyBottom = Math.max(bodyBottom, y);
            }
          }
        }
      }
      if (bodyN === 0) fail("frame " + NAMES[row][col] + " has no body pixels; the colour test no longer matches the artwork.");
      return {
        name: NAMES[row][col],
        row,
        col,
        box,
        bandY0: y0,
        bandY1: y1,
        anchorX: sx / bodyN,
        groundY: box.y1,
        bodyH: bodyBottom - bodyTop + 1,
      };
    });

    // One ground line for the row: the lowest ink any of its frames reaches. A
    // frame drawn in the air keeps the gap the artist gave it.
    const ground = Math.max(...rowCuts.map((c) => c.box.y1));
    for (const c of rowCuts) c.groundY = ground;
    cuts.push(...rowCuts);
  });

  // ── One cell, big enough for every frame ──────────────────────────────────
  const left = Math.max(...cuts.map((c) => c.anchorX - c.box.x0));
  const right = Math.max(...cuts.map((c) => c.box.x1 - c.anchorX));
  const above = Math.max(...cuts.map((c) => c.groundY - c.box.y0));
  const half = Math.ceil(Math.max(left, right)) + CELL_PAD;
  const cellW = half * 2;
  const cellH = Math.ceil(above) + CELL_PAD * 2;
  /** Where the ground line sits in the cell, as a fraction of its height. */
  const footY = (CELL_PAD + above) / cellH;

  // The tallest drawn body sets the scale for the whole sheet -- per sheet,
  // never per frame, or the poses the artist deliberately squashed get
  // stretched back out and the drawn motion is flattened.
  const refBody = Math.max(...cuts.map((c) => c.bodyH));
  const scale = OUT_BODY_PX / refBody;
  const outW = Math.round(cellW * scale);
  const outH = Math.round(cellH * scale);

  console.log("  ground " + GROUND.join(",") + "  cell " + cellW + "x" + cellH
    + " -> " + outW + "x" + outH + "  footY " + footY.toFixed(4)
    + "  body " + refBody + "px -> " + OUT_BODY_PX + "px");

  // ── Cut, key, register, write ─────────────────────────────────────────────
  mkdirSync(OUT_DIR, { recursive: true });
  for (const f of readdirSync(OUT_DIR)) {
    if (f.endsWith(".webp")) unlinkSync(join(OUT_DIR, f));
  }

  const written: { name: string; bytes: number }[] = [];

  for (const cut of cuts) {
    // The source window: one cell, positioned so this frame's anchor and the
    // row's ground land where the cell says they do.
    const winX = Math.round(cut.anchorX) - half;
    const winY = cut.groundY + CELL_PAD - cellH + 1;

    // Ground is whatever the border reaches. Anything enclosed is kept, whatever
    // its colour -- which is what saves the near-white gloves and shoes.
    const isGround = new Uint8Array(cellW * cellH);
    const stack: number[] = [];
    const push = (cx: number, cy: number) => {
      if (cx < 0 || cy < 0 || cx >= cellW || cy >= cellH) return;
      const k = cy * cellW + cx;
      if (isGround[k]) return;
      const sxp = winX + cx;
      const syp = winY + cy;
      // Outside the sheet, or outside this frame's own column or row of
      // drawings, counts as ground. A cell is sized for the widest pose and the
      // tallest, so a smaller one would otherwise reach into its neighbour --
      // or, below the ground line, into the row's lettering.
      const outside = sxp < 0 || syp < 0 || sxp >= W || syp >= H
        || sxp < cut.box.x0 || sxp > cut.box.x1
        || syp < cut.bandY0 || syp > cut.bandY1;
      if (!outside && isInk(sxp, syp)) return;
      isGround[k] = 1;
      stack.push(cx, cy);
    };
    for (let x = 0; x < cellW; x++) {
      push(x, 0);
      push(x, cellH - 1);
    }
    for (let y = 0; y < cellH; y++) {
      push(0, y);
      push(cellW - 1, y);
    }
    while (stack.length) {
      const cy = stack.pop() as number;
      const cx = stack.pop() as number;
      push(cx + 1, cy);
      push(cx - 1, cy);
      push(cx, cy + 1);
      push(cx, cy - 1);
    }

    const px = Buffer.alloc(cellW * cellH * 4, 0);
    for (let cy = 0; cy < cellH; cy++) {
      for (let cx = 0; cx < cellW; cx++) {
        const k = cy * cellW + cx;
        const sxp = winX + cx;
        const syp = winY + cy;
        if (!isGround[k] && sxp >= 0 && syp >= 0 && sxp < W && syp < H) {
          const i = (syp * W + sxp) * C;
          const o = k * 4;
          px[o] = data[i];
          px[o + 1] = data[i + 1];
          px[o + 2] = data[i + 2];
          px[o + 3] = 255;
        }
      }
    }

    // ── Bleed the colour outward before feathering ───────────────────────────
    // A transparent pixel carries no colour, so a feathered edge over one blends
    // the silhouette toward black and rims the character. Growing the colour a
    // few pixels past the cut -- without touching alpha -- means the ramp blends
    // character into character and the rim never appears.
    for (let pass = 0; pass < BLEED_PASSES; pass++) {
      const before = Buffer.from(px);
      for (let cy = 0; cy < cellH; cy++) {
        for (let cx = 0; cx < cellW; cx++) {
          const o = (cy * cellW + cx) * 4;
          if (before[o + 3] === 0) {
            let r = 0;
            let g = 0;
            let b = 0;
            let n = 0;
            for (let dy = -1; dy <= 1; dy++) {
              for (let dx = -1; dx <= 1; dx++) {
                const nx = cx + dx;
                const ny = cy + dy;
                if (nx >= 0 && ny >= 0 && nx < cellW && ny < cellH) {
                  const q = (ny * cellW + nx) * 4;
                  if (before[q + 3] > 0) { r += before[q]; g += before[q + 1]; b += before[q + 2]; n++; }
                }
              }
            }
            if (n > 0) {
              px[o] = Math.round(r / n);
              px[o + 1] = Math.round(g / n);
              px[o + 2] = Math.round(b / n);
              // Alpha deliberately left at zero: this pass paints colour only.
            }
          }
        }
      }
    }

    // Feather the alpha, then write it back into the same buffer. Joining a
    // blurred channel onto a stripped image instead produces a four-band image
    // sharp does not read as RGBA -- the alpha is dropped and the resize with
    // it, silently, which is a hard failure to see in a finished sprite.
    const alpha = await sharp(px, { raw: { width: cellW, height: cellH, channels: 4 } })
      .extractChannel(3)
      .blur(FEATHER)
      .raw()
      .toBuffer();
    for (let k = 0; k < cellW * cellH; k++) px[k * 4 + 3] = alpha[k];

    const out = await sharp(px, { raw: { width: cellW, height: cellH, channels: 4 } })
      .resize(outW, outH, { fit: "fill", kernel: "lanczos3" })
      .webp({ quality: 92, alphaQuality: 100, effort: 6 })
      .toBuffer();

    const check = await sharp(out).metadata();
    if (!check.hasAlpha || check.width !== outW || check.height !== outH) {
      fail("frame " + cut.name + " encoded as " + check.width + "x" + check.height
        + " hasAlpha=" + check.hasAlpha + "; expected " + outW + "x" + outH + " with alpha.");
    }

    writeFileSync(join(OUT_DIR, cut.name + ".webp"), out);
    written.push({ name: cut.name, bytes: out.length });
  }

  // ── Manifest ──────────────────────────────────────────────────────────────
  for (const [clip, spec] of Object.entries(CLIPS)) {
    for (const f of spec.frames) {
      if (!cuts.some((c) => c.name === f)) fail('clip "' + clip + '" names frame "' + f + '", which the sheet does not contain.');
    }
  }

  const frameUnion = cuts.map((c) => '  | "' + c.name + '"').join("\n");
  const frameRows = cuts
    .map((c) => '  "' + c.name + '": { facing: "' + facingOf(c.name) + '", row: ' + c.row + ", col: " + c.col + " },")
    .join("\n");
  const clipRows = Object.entries(CLIPS)
    .map(([k, v]) => '  "' + k + '": {\n    note: ' + JSON.stringify(v.note)
      + ",\n    frames: [" + v.frames.map((f) => '"' + f + '"').join(", ")
      + "],\n    fps: " + v.fps + ",\n    loop: " + v.loop + ",\n    rest: " + v.rest + ",\n  },")
    .join("\n");

  const lines = [
    "/**",
    " * GENERATED FILE -- do not edit. Run `npm run build:sprites` to regenerate.",
    " *",
    " * Quartz's " + cuts.length + " frames, cut from `design/sprite_sheet.jpg` and registered",
    " * onto one character height and one ground line.",
    " *",
    " * Draw a frame at `aspect`, put `footY` of its height on the ground, and size",
    " * it so that `bodyH` of its height is the character. Every frame agrees about",
    " * all three, so swapping one for another moves nothing the artist did not draw",
    " * as moving -- `jump` and `fall` rise because their lift survives into the",
    " * image as transparent padding, not because anything offsets them at runtime.",
    " *",
    " * NEVER MIRROR A FRAME. The sheet draws its own left- and right-facing variants;",
    " * `facing` says which way each one looks. The microphone and the quavers are",
    " * drawn objects and read as reversed when flipped.",
    " */",
    "",
    "export type QuartzFrame =",
    frameUnion + ";",
    "",
    'export type QuartzFacing = "left" | "right" | "front";',
    "",
    "/** Cell geometry. Identical for every frame, which is what makes a swap invisible. */",
    "export const QUARTZ_CELL = {",
    "  width: " + outW + ",",
    "  height: " + outH + ",",
    "  /** width / height */",
    "  aspect: " + (outW / outH).toFixed(4) + ",",
    "  /** Where the ground line sits, as a fraction of cell height. */",
    "  footY: " + footY.toFixed(4) + ",",
    "  /** How much of the cell height the character is, at its tallest. */",
    "  bodyH: " + (OUT_BODY_PX / outH).toFixed(4) + ",",
    "} as const;",
    "",
    "export const QUARTZ_FRAMES: Record<QuartzFrame, { facing: QuartzFacing; row: number; col: number }> = {",
    frameRows,
    "};",
    "",
    "/**",
    " * Named sequences. `fps`, `loop` and `rest` are declared rather than measured --",
    " * frame timing is not in the artwork. `rest` is how many extra frame slots the",
    " * clip holds its last frame for, which is what stops a short clip reading as a",
    " * twitch.",
    " */",
    "export const QUARTZ_CLIPS = {",
    clipRows,
    "} as const;",
    "",
    "export type QuartzClipName = keyof typeof QUARTZ_CLIPS;",
    "",
    "/** The URL of one frame. */",
    "export const quartzSprite = (frame: QuartzFrame) => `" + PUBLIC_PREFIX + "/${frame}.webp`;",
    "",
  ];
  writeFileSync(MANIFEST, lines.join("\n"));

  const total = written.reduce((s, w) => s + w.bytes, 0);
  console.log("  " + written.length + " frames, " + (total / 1024).toFixed(0) + " KB total, largest "
    + Math.round(Math.max(...written.map((w) => w.bytes)) / 1024) + " KB");
  console.log("  -> " + OUT_DIR);
  console.log("  -> " + MANIFEST);
}

main();

/**
 * GENERATED FILE -- do not edit. Run `npm run build:sprites` to regenerate.
 *
 * Quartz's 20 frames, cut from `design/sprite_sheet.jpg` and registered
 * onto one character height and one ground line.
 *
 * Draw a frame at `aspect`, put `footY` of its height on the ground, and size
 * it so that `bodyH` of its height is the character. Every frame agrees about
 * all three, so swapping one for another moves nothing the artist did not draw
 * as moving -- `jump` and `fall` rise because their lift survives into the
 * image as transparent padding, not because anything offsets them at runtime.
 *
 * NEVER MIRROR A FRAME. The sheet draws its own left- and right-facing variants;
 * `facing` says which way each one looks. The microphone and the quavers are
 * drawn objects and read as reversed when flipped.
 */

export type QuartzFrame =
  | "idle-l"
  | "run-l1"
  | "run-l2"
  | "sing-l"
  | "idle-r"
  | "run-r1"
  | "run-r2"
  | "sing-r"
  | "idle-front"
  | "happy"
  | "wink"
  | "surprise"
  | "jump"
  | "fall"
  | "hurt"
  | "death"
  | "attack"
  | "victory"
  | "bow"
  | "applause";

export type QuartzFacing = "left" | "right" | "front";

/** Cell geometry. Identical for every frame, which is what makes a swap invisible. */
export const QUARTZ_CELL = {
  width: 401,
  height: 297,
  /** width / height */
  aspect: 1.3502,
  /** Where the ground line sits, as a fraction of cell height. */
  footY: 0.9703,
  /** How much of the cell height the character is, at its tallest. */
  bodyH: 0.8081,
} as const;

export const QUARTZ_FRAMES: Record<QuartzFrame, { facing: QuartzFacing; row: number; col: number }> = {
  "idle-l": { facing: "left", row: 0, col: 0 },
  "run-l1": { facing: "left", row: 0, col: 1 },
  "run-l2": { facing: "left", row: 0, col: 2 },
  "sing-l": { facing: "left", row: 0, col: 3 },
  "idle-r": { facing: "right", row: 1, col: 0 },
  "run-r1": { facing: "right", row: 1, col: 1 },
  "run-r2": { facing: "right", row: 1, col: 2 },
  "sing-r": { facing: "right", row: 1, col: 3 },
  "idle-front": { facing: "front", row: 2, col: 0 },
  "happy": { facing: "front", row: 2, col: 1 },
  "wink": { facing: "front", row: 2, col: 2 },
  "surprise": { facing: "front", row: 2, col: 3 },
  "jump": { facing: "front", row: 3, col: 0 },
  "fall": { facing: "front", row: 3, col: 1 },
  "hurt": { facing: "front", row: 3, col: 2 },
  "death": { facing: "front", row: 3, col: 3 },
  "attack": { facing: "front", row: 4, col: 0 },
  "victory": { facing: "front", row: 4, col: 1 },
  "bow": { facing: "front", row: 4, col: 2 },
  "applause": { facing: "front", row: 4, col: 3 },
};

/**
 * Named sequences. `fps`, `loop` and `rest` are declared rather than measured --
 * frame timing is not in the artwork. `rest` is how many extra frame slots the
 * clip holds its last frame for, which is what stops a short clip reading as a
 * twitch.
 */
export const QUARTZ_CLIPS = {
  "idle": {
    note: "front, facing the reader",
    frames: ["idle-front"],
    fps: 1,
    loop: false,
    rest: 0,
  },
  "blink": {
    note: "a wink, then back to front",
    frames: ["wink", "idle-front"],
    fps: 5,
    loop: false,
    rest: 0,
  },
  "run-left": {
    note: "two-frame gait, travelling left",
    frames: ["run-l1", "run-l2"],
    fps: 8,
    loop: true,
    rest: 0,
  },
  "run-right": {
    note: "two-frame gait, travelling right",
    frames: ["run-r1", "run-r2"],
    fps: 8,
    loop: true,
    rest: 0,
  },
  "sing": {
    note: "eyes shut, into the microphone",
    frames: ["sing-r"],
    fps: 1,
    loop: false,
    rest: 0,
  },
  "belt": {
    note: "the note lands -- flare, stars and all",
    frames: ["attack"],
    fps: 1,
    loop: false,
    rest: 0,
  },
  "cheer": {
    note: "delight, then both hands up",
    frames: ["happy", "victory"],
    fps: 3,
    loop: false,
    rest: 4,
  },
  "leap": {
    note: "up, over, and down",
    frames: ["jump", "fall"],
    fps: 6,
    loop: false,
    rest: 2,
  },
  "stumble": {
    note: "off the note, then flat on the floor",
    frames: ["hurt", "death"],
    fps: 2.5,
    loop: false,
    rest: 5,
  },
  "bow": {
    note: "taking the applause",
    frames: ["bow", "applause"],
    fps: 2.5,
    loop: false,
    rest: 4,
  },
  "startled": {
    note: "caught out",
    frames: ["surprise"],
    fps: 1,
    loop: false,
    rest: 0,
  },
} as const;

export type QuartzClipName = keyof typeof QUARTZ_CLIPS;

/** The URL of one frame. */
export const quartzSprite = (frame: QuartzFrame) => `/sprites/quartz/${frame}.webp`;

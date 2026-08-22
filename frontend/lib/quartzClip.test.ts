/**
 * Playing a clip, and the two ways a mascot goes wrong.
 *
 * A character that holds its last frame forever reads as broken rather than
 * still -- the cheer ends with both hands in the air and stays there. A
 * character that snaps back the instant its clip ends reads as a twitch. `rest`
 * is the thing between them, and it is the only part of the player with any
 * judgement in it.
 */
import { describe, expect, it } from "vitest";

import { QUARTZ_CLIPS } from "@/lib/quartzSprites";
import { clipDurationMs, frameAt, isSettled, REST_FRAME } from "@/lib/quartzClip";

// @spec UI-MASCOT-009
describe("a clip that does not loop", () => {
  it("plays its frames in order, one slot each", () => {
    // `cheer` is happy then victory at 3fps -- a slot is 1000/3 ms.
    expect(frameAt("cheer", 0)).toBe("happy");
    expect(frameAt("cheer", 100)).toBe("happy");
    expect(frameAt("cheer", 400)).toBe("victory");
  });

  it("holds its last frame for the slots it declares as rest, then settles", () => {
    const clip = QUARTZ_CLIPS.cheer;
    const slot = 1000 / clip.fps;
    // Two drawn frames, then four rest slots still showing the last one.
    expect(frameAt("cheer", slot * 2 + 1)).toBe("victory");
    expect(frameAt("cheer", slot * 5)).toBe("victory");
    // Past the rest, the character goes back to standing rather than staying
    // frozen with both hands up.
    expect(frameAt("cheer", slot * 6 + 1)).toBe(REST_FRAME);
  });

  it("reports when it has settled, so a caller can stop asking", () => {
    const slot = 1000 / QUARTZ_CLIPS.cheer.fps;
    expect(isSettled("cheer", 0)).toBe(false);
    expect(isSettled("cheer", slot * 5)).toBe(false);
    expect(isSettled("cheer", slot * 6 + 1)).toBe(true);
  });
});

// @spec UI-MASCOT-009
describe("a clip that loops", () => {
  it("never settles", () => {
    expect(isSettled("run-right", 0)).toBe(false);
    expect(isSettled("run-right", 1_000_000)).toBe(false);
  });

  it("wraps rather than running off the end", () => {
    const slot = 1000 / QUARTZ_CLIPS["run-right"].fps;
    expect(frameAt("run-right", 0)).toBe("run-r1");
    expect(frameAt("run-right", slot)).toBe("run-r2");
    expect(frameAt("run-right", slot * 2)).toBe("run-r1");
    expect(frameAt("run-right", slot * 2001)).toBe("run-r2");
  });

  it("has no duration", () => {
    expect(clipDurationMs("run-right")).toBe(Number.POSITIVE_INFINITY);
  });
});

// @spec UI-MASCOT-006, UI-MASCOT-007
describe("time before the clip starts", () => {
  it("shows the first frame rather than an empty cell", () => {
    // A negative elapsed time is what a caller gets from a clock that has been
    // adjusted, and a blank mascot is worse than an early one.
    expect(frameAt("cheer", -50)).toBe("happy");
  });
});

// @spec UI-MASCOT-007
describe("every declared clip", () => {
  it("names only frames the sheet contains, and settles somewhere sensible", () => {
    for (const name of Object.keys(QUARTZ_CLIPS) as (keyof typeof QUARTZ_CLIPS)[]) {
      const clip = QUARTZ_CLIPS[name];
      expect(clip.frames.length).toBeGreaterThan(0);
      expect(clip.fps).toBeGreaterThan(0);
      // The first frame is what a reduced-motion reader sees, so it has to be
      // the pose that carries the clip's meaning.
      expect(frameAt(name, 0)).toBe(clip.frames[0]);
    }
  });

  it("gives a non-looping clip a finite duration that covers its rest", () => {
    for (const name of Object.keys(QUARTZ_CLIPS) as (keyof typeof QUARTZ_CLIPS)[]) {
      const clip = QUARTZ_CLIPS[name];
      if (!clip.loop) {
        const slot = 1000 / clip.fps;
        expect(clipDurationMs(name)).toBeCloseTo(slot * (clip.frames.length + clip.rest), 6);
      }
    }
  });
});

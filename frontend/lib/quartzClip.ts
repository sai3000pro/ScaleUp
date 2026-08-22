/**
 * Which frame a clip is showing, given how long it has been playing.
 *
 * Pure, and it imports nothing but the generated manifest, because "what is the
 * mascot doing right now" is a question about a sequence and a number rather
 * than about the DOM. Time is a parameter and never a clock read, which is the
 * project's rule everywhere else and is what lets the whole player be asserted
 * on without a browser.
 *
 * The one piece of judgement here is `rest`. A clip that stops on its last
 * frame leaves the character mid-gesture forever -- the cheer ends with both
 * hands in the air and they stay up -- and a clip that snaps back the instant
 * its frames run out reads as a twitch. `rest` holds the last frame for a
 * declared number of slots and then hands back to a resting pose, which is what
 * makes a two-frame reaction read as a beat rather than a glitch.
 */
import { QUARTZ_CLIPS, type QuartzClipName, type QuartzFrame } from "@/lib/quartzSprites";

/**
 * Where a finished clip hands back to.
 *
 * Front-facing and empty-handed: it is the pose that follows anything. A clip
 * that should persist instead of settling is not a clip -- draw its frame
 * directly.
 */
export const REST_FRAME: QuartzFrame = "idle-front";

/** How long one frame is held, in milliseconds. */
function slotMs(clip: QuartzClipName): number {
  return 1000 / QUARTZ_CLIPS[clip].fps;
}

/**
 * How long the clip runs before it settles, including its rest.
 *
 * Infinite for a looping clip, which is the honest answer rather than a large
 * number: a caller that schedules against this must not be handed a moment a
 * run cycle supposedly ends.
 */
export function clipDurationMs(clip: QuartzClipName): number {
  const spec = QUARTZ_CLIPS[clip];
  if (spec.loop) return Number.POSITIVE_INFINITY;
  else return slotMs(clip) * (spec.frames.length + spec.rest);
}

/** Whether the clip has finished and handed back to the resting pose. */
export function isSettled(clip: QuartzClipName, elapsedMs: number): boolean {
  return elapsedMs >= clipDurationMs(clip);
}

/**
 * The frame to draw.
 *
 * A negative elapsed time -- which is what a caller gets from a clock that has
 * been adjusted, or from a start time scheduled slightly ahead -- shows the
 * first frame rather than nothing. A blank mascot is a worse answer than an
 * early one.
 */
export function frameAt(clip: QuartzClipName, elapsedMs: number): QuartzFrame {
  const spec = QUARTZ_CLIPS[clip];
  const frames = spec.frames as readonly QuartzFrame[];
  if (elapsedMs <= 0) return frames[0];

  const index = Math.floor(elapsedMs / slotMs(clip));
  if (spec.loop) {
    return frames[index % frames.length];
  } else if (index < frames.length) {
    return frames[index];
  } else if (index < frames.length + spec.rest) {
    return frames[frames.length - 1];
  } else {
    return REST_FRAME;
  }
}

"use client";

/**
 * Quartz: a quarter note with a microphone, and the only character in the app.
 *
 * It appears beside the wordmark on every authenticated view and several times
 * over on the landing page, at sizes from 30px to 200px, and it is the same
 * creature at all of them — the frames are registered onto one character height
 * and one ground line, so a size is a number rather than a separate asset.
 *
 * ── WHAT IT DOES ────────────────────────────────────────────────────────────
 *   rest       the frame the server painted, and the frame it returns to.
 *   greeting   hovering or focusing it plays a reaction, once.
 *   activated  clicking it plays a bigger one.
 * Nothing it does changes anything. That is deliberate: a character that gated
 * a real action would make charm load-bearing, and a reader who turns off
 * animation would lose function rather than delight.
 *
 * ── TWO RULES THAT LOOK LIKE DETAILS ────────────────────────────────────────
 * THE SERVER PAINTS THE RESTING FRAME, and so does the first client render, so
 * there is no swap at hydration and no hole while a sprite is fetched.
 * `usePrefersReducedMotion` starts false on the server, so it is consulted only
 * to decide whether to START motion — never to choose what to render.
 *
 * NEVER MIRROR A FRAME IN CSS. `scale: -1 1` reverses the microphone and the
 * quavers, which are drawn objects. Both facings ship as separate files; pick
 * one by name.
 * ────────────────────────────────────────────────────────────────────────────
 *
 * @spec UI-MASCOT-001, UI-MASCOT-002, UI-MASCOT-003, UI-MASCOT-004
 * @spec UI-MASCOT-005, UI-MASCOT-006, UI-MASCOT-007, UI-MASCOT-008
 * @spec UI-MASCOT-009, UI-MASCOT-010, UI-MASCOT-011
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { clipDurationMs, frameAt } from "@/lib/quartzClip";
import {
  QUARTZ_CELL,
  QUARTZ_CLIPS,
  quartzSprite,
  type QuartzClipName,
  type QuartzFrame,
} from "@/lib/quartzSprites";

export interface QuartzProps {
  /** The character's height in CSS px. The cell around it is derived. */
  size?: number;
  /** The pose it holds when nothing is happening. */
  rest?: QuartzFrame;
  /** Played once when the pointer enters or it takes focus. */
  greet?: QuartzClipName;
  /** Played once when it is clicked or activated by keyboard. */
  react?: QuartzClipName;
  /** Played on a loop from mount. Overrides `rest` until it is interrupted. */
  loop?: QuartzClipName;
  /** Describes the mascot where it is not decorative. Omit beside a wordmark. */
  label?: string;
  className?: string;
}

/**
 * How often a resting mascot looks up from what it is doing.
 *
 * Re-randomised each time rather than fixed: an idle animation on a metronome
 * is the tell that it is a loop and not a creature.
 */
const IDLE_MIN_MS = 5200;
const IDLE_SPREAD_MS = 6500;

/** Every frame a reaction can reach, so a first interaction never shows a gap. */
function framesOf(clip: QuartzClipName | undefined): readonly QuartzFrame[] {
  if (!clip) return [];
  else return QUARTZ_CLIPS[clip].frames as readonly QuartzFrame[];
}

export function Quartz({
  size = 40,
  rest = "idle-front",
  greet,
  react,
  loop,
  label,
  className = "",
}: QuartzProps) {
  const reduced = usePrefersReducedMotion();
  /** The clip in flight and when it started, or null while at rest. */
  const [playing, setPlaying] = useState<{ clip: QuartzClipName; startedAt: number } | null>(null);
  const [frame, setFrame] = useState<QuartzFrame>(rest);
  const preloaded = useRef(false);

  const interactive = Boolean(greet || react);
  /**
   * A mascot with a name is a control: focusable, activatable, announced. One
   * without a name sits beside a wordmark that already names the destination
   * (`UI-MASCOT-005`), so it stays decoration that happens to react to a
   * pointer -- giving it a role AND hiding it from assistive technology would
   * be a contradiction, and giving it a tab stop would make the reader press
   * Tab twice to pass one link.
   */
  const isControl = interactive && Boolean(label);

  // ── Preloading ────────────────────────────────────────────────────────────
  // Only the frames this instance can actually reach, and only once. A mascot
  // that greets and reacts pulls four or five files; the whole set is twenty.
  const preload = useCallback(() => {
    if (preloaded.current || typeof document === "undefined") return;
    preloaded.current = true;
    for (const f of new Set([...framesOf(greet), ...framesOf(react), ...framesOf(loop)])) {
      const img = new Image();
      img.src = quartzSprite(f);
    }
  }, [greet, react, loop]);

  const play = useCallback(
    (clip: QuartzClipName | undefined) => {
      preload();
      // Under reduced motion the character still changes pose — which pose it
      // holds is information — but it does not animate between them.
      if (!clip) return;
      else if (reduced) setFrame(QUARTZ_CLIPS[clip].frames[0] as QuartzFrame);
      else setPlaying({ clip, startedAt: performance.now() });
    },
    [preload, reduced],
  );

  // ── The clip in flight ────────────────────────────────────────────────────
  // One rAF loop that lives exactly as long as the clip does. A looping clip
  // never ends, so it runs until the component unmounts or something
  // interrupts it.
  useEffect(() => {
    if (!playing || reduced) return;
    let raf = 0;
    const duration = clipDurationMs(playing.clip);
    const tick = () => {
      const elapsed = performance.now() - playing.startedAt;
      // On the last tick, hand back to THIS instance's resting pose rather than
      // the player's generic one: a mark that rests facing right would
      // otherwise flash front for a frame as the clip lets go.
      if (elapsed >= duration) {
        setFrame(rest);
        setPlaying(null);
      } else {
        setFrame(frameAt(playing.clip, elapsed));
        raf = requestAnimationFrame(tick);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, reduced, rest]);

  // Back to the declared resting pose whenever nothing is in flight, so a
  // changed `rest` prop is honoured and a finished clip does not linger.
  useEffect(() => {
    if (!playing) setFrame(rest);
  }, [playing, rest]);

  // A loop starts itself. Under reduced motion it holds its first frame, which
  // is a pose rather than a still of an animation.
  useEffect(() => {
    if (!loop) return;
    else if (reduced) setFrame(QUARTZ_CLIPS[loop].frames[0] as QuartzFrame);
    else setPlaying({ clip: loop, startedAt: performance.now() });
  }, [loop, reduced]);

  // ── Looking alive while resting ───────────────────────────────────────────
  // Only when it is plainly idle: glancing up in the middle of a wave reads as
  // a glitch, and a looping clip is already busy.
  useEffect(() => {
    if (playing || loop || reduced || !interactive) return;
    let timer: ReturnType<typeof setTimeout>;
    const glance = () => {
      setPlaying({ clip: "blink", startedAt: performance.now() });
      timer = setTimeout(glance, IDLE_MIN_MS + Math.random() * IDLE_SPREAD_MS);
    };
    timer = setTimeout(glance, IDLE_MIN_MS + Math.random() * IDLE_SPREAD_MS);
    return () => clearTimeout(timer);
  }, [playing, loop, reduced, interactive]);

  // ── Geometry ──────────────────────────────────────────────────────────────
  // `size` is the CHARACTER's height, not the box's. The cell is taller than the
  // drawing — headroom for raised hands and the flare — so the box is inflated
  // by exactly the fraction of it that is character.
  const boxH = size / QUARTZ_CELL.bodyH;
  const style = {
    "--quartz-h": `${boxH}px`,
    "--quartz-w": `${boxH * QUARTZ_CELL.aspect}px`,
    "--quartz-foot": `${QUARTZ_CELL.footY}`,
  } as React.CSSProperties;

  const handlers = interactive
    ? {
        onPointerEnter: () => play(greet),
        onFocus: () => play(greet),
        onClick: () => play(react ?? greet),
        onKeyDown: (e: React.KeyboardEvent) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            play(react ?? greet);
          }
        },
      }
    : {};

  return (
    <span
      className={`quartz ${className}`}
      style={style}
      data-playing={playing?.clip}
      // Interactive but purely decorative, so it is a button to the keyboard and
      // nothing to a screen reader unless it was given a name.
      role={isControl ? "button" : undefined}
      tabIndex={isControl ? 0 : undefined}
      aria-label={label}
      aria-hidden={isControl ? undefined : true}
      {...handlers}
    >
      {/* A raw <img>: these are encoded at a quality chosen against the artwork,
          and the framework's image pipeline would re-encode them and throw that
          away. They are already the size they are drawn at. */}
      <img
        src={quartzSprite(frame)}
        alt=""
        aria-hidden
        draggable={false}
        width={QUARTZ_CELL.width}
        height={QUARTZ_CELL.height}
        decoding="sync"
        className="quartz__sprite"
      />
    </span>
  );
}

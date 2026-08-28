/**
 * Shared interaction and surface classes.
 *
 * These exist because the same element was being styled four slightly different
 * ways across four files -- and because no button in the app had any focus
 * style at all, so keyboard users got the browser default on some controls and
 * nothing distinguishable on others.
 *
 * Written as literal strings, never interpolated: Tailwind's JIT scans source
 * text, so a class name assembled from a variable is simply never generated.
 *
 * The ramps these classes name are inverted in app/globals.css, so `slate-950`
 * is the page white and `slate-100` is near-black ink. Read every class here in
 * that direction. Contrast for the colours named below is asserted, not
 * asserted-by-eye, in lib/theme.test.ts.
 *
 * @spec UI-SYS-001, UI-SYS-002, UI-SYS-003
 */

/**
 * Visible keyboard focus. `focus-visible` so a mouse click does not ring.
 *
 * @spec UI-A11Y-001, UI-A11Y-002
 */
export const FOCUS_RING =
  "outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 " +
  "focus-visible:ring-offset-slate-950";

/** Primary action. One definition, so every primary button matches. */
export const BUTTON_PRIMARY =
  "rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-slate-950 transition " +
  "hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS_RING;

/** Secondary / quieter action on a raised surface. */
export const BUTTON_SECONDARY =
  "rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm font-semibold text-slate-200 " +
  "transition hover:border-slate-600 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS_RING;

/**
 * A live, stoppable action: recording, a take in progress.
 *
 * Solid rather than tinted, because it is the primary control of the panel it
 * sits in and it has to be findable at a glance while someone is holding an
 * instrument. The rose fill is the same one `BUTTON_PRIMARY` uses inverted, so
 * "start" and "stop" read as one control changing state rather than two
 * different buttons.
 *
 * @spec UI-A11Y-008
 */
export const BUTTON_RECORDING =
  "rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold text-slate-950 transition " +
  "hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50 " +
  FOCUS_RING;

/** Text input / textarea. */
export const INPUT =
  "w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 " +
  "placeholder:text-slate-500 focus:border-sky-500 " +
  FOCUS_RING;

/** A raised panel: cards, the inspector, the upload box. */
export const CARD = "rounded-xl border border-slate-800 bg-slate-900/50 p-4";

/** Inline nav / low-emphasis text button. */
export const NAV_LINK = "rounded-sm hover:text-slate-200 " + FOCUS_RING;

/**
 * Muted body copy.
 *
 * `slate-400` is the quietest ink that clears 4.5:1 against BOTH the page and a
 * raised card -- and the card is the one that matters, since that is where most
 * muted text in the app sits. `slate-500` clears it on both too, but only just,
 * so it is the floor rather than the default; `slate-600` and lighter are
 * surface colours, not ink.
 *
 * This constant is currently used nowhere, while `text-slate-500` appears
 * directly in 58 places. Tracked as UI-SYS-004.
 *
 * @spec UI-A11Y-007
 */
export const MUTED = "text-slate-400";

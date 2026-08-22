/**
 * Every figure and claim the landing page states, and where each one came from.
 *
 * The project's tenet is that the public page claims only what the product
 * already does. This module is where that stops being a sentence in a design
 * document: a claim is a record with a mandatory `source`, so one without
 * provenance does not compile, and the page renders the source next to the claim
 * so a reader can check it without reading this file.
 *
 * ── THE PAGE NAMES NOBODY ───────────────────────────────────────────────────
 * It describes what is hard about hearing a performance, never who has failed
 * at it. Naming another project to make a point about difficulty is a cheap
 * argument and a discourtesy, and a reader who came to find out what this thing
 * does did not come to read about somebody else's repository.
 *
 * Everything below is either a property of the problem — true of any system
 * that tries this — or a property of this one, cited to the file that
 * implements it.
 * ────────────────────────────────────────────────────────────────────────────
 */

/** One stated quantity. `source` is not optional and has no default. */
export interface Figure {
  /** Stable handle, so a claim on the page can be traced back to this entry. */
  id: string;
  /** The number as it is set on the page. */
  value: string;
  /** What it counts. */
  label: string;
  /** Where it can be checked. */
  source: string;
}

/** One reason hearing a performance well enough to coach it is hard. */
export interface HardPart {
  id: string;
  /** The difficulty, in the fewest words that still carry it. */
  title: string;
  /** Why a reasonable first attempt gets this wrong. */
  problem: string;
  /** What this system does instead. */
  answer: string;
  /** The file the answer can be checked in. */
  source: string;
}

/**
 * What this system measures and holds.
 *
 * Counted from the curricula and evaluators here rather than rounded up: six
 * published curricula hold 7 + 9 + 10 + 11 + 8 + 8 skills.
 */
export const SYSTEM_FIGURES: readonly Figure[] = [
  {
    id: "instruments",
    value: "6",
    label: "instruments with a published, versioned curriculum",
    source: "backend/app/curricula/",
  },
  {
    id: "skills",
    value: "53",
    label: "skills across those six prerequisite graphs",
    source: "backend/app/curricula/{piano,guitar,violin,trumpet,drums,banjo}.json",
  },
  {
    id: "dimensions",
    value: "4",
    label: "dimensions scored in a take — pitch, rhythm, dynamics, technique",
    source: "backend/app/evaluation/registry.py",
  },
  {
    id: "posture",
    value: "16",
    label: "posture rules, each declaring the landmarks it needs to be honest",
    source: "frontend/lib/posture.ts",
  },
  {
    id: "keys",
    value: "0",
    label: "API keys needed to record a take and be graded on it",
    source: "backend/app/llm/registry.py — LLM_PROVIDER=fake is the default",
  },
];

/**
 * Why this is hard.
 *
 * Four properties of the problem, each with the thing this system does about
 * it. None of them is a claim about anybody else's work — they are what the
 * domain does to anyone who tries, and the reason a naive version of this is
 * easy to build and useless to practise with.
 */
export const HARD_PARTS: readonly HardPart[] = [
  {
    id: "cents",
    title: "The nearest note is not close enough",
    problem:
      "Round what you played to the nearest semitone and almost everything comes back correct. A note a quarter-tone flat rounds to the right name and passes. That is the entire problem a string player has, and it is invisible at that resolution.",
    answer:
      "Intonation is measured in cents against the written pitch, so being nearly right is a number rather than a pass. Fifty cents is a quarter-tone; the failure threshold sits at half of that.",
    source: "backend/app/evaluation/violin.py",
  },
  {
    id: "timing",
    title: "Right note, wrong moment",
    problem:
      "Line your notes up against the score one for one and time disappears. Play the passage perfectly but a beat late and nothing objects. Compare strictly by the clock instead and playing it slowly to get it right becomes an error.",
    answer:
      "Takes are aligned elastically against the score rather than compared position by position, so a slow tempo and a wrong rhythm stop being the same mistake.",
    source: "backend/app/evaluation/dtw.py",
  },
  {
    id: "dynamics",
    title: "Loud is a property of your room",
    problem:
      "Absolute level tells you about the microphone, how far away you sat, and the size of the room. Score it directly and moving your laptop counts as a change in your playing.",
    answer:
      "Levels are centred on your own take and dynamics are scored as rank agreement — did the crescendo actually happen — which no amount of gain can flatter.",
    source: "backend/app/evaluation/dynamics.py",
  },
  {
    id: "honesty",
    title: "A number that measures nothing looks exactly like one that does",
    problem:
      "Silence, a hand out of frame, a hip the camera cannot see. The tempting thing is to score it anyway, because a grade with a gap in it feels broken — and nobody can tell the difference by looking.",
    answer:
      "An unmeasured dimension is reported as absent and the rest are renormalised around it. A drummer is not marked down for pitch. Nothing is scored zero because it was not observed.",
    source: "backend/app/evaluation/registry.py",
  },
];

/** Everything the page may state as a number, in one list. */
export const EVIDENCE: readonly Figure[] = SYSTEM_FIGURES;

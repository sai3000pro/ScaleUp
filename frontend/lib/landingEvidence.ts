/**
 * Every figure the landing page states, and where each one came from.
 *
 * The project's tenet is that the public page claims only what the product
 * already does. This module is where that stops being a sentence in a design
 * document: a figure is a record with a mandatory `source`, so a claim without
 * provenance does not compile, and the page renders the source next to the
 * number so a reader can check it without reading this file.
 *
 * ── WHY THERE ARE NO MARKET STATISTICS HERE ─────────────────────────────────
 * The three prior attempts this page cites -- music-maestro, MusicTeacher and
 * vocal-ai -- were read for figures on what coaching costs: lesson prices,
 * teacher supply, how many learners give up. They contain none. They are three
 * hackathon projects, and what they hold is problem statements and DSP
 * thresholds.
 *
 * So the cost argument is made from what a tutor *does* rather than from a
 * price, and every quantity below is drawn from this repository. The slot for a
 * sourced market figure is open and deliberately empty: adding a
 * plausible-looking one would be exactly the failure this module exists to
 * prevent, and a reader who checks one claim and finds it invented discounts
 * every other claim on the page.
 * ────────────────────────────────────────────────────────────────────────────
 */

/**
 * One stated quantity.
 *
 * `source` is not optional and has no default. That is the whole mechanism.
 */
export interface Figure {
  /** Stable handle, so a claim on the page can be traced back to this entry. */
  id: string;
  /** The number as it is set on the page. */
  value: string;
  /** What it counts. */
  label: string;
  /** Where it can be checked. A path in this repository, or a named outside source. */
  source: string;
}

/** One prior attempt at this product, and the specific thing it could not do. */
export interface PriorAttempt {
  repo: string;
  /** What it set out to be, in its own terms. */
  premise: string;
  /** The file the finding can be checked in. */
  file: string;
  /** What the code actually does. */
  finding: string;
  /** What that leaves unmeasured -- the point of the section. */
  missing: string;
}

/**
 * What this system measures and holds.
 *
 * Counted from the curricula and evaluators in this repository rather than
 * rounded up: six published curricula hold 7 + 9 + 10 + 11 + 8 + 8 skills.
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
    id: "cents",
    value: "±1 cent",
    label: "the resolution intonation is reported at, rather than to the nearest semitone",
    source: "backend/app/evaluation/violin.py",
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
    label: "API keys required to record a take and be graded on it",
    source: "backend/app/llm/registry.py — LLM_PROVIDER=fake is the default",
  },
];

/**
 * Three teams built an AI music coach. What each one could not hear.
 *
 * Every finding below was read out of the named file in the sibling repository,
 * not inferred from its README. The section argues that this problem is hard,
 * and it would be self-defeating to argue that with a characterisation.
 */
export const PRIOR_ART: readonly PriorAttempt[] = [
  {
    repo: "music-maestro",
    premise: "An AI-guided vocal coach giving instant feedback in the absence of a teacher.",
    file: "static/js/script.js",
    finding:
      "A note is scored by rounding the detected pitch to the nearest semitone and comparing it to the target — Math.round(midiNum) == current_note.pitch — then incrementing a counter.",
    missing:
      "There is no cents figure, no onset and no duration. A note 49 cents flat scores exactly like a perfect one, and a note played at the wrong moment scores exactly like one in time.",
  },
  {
    repo: "MusicTeacher",
    premise: "Upload a video of yourself playing; get feedback on style, tempo and technique.",
    file: "backend/services/ai_services.py",
    finding:
      "The scoring path returns np.random.uniform(7.0, 9.5) for pitch, with comparable draws for rhythm and dynamics.",
    missing:
      "The number is not a measurement of anything. The rubric around it is real; the grade inside it is a random draw, and it looks exactly like a grade.",
  },
  {
    repo: "vocal-ai",
    premise: "Real-time voice analysis with a conversational coach that remembers your progress.",
    file: "backend/enhanced_letta_service.py",
    finding:
      "It carries genuine vocal science — jitter above 0.020 and shimmer above 0.025 read as strain, vibrato sits optimally near 5.5–6 Hz — and its fallback analyzer invents metrics when the real one is unavailable.",
    missing:
      "The invented metrics are persisted like measured ones, so a session that was never analysed becomes a data point in the learner's own trend.",
  },
];

/** Everything the page may state as a number, in one list. */
export const EVIDENCE: readonly Figure[] = SYSTEM_FIGURES;

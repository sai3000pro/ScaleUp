/**
 * Turning a stream of per-frame pitch readings into discrete note events.
 *
 * This is the layer a pitch detector does not give you. CREPE (and the
 * autocorrelation fallback) answer "what pitch is sounding right now" every few
 * milliseconds; nothing in that answer says where one note ends and the next
 * begins. Reference implementations skip this entirely by knowing the reference
 * timeline in advance and asking only "is the right note sounding during this
 * window" — which cannot score a performance the learner plays freely, and
 * cannot detect an extra note at all.
 *
 * Pure and frame-driven: `pushFrame` takes a state and one reading and returns
 * a new state. No audio, no timers, no closures over a live analyser. That is
 * what makes every threshold below testable against synthetic frames, and it is
 * why the streaming coach can replay a buffer through this and land on a
 * bit-identical state.
 *
 * The pipeline, in order:
 *   median filter → amplitude + confidence gate → onset → sustain → note-off
 */

import type { PerformedNote } from "@/lib/types";

export interface PitchFrame {
  /** Seconds since capture started. */
  timeSeconds: number;
  /** Fractional MIDI pitch, or null when no pitch was detected. */
  midiExact: number | null;
  /** 0..1 detector confidence (CREPE activation peak, or autocorrelation clarity). */
  confidence: number;
  /** Frame level in dBFS, floored at RMS_FLOOR_DB. */
  rmsDb: number;
}

export interface NoteSegment extends PerformedNote {
  pitch_midi: number;
  /** (-50, +50]. The residual CREPE computes and most wrappers throw away. */
  cents_deviation: number;
  onset_seconds: number;
  duration_seconds: number;
  confidence: number;
  peak_level_db: number;
  mean_level_db: number;
}

export interface SegmenterConfig {
  minNoteDurationSeconds: number;
  pitchChangeFrames: number;
  confidenceOn: number;
  confidenceOff: number;
  pitchMedianWindow: number;
  noteOnRmsDb: number;
  noteOffRmsDb: number;
  noteOffFrames: number;
  reattackRiseDb: number;
  reattackWindowFrames: number;
}

/**
 * The first three are carried over from the autocorrelation segmenter this
 * replaces, where they were tuned against real takes. The rest are new, and
 * genuinely are guesses — they are the first things to calibrate once there are
 * recordings to calibrate against.
 */
export const DEFAULT_SEGMENTER_CONFIG: SegmenterConfig = {
  minNoteDurationSeconds: 0.12,
  pitchChangeFrames: 6,
  confidenceOn: 0.55,
  // Hysteresis: a note has to be *more* convincing to start than to continue.
  // A single threshold makes a decaying piano note flicker on and off at the
  // boundary, and each flicker becomes a spurious extra note in the score.
  confidenceOff: 0.4,
  pitchMedianWindow: 5,
  noteOnRmsDb: -45,
  noteOffRmsDb: -52,
  noteOffFrames: 3,
  reattackRiseDb: 6,
  reattackWindowFrames: 4,
};

export const RMS_FLOOR_DB = -100;

interface OpenNote {
  midiSum: number;
  frames: number;
  confidenceSum: number;
  onsetSeconds: number;
  lastSeconds: number;
  peakDb: number;
  levelSum: number;
  quietFrames: number;
  midiValues: number[];
}

export interface SegmenterState {
  readonly frames: readonly PitchFrame[];
  readonly recent: readonly number[];
  readonly recentDb: readonly number[];
  readonly open: OpenNote | null;
  readonly pendingChange: number;
  readonly completed: readonly NoteSegment[];
}

export function initialSegmenterState(): SegmenterState {
  return { frames: [], recent: [], recentDb: [], open: null, pendingChange: 0, completed: [] };
}

function median(values: readonly number[]): number {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 === 1 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

function closeNote(
  open: OpenNote,
  endSeconds: number,
  config: SegmenterConfig,
): NoteSegment | null {
  const duration = endSeconds - open.onsetSeconds;
  if (duration < config.minNoteDurationSeconds) return null;

  // Median rather than mean: one octave-flip frame would drag a mean far enough
  // to change the reported semitone, and the whole note with it.
  const midiExact = median(open.midiValues);
  const rounded = Math.round(midiExact);
  return {
    pitch_midi: rounded,
    cents_deviation: Math.round((midiExact - rounded) * 100 * 10) / 10,
    onset_seconds: Math.round(open.onsetSeconds * 1000) / 1000,
    duration_seconds: Math.round(duration * 1000) / 1000,
    confidence: Math.min(1, open.confidenceSum / Math.max(1, open.frames)),
    peak_level_db: Math.round(open.peakDb * 10) / 10,
    mean_level_db: Math.round((open.levelSum / Math.max(1, open.frames)) * 10) / 10,
    string: null,
    fret: null,
  };
}

/** Fold one frame into the state. Never mutates its argument. */
// @spec OBS-NOTE-001, OBS-NOTE-002, OBS-NOTE-003, OBS-NOTE-004, OBS-NOTE-005, OBS-NOTE-007, OBS-NOTE-011
export function pushFrame(
  state: SegmenterState,
  frame: PitchFrame,
  overrides: Partial<SegmenterConfig> = {},
): SegmenterState {
  const config = { ...DEFAULT_SEGMENTER_CONFIG, ...overrides };
  const recent = [...state.recent, frame.midiExact ?? Number.NaN].slice(-config.pitchMedianWindow);
  const recentDb = [...state.recentDb, frame.rmsDb].slice(-config.reattackWindowFrames);
  const usable = recent.filter((value) => Number.isFinite(value));

  const open = state.open;
  const completed = [...state.completed];
  let nextOpen: OpenNote | null = open;
  let pendingChange = state.pendingChange;

  // A note is "sounding" when the detector is confident AND there is enough
  // level. Requiring both is what keeps room tone with an accidental periodicity
  // from becoming a note.
  const gateOn = frame.confidence >= config.confidenceOn && frame.rmsDb >= config.noteOnRmsDb;
  const gateSustain = frame.confidence >= config.confidenceOff && frame.rmsDb >= config.noteOffRmsDb;
  const sounding = open === null ? gateOn : gateSustain;
  const smoothed = usable.length > 0 ? median(usable) : null;

  if (!sounding || smoothed === null || frame.midiExact === null) {
    if (open !== null) {
      const quiet = open.quietFrames + 1;
      if (quiet >= config.noteOffFrames) {
        const segment = closeNote(open, frame.timeSeconds, config);
        if (segment !== null) completed.push(segment);
        nextOpen = null;
      } else {
        nextOpen = { ...open, quietFrames: quiet };
      }
    }
    pendingChange = 0;
  } else {
    const semitone = Math.round(smoothed);
    // Two ways a new note starts: the pitch changed and held, or the level
    // jumped. Without the second, two identical repeated notes merge into one
    // long note — the detector cannot see a re-attack in pitch alone.
    const priorDb = recentDb.length > 1 ? Math.min(...recentDb.slice(0, -1)) : frame.rmsDb;
    const reattack = open !== null && frame.rmsDb - priorDb >= config.reattackRiseDb;

    if (open === null) {
      nextOpen = openNote(semitone, smoothed, frame);
      pendingChange = 0;
    } else if (semitone !== Math.round(median(open.midiValues)) || reattack) {
      pendingChange = reattack ? config.pitchChangeFrames : pendingChange + 1;
      if (pendingChange >= config.pitchChangeFrames) {
        const segment = closeNote(open, frame.timeSeconds, config);
        if (segment !== null) completed.push(segment);
        nextOpen = openNote(semitone, smoothed, frame);
        pendingChange = 0;
      } else {
        nextOpen = sustain(open, smoothed, frame);
      }
    } else {
      nextOpen = sustain(open, smoothed, frame);
      pendingChange = 0;
    }
  }

  return {
    frames: [...state.frames, frame].slice(-4),
    recent,
    recentDb,
    open: nextOpen,
    pendingChange,
    completed,
  };
}

function openNote(semitone: number, midiExact: number, frame: PitchFrame): OpenNote {
  void semitone;
  return {
    midiSum: midiExact,
    frames: 1,
    confidenceSum: frame.confidence,
    onsetSeconds: frame.timeSeconds,
    lastSeconds: frame.timeSeconds,
    peakDb: frame.rmsDb,
    levelSum: frame.rmsDb,
    quietFrames: 0,
    midiValues: [midiExact],
  };
}

function sustain(open: OpenNote, midiExact: number, frame: PitchFrame): OpenNote {
  return {
    ...open,
    midiSum: open.midiSum + midiExact,
    frames: open.frames + 1,
    confidenceSum: open.confidenceSum + frame.confidence,
    lastSeconds: frame.timeSeconds,
    peakDb: Math.max(open.peakDb, frame.rmsDb),
    levelSum: open.levelSum + frame.rmsDb,
    quietFrames: 0,
    midiValues: [...open.midiValues, midiExact],
  };
}

/** Close any open note and return every segment, onsets rebased to the first. */
// @spec OBS-NOTE-006, OBS-NOTE-008, OBS-NOTE-009, OBS-NOTE-010
export function finalizeSegments(
  state: SegmenterState,
  endTimeSeconds: number,
  overrides: Partial<SegmenterConfig> = {},
): NoteSegment[] {
  const config = { ...DEFAULT_SEGMENTER_CONFIG, ...overrides };
  const segments = [...state.completed];
  if (state.open !== null) {
    const last = closeNote(state.open, endTimeSeconds, config);
    if (last !== null) segments.push(last);
  }
  if (segments.length === 0) return [];

  // Rebase onto the first note so a silence before the learner starts playing
  // does not read as rushing the whole piece.
  const origin = segments[0].onset_seconds;
  return segments.map((segment) => ({
    ...segment,
    onset_seconds: Math.round((segment.onset_seconds - origin) * 1000) / 1000,
  }));
}

/** Convenience for tests: run a whole frame list through in one call. */
export function segmentFrames(
  frames: readonly PitchFrame[],
  overrides: Partial<SegmenterConfig> = {},
): NoteSegment[] {
  let state = initialSegmenterState();
  for (const frame of frames) {
    state = pushFrame(state, frame, overrides);
  }
  const end = frames.length > 0 ? frames[frames.length - 1].timeSeconds : 0;
  return finalizeSegments(state, end, overrides);
}

export type MockPattern =
  | "stepwise"
  | "repeated-same-pitch"
  | "vibrato"
  | "octave-glitch"
  | "silence"
  | "short-blip"
  | "crescendo";

/**
 * Deterministic frame fixtures, mirroring `mockHandLandmarks` in technique.ts.
 * They exist so every threshold above has a test that fails when it moves.
 */
export function mockPitchFrames(pattern: MockPattern, hopSeconds = 0.016): PitchFrame[] {
  const frames: PitchFrame[] = [];
  const push = (time: number, midi: number | null, confidence: number, db: number) =>
    frames.push({ timeSeconds: time, midiExact: midi, confidence, rmsDb: db });

  const framesPerNote = Math.round(0.4 / hopSeconds);
  if (pattern === "silence") {
    for (let index = 0; index < 60; index += 1) push(index * hopSeconds, null, 0, RMS_FLOOR_DB);
  } else if (pattern === "short-blip") {
    for (let index = 0; index < 4; index += 1) push(index * hopSeconds, 60, 0.9, -20);
    for (let index = 4; index < 30; index += 1) push(index * hopSeconds, null, 0, RMS_FLOOR_DB);
  } else if (pattern === "stepwise") {
    [60, 62, 64, 65].forEach((midi, note) => {
      for (let index = 0; index < framesPerNote; index += 1) {
        push((note * framesPerNote + index) * hopSeconds, midi + 0.12, 0.9, -20);
      }
    });
  } else if (pattern === "repeated-same-pitch") {
    // Same pitch twice, with a level dip and a fresh attack between them.
    for (let note = 0; note < 2; note += 1) {
      for (let index = 0; index < framesPerNote; index += 1) {
        const decay = -18 - (index / framesPerNote) * 14;
        push((note * framesPerNote + index) * hopSeconds, 60, 0.9, index === 0 ? -18 : decay);
      }
    }
  } else if (pattern === "vibrato") {
    for (let index = 0; index < framesPerNote * 2; index += 1) {
      const wobble = 0.35 * Math.sin(index * 0.6);
      push(index * hopSeconds, 69 + wobble, 0.9, -20);
    }
  } else if (pattern === "octave-glitch") {
    for (let index = 0; index < framesPerNote; index += 1) {
      // One frame reads an octave low, exactly the CREPE failure the median
      // filter exists to absorb.
      push(index * hopSeconds, index === 10 ? 48 : 60, 0.9, -20);
    }
  } else if (pattern === "crescendo") {
    [60, 62, 64, 65].forEach((midi, note) => {
      for (let index = 0; index < framesPerNote; index += 1) {
        push((note * framesPerNote + index) * hopSeconds, midi, 0.9, -40 + note * 7);
      }
    });
  }
  return frames;
}

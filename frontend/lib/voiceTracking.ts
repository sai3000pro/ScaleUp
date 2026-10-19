/**
 * Polyphonic segmentation: one shared-segmenter track per sounding voice.
 *
 * The note segmenter in `noteSegmentation.ts` turns a stream of single pitch
 * frames into notes. A chord is several such streams at once, so each detected
 * voice is routed to the track whose pitch it continues (within a semitone), a
 * voice nothing continues opens a new track, and a track that hears nothing
 * this frame receives a silent frame so the segmenter closes its note on the
 * same terms a monophonic rest would. Every decision about what is a note stays
 * in the segmenter; this module only decides which stream a voice belongs to.
 */

import {
  DEFAULT_SEGMENTER_CONFIG,
  finalizeSegments,
  initialSegmenterState,
  pushFrame,
  type NoteSegment,
  type PitchFrame,
  type SegmenterConfig,
  type SegmenterState,
} from "@/lib/noteSegmentation";

export interface VoiceFrame {
  midiExact: number;
  confidence: number;
}

export interface PolyphonicFrame {
  timeSeconds: number;
  voices: readonly VoiceFrame[];
  rmsDb: number;
}

interface VoiceTrack {
  /** Pitch of the most recent frame routed here. */
  midi: number;
  state: SegmenterState;
  /** Absolute onset of this track's first note; the segmenter rebases onsets per track. */
  originSeconds: number | null;
}

export interface VoiceTrackerState {
  tracks: readonly VoiceTrack[];
}

/** Voices closer than this (in semitones) continue the same track. */
export const TRACK_MATCH_SEMITONES = 0.75;

export function initialVoiceTrackerState(): VoiceTrackerState {
  return { tracks: [] };
}

function trackOrigin(track: VoiceTrack): number | null {
  if (track.originSeconds !== null) return track.originSeconds;
  if (track.state.completed.length > 0) return track.state.completed[0].onset_seconds;
  return track.state.open === null ? null : track.state.open.onsetSeconds;
}

// @spec CAP-PITCH-007
export function pushPolyphonicFrame(
  state: VoiceTrackerState,
  frame: PolyphonicFrame,
  overrides: Partial<SegmenterConfig> = {},
): VoiceTrackerState {
  const config = { ...DEFAULT_SEGMENTER_CONFIG, ...overrides };
  const unmatched = [...frame.voices].sort((a, b) => b.confidence - a.confidence);
  const next: VoiceTrack[] = [];

  for (const track of state.tracks) {
    let chosen = -1;
    let chosenDistance = TRACK_MATCH_SEMITONES;
    unmatched.forEach((voice, index) => {
      const distance = Math.abs(voice.midiExact - track.midi);
      if (distance < chosenDistance) {
        chosen = index;
        chosenDistance = distance;
      }
    });
    const pitchFrame: PitchFrame = chosen >= 0
      ? { timeSeconds: frame.timeSeconds, midiExact: unmatched[chosen].midiExact, confidence: unmatched[chosen].confidence, rmsDb: frame.rmsDb }
      : { timeSeconds: frame.timeSeconds, midiExact: null, confidence: 0, rmsDb: frame.rmsDb };
    if (chosen >= 0) unmatched.splice(chosen, 1);
    const advanced = pushFrame(track.state, pitchFrame, config);
    const alive = advanced.open !== null || advanced.completed.length > 0 || chosen >= 0;
    if (alive) {
      next.push({ midi: chosen >= 0 ? pitchFrame.midiExact ?? track.midi : track.midi, state: advanced, originSeconds: trackOrigin({ ...track, state: advanced }) });
    }
  }

  for (const voice of unmatched) {
    const pitchFrame: PitchFrame = { timeSeconds: frame.timeSeconds, midiExact: voice.midiExact, confidence: voice.confidence, rmsDb: frame.rmsDb };
    const advanced = pushFrame(initialSegmenterState(), pitchFrame, config);
    next.push({ midi: voice.midiExact, state: advanced, originSeconds: trackOrigin({ midi: voice.midiExact, state: advanced, originSeconds: null }) });
  }

  return { tracks: next };
}

/** Close every track and return all notes, onsets rebased to the earliest, ordered by onset then pitch. */
// @spec CAP-PITCH-007
export function finalizePolyphonic(
  state: VoiceTrackerState,
  endTimeSeconds: number,
  overrides: Partial<SegmenterConfig> = {},
): NoteSegment[] {
  const absolute: NoteSegment[] = [];
  for (const track of state.tracks) {
    const origin = trackOrigin(track) ?? 0;
    for (const segment of finalizeSegments(track.state, endTimeSeconds, overrides)) {
      absolute.push({ ...segment, onset_seconds: segment.onset_seconds + origin });
    }
  }
  if (absolute.length === 0) return [];
  const first = Math.min(...absolute.map((segment) => segment.onset_seconds));
  return absolute
    .map((segment) => ({ ...segment, onset_seconds: Math.round((segment.onset_seconds - first) * 1000) / 1000 }))
    .sort((a, b) => a.onset_seconds - b.onset_seconds || a.pitch_midi - b.pitch_midi);
}

/** Convenience for tests: run a whole frame list through in one call. */
export function segmentPolyphonicFrames(
  frames: readonly PolyphonicFrame[],
  overrides: Partial<SegmenterConfig> = {},
): NoteSegment[] {
  let state = initialVoiceTrackerState();
  for (const frame of frames) state = pushPolyphonicFrame(state, frame, overrides);
  const end = frames.length > 0 ? frames[frames.length - 1].timeSeconds : 0;
  return finalizePolyphonic(state, end, overrides);
}

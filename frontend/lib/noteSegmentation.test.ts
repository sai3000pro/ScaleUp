import { describe, expect, it } from "vitest";

import {
  DEFAULT_SEGMENTER_CONFIG,
  RMS_FLOOR_DB,
  mockPitchFrames,
  segmentFrames,
} from "@/lib/noteSegmentation";

describe("note segmentation", () => {
  it("splits a stepwise line into one note per pitch", () => {
    const notes = segmentFrames(mockPitchFrames("stepwise"));
    expect(notes).toHaveLength(4);
    expect(notes.map((note) => note.pitch_midi)).toEqual([60, 62, 64, 65]);
  });

  it("rebases onsets onto the first note", () => {
    const notes = segmentFrames(mockPitchFrames("stepwise"));
    expect(notes[0].onset_seconds).toBe(0);
    expect(notes[1].onset_seconds).toBeGreaterThan(0.3);
  });

  it("recovers the cents residual instead of discarding it", () => {
    // The fixture sits 12 cents sharp of MIDI 60.
    const notes = segmentFrames(mockPitchFrames("stepwise"));
    expect(notes[0].cents_deviation).toBeGreaterThan(8);
    expect(notes[0].cents_deviation).toBeLessThan(16);
    for (const note of notes) {
      expect(note.cents_deviation).toBeGreaterThan(-50);
      expect(note.cents_deviation).toBeLessThanOrEqual(50);
    }
  });

  it("hears two attacks on the same pitch as two notes", () => {
    // The case a pitch-change-only segmenter cannot see at all: without an
    // amplitude re-attack trigger these merge into one long note and the take
    // is scored as a missed note plus a held one.
    const notes = segmentFrames(mockPitchFrames("repeated-same-pitch"));
    expect(notes).toHaveLength(2);
    expect(notes[0].pitch_midi).toBe(60);
    expect(notes[1].pitch_midi).toBe(60);
  });

  it("does not split a vibrato into separate notes", () => {
    const notes = segmentFrames(mockPitchFrames("vibrato"));
    expect(notes).toHaveLength(1);
    expect(notes[0].pitch_midi).toBe(69);
  });

  it("absorbs a single-frame octave flip", () => {
    const notes = segmentFrames(mockPitchFrames("octave-glitch"));
    expect(notes).toHaveLength(1);
    expect(notes[0].pitch_midi).toBe(60);
  });

  it("returns nothing for silence", () => {
    expect(segmentFrames(mockPitchFrames("silence"))).toEqual([]);
  });

  it("drops a blip shorter than the minimum note duration", () => {
    expect(segmentFrames(mockPitchFrames("short-blip"))).toEqual([]);
  });

  it("reports rising levels across a crescendo", () => {
    const notes = segmentFrames(mockPitchFrames("crescendo"));
    expect(notes).toHaveLength(4);
    for (let index = 1; index < notes.length; index += 1) {
      expect(notes[index].mean_level_db).toBeGreaterThan(notes[index - 1].mean_level_db);
    }
  });

  it("is deterministic", () => {
    const frames = mockPitchFrames("stepwise");
    expect(segmentFrames(frames)).toEqual(segmentFrames(frames));
  });

  it("ignores frames below the level gate even when the detector is confident", () => {
    // Room tone with an accidental periodicity: high clarity, no level. A
    // confidence-only gate turns this into a note.
    const frames = Array.from({ length: 40 }, (_, index) => ({
      timeSeconds: index * 0.016,
      midiExact: 60,
      confidence: 0.95,
      rmsDb: RMS_FLOOR_DB,
    }));
    expect(segmentFrames(frames)).toEqual([]);
  });

  it("uses hysteresis so a decaying note does not chatter", () => {
    const { noteOnRmsDb, noteOffRmsDb } = DEFAULT_SEGMENTER_CONFIG;
    expect(noteOffRmsDb).toBeLessThan(noteOnRmsDb);
    const frames = Array.from({ length: 40 }, (_, index) => ({
      timeSeconds: index * 0.016,
      midiExact: 60,
      confidence: 0.9,
      // Starts above the on-threshold, decays to between off and on. A single
      // threshold would end the note halfway and start a new one.
      rmsDb: index === 0 ? -20 : (noteOnRmsDb + noteOffRmsDb) / 2,
    }));
    expect(segmentFrames(frames)).toHaveLength(1);
  });
});

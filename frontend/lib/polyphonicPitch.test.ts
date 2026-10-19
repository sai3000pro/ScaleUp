import { describe, expect, it } from "vitest";

import { detectPitches } from "@/lib/polyphonicPitch";

const SAMPLE_RATE = 48000;
const SIZE = 4096;

function midiToHz(midi: number): number {
  return 440 * 2 ** ((midi - 69) / 12);
}

/** A plucked-string-like tone: fundamental plus decaying harmonics. */
function synthesise(midis: readonly number[], harmonics = 5): Float32Array {
  const out = new Float32Array(SIZE);
  for (const midi of midis) {
    const f0 = midiToHz(midi);
    for (let h = 1; h <= harmonics; h += 1) {
      for (let i = 0; i < SIZE; i += 1) {
        out[i] += (0.3 / h) * Math.sin((2 * Math.PI * f0 * h * i) / SAMPLE_RATE);
      }
    }
  }
  return out;
}

const rounded = (midis: readonly number[]) =>
  detectPitches(synthesise(midis), SAMPLE_RATE).map((voice) => Math.round(voice.midiExact)).sort((a, b) => a - b);

// @spec CAP-PITCH-007
describe("polyphonic pitch detection", () => {
  it("resolves the three notes of a C major triad", () => {
    expect(rounded([60, 64, 67])).toEqual([60, 64, 67]);
  });

  it("resolves an open-voiced four-note chord across two octaves", () => {
    expect(rounded([48, 55, 64, 72])).toEqual([48, 55, 64, 72]);
  });

  it("hears a single note as exactly one voice, not its harmonics", () => {
    expect(rounded([57])).toEqual([57]);
  });

  it("does not invent a sub-octave for a note whose harmonics it shares", () => {
    expect(rounded([69])).not.toContain(57);
  });

  // @spec CAP-PITCH-002
  it("reports nothing for silence", () => {
    expect(detectPitches(new Float32Array(SIZE), SAMPLE_RATE)).toEqual([]);
  });

  // @spec CAP-PITCH-005, CAP-PITCH-008
  it("refines each voice to within a few cents", () => {
    const voices = detectPitches(synthesise([64, 67]), SAMPLE_RATE);
    for (const voice of voices) {
      const cents = (voice.midiExact - Math.round(voice.midiExact)) * 100;
      expect(Math.abs(cents)).toBeLessThan(15);
    }
  });

  // @spec CAP-PITCH-001
  it("reports a clarity in 0..1 and ranks voices by salience", () => {
    const voices = detectPitches(synthesise([60, 64, 67]), SAMPLE_RATE);
    expect(voices.length).toBe(3);
    for (const voice of voices) {
      expect(voice.clarity).toBeGreaterThan(0);
      expect(voice.clarity).toBeLessThanOrEqual(1);
    }
    for (let i = 1; i < voices.length; i += 1) {
      expect(voices[i - 1].salience).toBeGreaterThanOrEqual(voices[i].salience);
    }
  });
});

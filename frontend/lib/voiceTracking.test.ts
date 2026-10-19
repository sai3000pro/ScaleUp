import { describe, expect, it } from "vitest";

import { segmentPolyphonicFrames, type PolyphonicFrame } from "@/lib/voiceTracking";

const HOP = 0.016;

function frames(spec: readonly { seconds: number; midis: readonly number[] }[]): PolyphonicFrame[] {
  const out: PolyphonicFrame[] = [];
  let time = 0;
  for (const block of spec) {
    const count = Math.round(block.seconds / HOP);
    for (let i = 0; i < count; i += 1) {
      out.push({
        timeSeconds: time,
        voices: block.midis.map((midi) => ({ midiExact: midi + 0.05, confidence: 0.9 })),
        rmsDb: block.midis.length > 0 ? -20 : -80,
      });
      time += HOP;
    }
  }
  return out;
}

// @spec CAP-PITCH-007
describe("voice tracking", () => {
  it("turns a sustained triad into three notes sharing one onset", () => {
    const notes = segmentPolyphonicFrames(frames([{ seconds: 0.5, midis: [60, 64, 67] }, { seconds: 0.3, midis: [] }]));
    expect(notes.map((note) => note.pitch_midi)).toEqual([60, 64, 67]);
    expect(notes.every((note) => note.onset_seconds === 0)).toBe(true);
    expect(notes.every((note) => note.duration_seconds > 0.4)).toBe(true);
  });

  it("keeps a held bass note open while the upper voices change", () => {
    const notes = segmentPolyphonicFrames(
      frames([
        { seconds: 0.5, midis: [48, 64] },
        { seconds: 0.5, midis: [48, 65] },
        { seconds: 0.3, midis: [] },
      ]),
    );
    const bass = notes.filter((note) => note.pitch_midi === 48);
    expect(bass).toHaveLength(1);
    expect(bass[0].duration_seconds).toBeGreaterThan(0.9);
    expect(notes.filter((note) => note.pitch_midi !== 48).map((note) => note.pitch_midi)).toEqual([64, 65]);
  });

  it("rebases every voice to the earliest onset and orders by onset then pitch", () => {
    const notes = segmentPolyphonicFrames(
      frames([
        { seconds: 0.4, midis: [] },
        { seconds: 0.5, midis: [60] },
        { seconds: 0.5, midis: [60, 67] },
        { seconds: 0.3, midis: [] },
      ]),
    );
    expect(notes[0].pitch_midi).toBe(60);
    expect(notes[0].onset_seconds).toBe(0);
    expect(notes[1].pitch_midi).toBe(67);
    expect(notes[1].onset_seconds).toBeCloseTo(0.5, 1);
  });

  it("segments a monophonic line exactly as a single stream would", () => {
    const notes = segmentPolyphonicFrames(frames([{ seconds: 0.4, midis: [60] }, { seconds: 0.4, midis: [62] }, { seconds: 0.3, midis: [] }]));
    expect(notes.map((note) => note.pitch_midi)).toEqual([60, 62]);
  });
});

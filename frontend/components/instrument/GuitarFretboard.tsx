"use client";

import { memo, useMemo } from "react";
import type { ExerciseNote } from "@/lib/types";

interface GuitarFretboardProps {
  activeNote?: ExerciseNote | null;
  allNotes?: ExerciseNote[];
  exerciseTitle?: string;
  onNoteClick?: (midi: number) => void;
}

// Standard Guitar Tuning: Strings 6 to 1 (Low E to High E)
const STRINGS = [
  { stringNum: 1, name: "e", openMidi: 64 }, // High E
  { stringNum: 2, name: "B", openMidi: 59 },
  { stringNum: 3, name: "G", openMidi: 55 },
  { stringNum: 4, name: "D", openMidi: 50 },
  { stringNum: 5, name: "A", openMidi: 45 },
  { stringNum: 6, name: "E", openMidi: 40 }, // Low E
];

const FRET_MARKERS = [3, 5, 7, 9, 12];
const TOTAL_FRETS = 12;

// Standard Chord Fingerings [string 6, 5, 4, 3, 2, 1] (-1 for muted X, 0 for open O, >0 for fret)
const KNOWN_CHORDS: Record<string, { frets: number[]; fingers: string[] }> = {
  g: { frets: [3, 2, 0, 0, 0, 3], fingers: ["3", "2", "O", "O", "O", "4"] },
  c: { frets: [-1, 3, 2, 0, 1, 0], fingers: ["X", "3", "2", "O", "1", "O"] },
  d: { frets: [-1, -1, 0, 2, 3, 2], fingers: ["X", "X", "O", "1", "3", "2"] },
  em: { frets: [0, 2, 2, 0, 0, 0], fingers: ["O", "2", "3", "O", "O", "O"] },
  am: { frets: [-1, 0, 2, 2, 1, 0], fingers: ["X", "O", "2", "3", "1", "O"] },
  e: { frets: [0, 2, 2, 1, 0, 0], fingers: ["O", "2", "3", "1", "O", "O"] },
  a: { frets: [-1, 0, 2, 2, 2, 0], fingers: ["X", "O", "1", "2", "3", "O"] },
};

function getNotePosition(note: ExerciseNote): { stringNum: number; fret: number } | null {
  if (note.string !== null && note.fret !== null) {
    return { stringNum: note.string, fret: note.fret };
  }
  if (note.pitch_midi === null) return null;

  // Find natural guitar fretboard position closest to open/lower frets
  for (const s of [...STRINGS].reverse()) {
    const fret = note.pitch_midi - s.openMidi;
    if (fret >= 0 && fret <= TOTAL_FRETS) {
      return { stringNum: s.stringNum, fret };
    }
  }
  return null;
}

export const GuitarFretboard = memo(function GuitarFretboard({
  activeNote,
  allNotes = [],
  exerciseTitle = "",
  onNoteClick,
}: GuitarFretboardProps) {
  // Detect if exercise has a known chord shape
  const detectedChord = useMemo(() => {
    const title = exerciseTitle.toLowerCase();
    for (const [key, val] of Object.entries(KNOWN_CHORDS)) {
      if (title.includes(key)) return { name: key.toUpperCase(), ...val };
    }
    return null;
  }, [exerciseTitle]);

  const activePos = activeNote ? getNotePosition(activeNote) : null;

  const notePositions = useMemo(() => {
    const list: Array<{ stringNum: number; fret: number; name: string; midi: number }> = [];
    for (const n of allNotes) {
      const pos = getNotePosition(n);
      if (pos && n.pitch_midi !== null) {
        list.push({ ...pos, name: n.note_name, midi: n.pitch_midi });
      }
    }
    return list;
  }, [allNotes]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 shadow-inner">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-amber-400">🎸 Guitar Fretboard</span>
          {detectedChord && (
            <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs font-bold text-amber-300 border border-amber-500/30">
              {detectedChord.name} Chord Shape
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[11px] text-slate-400">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" /> Active Note
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-rose-500/60" /> Target Notes
          </span>
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="min-w-[620px] select-none">
          {/* Fret Number Header */}
          <div className="grid grid-cols-13 gap-0 text-center text-[10px] font-mono text-slate-500 mb-1">
            <div className="w-10">Nut (0)</div>
            {Array.from({ length: TOTAL_FRETS }, (_, i) => (
              <div key={i + 1} className="flex-1 font-semibold">
                {i + 1}
                {FRET_MARKERS.includes(i + 1) && (
                  <span className="ml-0.5 text-slate-400">{i + 1 === 12 ? "••" : "•"}</span>
                )}
              </div>
            ))}
          </div>

          {/* Fretboard Strings Grid */}
          <div className="relative rounded-lg border-2 border-amber-900/60 bg-gradient-to-r from-amber-950/40 via-slate-900 to-amber-950/30 p-2">
            {STRINGS.map((guitarString, sIndex) => {
              const stringThickness = `${1 + (6 - guitarString.stringNum) * 0.4}px`;
              const chordFret = detectedChord ? detectedChord.frets[6 - guitarString.stringNum] : undefined;

              return (
                <div key={guitarString.stringNum} className="relative flex items-center h-8 my-0.5">
                  {/* String Line Behind Frets */}
                  <div
                    className="absolute left-10 right-0 bg-gradient-to-r from-amber-200/50 via-slate-300/40 to-amber-200/50"
                    style={{ height: stringThickness }}
                  />

                  {/* Open String Label & Marker */}
                  <div className="w-10 z-10 flex items-center gap-1 pr-2 border-r-4 border-amber-400/80 bg-slate-950/90 h-full">
                    <span className="font-mono text-xs font-bold text-amber-300 w-3">{guitarString.name}</span>
                    {chordFret !== undefined && (
                      <span
                        className={`text-[10px] font-bold ${
                          chordFret === -1 ? "text-rose-400" : chordFret === 0 ? "text-emerald-400" : "text-slate-500"
                        }`}
                      >
                        {chordFret === -1 ? "✕" : chordFret === 0 ? "◯" : ""}
                      </span>
                    )}
                  </div>

                  {/* Fret Cells (1 to 12) */}
                  <div className="flex-1 grid grid-cols-12 h-full z-10">
                    {Array.from({ length: TOTAL_FRETS }, (_, fretIndex) => {
                      const fretNum = fretIndex + 1;
                      const isFretMarker = FRET_MARKERS.includes(fretNum);
                      const isDoubleMarker = fretNum === 12;

                      // Is active note on this string & fret?
                      const isActive = activePos?.stringNum === guitarString.stringNum && activePos.fret === fretNum;
                      // Is note in piece target?
                      const isTarget = notePositions.some(
                        (np) => np.stringNum === guitarString.stringNum && np.fret === fretNum,
                      );
                      // Is in chord diagram?
                      const isChordFinger = chordFret === fretNum;

                      const cellMidi = guitarString.openMidi + fretNum;

                      return (
                        <div
                          key={fretNum}
                          onClick={() => onNoteClick?.(cellMidi)}
                          className={`relative flex items-center justify-center border-r border-slate-700/80 cursor-pointer transition hover:bg-red-500/20 ${
                            sIndex === 0 ? "border-t-0" : ""
                          }`}
                        >
                          {/* Fretboard Inlay Dots at middle */}
                          {sIndex === 2 && isFretMarker && (
                            <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-20">
                              {isDoubleMarker ? (
                                <div className="flex gap-2">
                                  <div className="h-2 w-2 rounded-full bg-slate-300" />
                                  <div className="h-2 w-2 rounded-full bg-slate-300" />
                                </div>
                              ) : (
                                <div className="h-2.5 w-2.5 rounded-full bg-slate-300" />
                              )}
                            </div>
                          )}

                          {/* Active Note Indicator */}
                          {isActive ? (
                            <div className="z-20 flex h-6 w-6 items-center justify-center rounded-full bg-red-500 text-white font-black text-[11px] shadow-lg shadow-red-500/80 animate-bounce">
                              {activeNote?.note_name ?? "●"}
                            </div>
                          ) : isChordFinger ? (
                            <div className="z-20 flex h-5 w-5 items-center justify-center rounded-full bg-amber-400 text-slate-950 font-bold text-[10px] shadow-md shadow-amber-400/50">
                              {detectedChord?.fingers[6 - guitarString.stringNum] || "●"}
                            </div>
                          ) : isTarget ? (
                            <div className="z-20 flex h-5 w-5 items-center justify-center rounded-full bg-rose-500/80 text-white font-bold text-[10px] shadow">
                              ●
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
});

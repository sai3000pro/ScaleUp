"use client";

import type { Exercise, ExerciseNote } from "@/lib/types";
import { GuitarFretboard } from "./GuitarFretboard";
import { PianoKeyboard } from "./PianoKeyboard";

interface InstrumentVisualizerProps {
  exercise?: Exercise | null;
  activeNote?: ExerciseNote | null;
  allNotes?: ExerciseNote[];
  instrument?: string | null;
  onNoteClick?: (midi: number) => void;
}

export function InstrumentVisualizer({
  exercise,
  activeNote,
  allNotes = [],
  instrument,
  onNoteClick,
}: InstrumentVisualizerProps) {
  const targetInstrument = (
    instrument ||
    exercise?.evaluator_version?.split("-")[0] ||
    "piano"
  ).toLowerCase();

  const isGuitarOrFretted =
    targetInstrument.includes("guitar") ||
    targetInstrument.includes("banjo") ||
    targetInstrument.includes("bass");

  const notesToDisplay = allNotes.length > 0 ? allNotes : exercise?.notes ?? [];

  if (isGuitarOrFretted) {
    return (
      <GuitarFretboard
        activeNote={activeNote}
        allNotes={notesToDisplay}
        exerciseTitle={exercise?.title ?? ""}
        onNoteClick={onNoteClick}
      />
    );
  }

  // Piano / Default keyboard visualizer
  const activeMidi = activeNote?.pitch_midi ?? null;
  const targetMidis = notesToDisplay
    .map((n) => n.pitch_midi)
    .filter((m): m is number => m !== null);

  // Dynamic piano range based on notes in exercise (centered around C3 to C6)
  const minMidi = targetMidis.length > 0 ? Math.min(...targetMidis) : 60;
  const maxMidi = targetMidis.length > 0 ? Math.max(...targetMidis) : 72;

  // Align start to the nearest C below minMidi and end to nearest B/C above maxMidi
  const startMidi = Math.max(36, Math.floor((minMidi - 2) / 12) * 12);
  const endMidi = Math.min(84, Math.ceil((maxMidi + 2) / 12) * 12);

  return (
    <PianoKeyboard
      activeMidi={activeMidi}
      highlightedMidis={targetMidis}
      startMidi={startMidi}
      endMidi={endMidi}
      onKeyClick={onNoteClick}
    />
  );
}

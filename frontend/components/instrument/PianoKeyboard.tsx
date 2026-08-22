import { memo, useMemo } from "react";

interface PianoKeyboardProps {
  activeMidi?: number | null;
  highlightedMidis?: number[];
  startMidi?: number; // default 48 = C3
  endMidi?: number;   // default 72 = C5
  onKeyClick?: (midi: number) => void;
}

const PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const BLACK_KEY_PITCHES = [1, 3, 6, 8, 10]; // C#, D#, F#, G#, A#

function isBlackKey(midi: number): boolean {
  return BLACK_KEY_PITCHES.includes(midi % 12);
}

function midiName(midi: number): string {
  return `${PITCH_NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`;
}

export const PianoKeyboard = memo(function PianoKeyboard({
  activeMidi,
  highlightedMidis = [],
  startMidi = 48, // C3
  endMidi = 72,   // C5
  onKeyClick,
}: PianoKeyboardProps) {
  // Generate keys structure in range
  const { whiteKeys, blackKeys } = useMemo(() => {
    const white: Array<{ midi: number; name: string; isMiddleC: boolean; index: number }> = [];
    const black: Array<{ midi: number; name: string; whiteIndex: number }> = [];

    let whiteIndex = 0;
    for (let midi = startMidi; midi <= endMidi; midi++) {
      const name = midiName(midi);
      if (isBlackKey(midi)) {
        // Black key sits after the previous white key
        black.push({
          midi,
          name,
          whiteIndex: Math.max(0, whiteIndex - 1),
        });
      } else {
        white.push({
          midi,
          name,
          isMiddleC: midi === 60,
          index: whiteIndex,
        });
        whiteIndex++;
      }
    }
    return { whiteKeys: white, blackKeys: black };
  }, [startMidi, endMidi]);

  const totalWhite = whiteKeys.length;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 shadow-inner">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-200">🎹 Piano Keyboard</span>
          <span className="text-[11px] text-slate-400">(Middle C = C4)</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-slate-400">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" /> Active Key
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-red-400/60" /> Target Keys
          </span>
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="relative h-36 min-w-[500px] select-none rounded-lg border-2 border-slate-800 bg-slate-950 p-1">
          {/* White Keys Row */}
          <div className="flex h-full w-full gap-0.5">
            {whiteKeys.map((key) => {
              const isActive = activeMidi === key.midi;
              const isTarget = highlightedMidis.includes(key.midi);

              return (
                <button
                  key={key.midi}
                  type="button"
                  onClick={() => onKeyClick?.(key.midi)}
                  className={`group relative flex-1 rounded-b-md border transition-all ${isActive
                    ? "z-10 border-red-500 bg-gradient-to-b from-red-400 to-red-600 text-white shadow-lg shadow-red-500/60 scale-[1.02]"
                    : isTarget
                      ? "border-red-300 bg-red-50 text-red-950 hover:bg-red-100 hover:border-red-400"
                      : "border-slate-300 bg-white text-slate-800 hover:bg-red-50 hover:border-red-400 hover:text-red-600 active:bg-red-100"
                    }`}
                  title={`${key.name} (MIDI ${key.midi})`}
                >
                  {/* Middle C Dot */}
                  {key.isMiddleC && (
                    <span className="absolute bottom-6 left-1/2 -translate-x-1/2 h-2 w-2 rounded-full bg-red-500 shadow-sm" />
                  )}

                  {/* Note Label */}
                  <span className="absolute bottom-1.5 left-1/2 -translate-x-1/2 text-[10px] font-extrabold font-mono text-slate-900 group-hover:text-red-600">
                    {key.name}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Black Keys Layer (Sharps / Flats) */}
          <div className="pointer-events-none absolute inset-x-1 top-1 h-20">
            {blackKeys.map((key) => {
              const isActive = activeMidi === key.midi;
              const isTarget = highlightedMidis.includes(key.midi);

              // Calculate horizontal position based on white key index
              const leftPercent = ((key.whiteIndex + 0.68) / totalWhite) * 100;
              const keyWidthPercent = (1 / totalWhite) * 65;

              return (
                <button
                  key={key.midi}
                  type="button"
                  onClick={() => onKeyClick?.(key.midi)}
                  style={{
                    left: `${leftPercent}%`,
                    width: `${keyWidthPercent}%`,
                  }}
                  className={`group pointer-events-auto absolute top-0 h-full rounded-b-md border shadow-md transition-all ${
                    isActive
                      ? "z-20 border-red-400 bg-red-500 text-white shadow-lg shadow-red-500/80 scale-105"
                      : isTarget
                        ? "border-red-500/80 bg-red-950 text-red-200 hover:bg-red-900 hover:border-red-400 hover:text-white"
                        : "border-slate-900 bg-black text-slate-300 hover:bg-red-900 hover:border-red-500 hover:text-white active:bg-red-950"
                  }`}
                  title={`${key.name} (MIDI ${key.midi})`}
                >
                  <span className="absolute bottom-1 left-1/2 -translate-x-1/2 text-[8px] font-bold font-mono text-slate-300 group-hover:text-white transition-colors">
                    {key.name}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
});

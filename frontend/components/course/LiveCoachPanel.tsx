"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Exercise } from "@/lib/types";
import { CARD, FOCUS_RING } from "@/lib/ui";

interface LiveCoachPanelProps {
  courseId: string;
  refreshKey: number;
  onCompleted?: () => void;
}

export function LiveCoachPanel({ courseId, refreshKey }: LiveCoachPanelProps) {
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [selectedExerciseId, setSelectedExerciseId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadExercises() {
      try {
        setLoading(true);
        const items = await api.listPracticeExercises(courseId);
        if (cancelled) return;
        setExercises(items);
        setSelectedExerciseId((current) => current ?? items[0]?.id ?? null);
      } catch (caught: unknown) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Could not load drills.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadExercises();
    return () => {
      cancelled = true;
    };
  }, [courseId, refreshKey]);

  const selectedExercise = exercises.find((item) => item.id === selectedExerciseId) ?? null;

  return (
    <section className={CARD}>
      <header className="mb-3 flex items-center justify-between gap-2 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🎙️</span>
          <h2 className="text-sm font-bold text-slate-100">Live Coaching Studio</h2>
        </div>
        <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-[10px] font-bold text-red-400 border border-red-500/20">
          Real-time AI
        </span>
      </header>

      {error !== null && (
        <p role="alert" className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-xs text-slate-400 py-4 text-center animate-pulse">
          Loading practice studio…
        </p>
      ) : (
        <div className="space-y-3.5">
          {exercises.length > 0 ? (
            <>
              {/* Exercise Selector Dropdown */}
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
                  Select Drill / Exercise
                </label>
                <select
                  className={`w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-100 ${FOCUS_RING}`}
                  value={selectedExerciseId ?? ""}
                  onChange={(event) => setSelectedExerciseId(event.target.value)}
                >
                  {exercises.map((exercise) => (
                    <option key={exercise.id} value={exercise.id}>
                      {exercise.title} ({exercise.tempo_bpm} BPM · Level {exercise.difficulty})
                    </option>
                  ))}
                </select>
              </div>

              {/* Selected Drill Snapshot */}
              {selectedExercise && (
                <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-xs space-y-2">
                  <div className="flex items-center justify-between gap-1">
                    <span className="font-bold text-slate-100 truncate">{selectedExercise.title}</span>
                    <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] font-bold text-red-300 border border-red-500/20 shrink-0">
                      {selectedExercise.tempo_bpm} BPM
                    </span>
                  </div>

                  <p className="text-[11px] text-slate-300 line-clamp-2 leading-relaxed">
                    {selectedExercise.instructions || "Play the exercise cleanly with steady pulse."}
                  </p>

                  <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1 border-t border-slate-800/80">
                    <span>{selectedExercise.duration_beats} Beats</span>
                    <span>Level {selectedExercise.difficulty}/5</span>
                  </div>
                </div>
              )}

              {/* Studio Feature Checklist */}
              <ul className="space-y-1 text-[11px] text-slate-300 pt-1">
                <li className="flex items-center gap-1.5">
                  <span className="text-red-400 font-bold">✓</span> Fullscreen Fretboard & Keyboard
                </li>
                <li className="flex items-center gap-1.5">
                  <span className="text-red-400 font-bold">✓</span> Note Rehearsal & Audio Preview
                </li>
                <li className="flex items-center gap-1.5">
                  <span className="text-red-400 font-bold">✓</span> Real-Time Pitch & Rhythm Cues
                </li>
              </ul>

              {/* Gateway Launch Button */}
              <Link
                href={`/courses/${courseId}/coach?exercise=${selectedExerciseId ?? ""}`}
                className={`w-full py-3 px-4 rounded-xl bg-red-600 hover:bg-red-500 text-white font-bold text-sm shadow-md shadow-red-600/25 transition-all flex items-center justify-center gap-2 group ${FOCUS_RING}`}
              >
                <span>Launch Coaching Studio</span>
                <span className="transition-transform group-hover:translate-x-0.5">🚀</span>
              </Link>
            </>
          ) : (
            <p className="text-xs text-slate-400 py-2">
              No live coaching drills available for this course yet.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

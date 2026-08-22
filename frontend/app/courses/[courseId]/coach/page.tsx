"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { memo, Suspense, useCallback, useEffect, useRef, useState } from "react";

import { InstrumentVisualizer } from "@/components/instrument/InstrumentVisualizer";
import { api } from "@/lib/api";
import { getAudioContext, playMetronomeClick, playMidiTone } from "@/lib/audioSynth";
import { CoachSocket, type CoachCue, type CoachExercise, type CoachUtteranceState } from "@/lib/coachSocket";
import { MicRecorder } from "@/lib/pitchDetection";
import type { CoachLiveTipResponse, Course, Exercise, ExerciseNote, PerformanceAttempt, PerformedNote } from "@/lib/types";
import { BUTTON_SECONDARY, CARD, FOCUS_RING } from "@/lib/ui";
import { usePostureStore } from "@/stores/usePostureStore";

type StudioStage = "preview" | "countdown" | "connecting" | "listening" | "scoring" | "result";

const CUE_LABEL: Record<string, { label: string; tone: string }> = {
  rushing: { label: "Ahead of the beat (Rushing)", tone: "text-amber-300 border-amber-500/40 bg-amber-500/10" },
  dragging: { label: "Behind the beat (Dragging)", tone: "text-amber-300 border-amber-500/40 bg-amber-500/10" },
  flat_pitch: { label: "Under pitch (Flat)", tone: "text-rose-300 border-rose-500/40 bg-rose-500/10" },
  sharp_pitch: { label: "Over pitch (Sharp)", tone: "text-rose-300 border-rose-500/40 bg-rose-500/10" },
  missed_run: { label: "Notes missed", tone: "text-rose-300 border-rose-500/40 bg-rose-500/10" },
  extra_notes: { label: "Extra notes detected", tone: "text-amber-300 border-amber-500/40 bg-amber-500/10" },
  dynamics_flat: { label: "Monotone dynamic", tone: "text-amber-300 border-amber-500/40 bg-amber-500/10" },
  lost_place: { label: "Lost position", tone: "text-rose-300 border-rose-500/40 bg-rose-500/10" },
  good_streak: { label: "Clean playing! Keep the groove", tone: "text-emerald-300 border-emerald-500/40 bg-emerald-500/10" },
  take_complete: { label: "Take complete", tone: "text-rose-300 border-rose-500/40 bg-rose-500/10" },
};

export default function CoachingStudioPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-slate-950 p-8 text-center text-slate-400">
          Loading coaching studio…
        </main>
      }
    >
      <CoachingStudioView />
    </Suspense>
  );
}

function CoachingStudioView() {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const searchParams = useSearchParams();
  const initialExerciseId = searchParams.get("exercise");

  const [course, setCourse] = useState<Course | null>(null);
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [selectedExerciseId, setSelectedExerciseId] = useState<string | null>(initialExerciseId);
  const [stage, setStage] = useState<StudioStage>("preview");
  const [countdownValue, setCountdownValue] = useState<number>(3);
  const [previewNoteIndex, setPreviewNoteIndex] = useState<number | null>(null);
  const [cue, setCue] = useState<CoachCue | null>(null);
  const [utterance, setUtterance] = useState<CoachUtteranceState | null>(null);
  const [transcript, setTranscript] = useState<string[]>([]);
  const [attempt, setAttempt] = useState<PerformanceAttempt | null>(null);
  const [coachExercise, setCoachExercise] = useState<CoachExercise | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentBeat, setCurrentBeat] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [customBpm, setCustomBpm] = useState<number | null>(null);
  const [aiTip, setAiTip] = useState<CoachLiveTipResponse | null>(null);
  const [isFetchingTip, setIsFetchingTip] = useState(false);

  const socketRef = useRef<CoachSocket | null>(null);
  const recorderRef = useRef<MicRecorder | null>(null);
  const notesRef = useRef<PerformedNote[]>([]);
  const countdownTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      try {
        setLoading(true);
        const [loadedCourse, loadedExercises] = await Promise.all([
          api.getCourse(courseId),
          api.listPracticeExercises(courseId),
        ]);
        if (cancelled) return;
        setCourse(loadedCourse);
        setExercises(loadedExercises);
        if (loadedExercises.length > 0) {
          setSelectedExerciseId((prev) => {
            if (prev && loadedExercises.some((e) => e.id === prev)) return prev;
            return loadedExercises[0].id;
          });
        }
      } catch (caught: unknown) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Failed to load studio data.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadData();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  useEffect(() => {
    return () => {
      if (countdownTimerRef.current !== null) {
        clearInterval(countdownTimerRef.current);
      }
      socketRef.current?.close();
      void recorderRef.current?.stop();
    };
  }, []);

  const selectedExercise = exercises.find((item) => item.id === selectedExerciseId) ?? null;
  const tempoBpm = customBpm ?? selectedExercise?.tempo_bpm ?? coachExercise?.tempo_bpm ?? 60;

  // Active note currently focused by the live coach / highway
  const currentCursor = cue?.cursor ?? 0;
  const currentActiveNote = selectedExercise?.notes?.[currentCursor] ?? null;

  // Zero-lag hardware-clock visual metronome pulse during active take
  useEffect(() => {
    if (stage !== "listening") {
      setCurrentBeat(1);
      return;
    }
    setCurrentBeat(1);
    const beatIntervalMs = Math.max(150, Math.round((60 / tempoBpm) * 1000));
    const timer = setInterval(() => {
      setCurrentBeat((prev) => (prev % 4) + 1);
    }, beatIntervalMs);
    return () => clearInterval(timer);
  }, [stage, tempoBpm]);

  // Synchronize displayed beat directly with the active note on the highway and keyboard
  const activeNoteBeat = currentActiveNote !== null ? (Math.floor(currentActiveNote.onset_beats) % 4) + 1 : null;
  const displayedBeat = (stage === "listening" && activeNoteBeat !== null) ? activeNoteBeat : currentBeat;

  const fetchLiveAiTip = useCallback(async () => {
    if (!selectedExercise) return;
    setIsFetchingTip(true);
    try {
      const tipRes = await api.getLiveCoachTip(courseId, {
        exercise_title: selectedExercise.title,
        instrument: course?.title?.toLowerCase().includes("guitar")
          ? "guitar"
          : course?.title?.toLowerCase().includes("violin")
          ? "violin"
          : course?.title?.toLowerCase().includes("trumpet")
          ? "trumpet"
          : course?.title?.toLowerCase().includes("drum")
          ? "drums"
          : "piano",
        tempo_bpm: tempoBpm,
        current_note: currentActiveNote?.note_name ?? null,
        signed_timing_bias_seconds: cue?.signed_timing_bias_seconds ?? null,
        mean_pitch_error_semitones: cue?.mean_pitch_error_semitones ?? null,
        streak_count: cue?.matched_count ?? 0,
      });
      setAiTip(tipRes);
    } catch {
      // Graceful fallback
    } finally {
      setIsFetchingTip(false);
    }
  }, [courseId, selectedExercise, course, tempoBpm, currentActiveNote, cue]);

  const startTake = useCallback(async () => {
    if (selectedExerciseId === null) return;
    setError(null);
    setAttempt(null);
    setTranscript([]);
    setCue(null);
    setStage("connecting");
    notesRef.current = [];
    usePostureStore.getState().begin(null);

    try {
      const session = await api.createPracticeSession(selectedExerciseId);
      const socket = new CoachSocket(session.id, {
        onReady: (exercise) => {
          setCoachExercise(exercise);
          setStage("listening");
        },
        onCue: (nextCue) => {
          setCue(nextCue);
        },
        onUtterance: (next) => {
          setUtterance(next);
          if (!next.streaming && !next.cancelled && next.text.trim() !== "") {
            setTranscript((lines) => [...lines, next.text]);
          }
        },
        onResult: (result) => {
          setAttempt(result);
          setStage("result");
        },
        onError: (err) => {
          setError(err);
        },
      });
      socketRef.current = socket;
      await socket.connect();

      const recorder = new MicRecorder(() => {}, {
        onNote: (note) => {
          notesRef.current.push(note);
          socket.pushNote(note);
        },
        onLevel: (rmsDb, silenceSeconds) => socket.pushLevel(rmsDb, silenceSeconds),
      });
      recorderRef.current = recorder;
      await recorder.start();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Could not start the live coaching session.");
      setStage("preview");
      socketRef.current?.close();
      socketRef.current = null;
    }
  }, [selectedExerciseId]);

  const cancelCountdown = useCallback(() => {
    if (countdownTimerRef.current !== null) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
    setStage("preview");
  }, []);

  const triggerCountdown = useCallback(() => {
    if (selectedExerciseId === null) return;
    if (countdownTimerRef.current !== null) {
      clearInterval(countdownTimerRef.current);
    }
    // Pre-warm audio context immediately on user click for zero-latency clicks
    getAudioContext();

    setStage("countdown");
    setCountdownValue(3);
    playMetronomeClick(false);

    let count = 3;
    const tickIntervalMs = 1200;

    countdownTimerRef.current = setInterval(() => {
      count -= 1;
      if (count > 0) {
        setCountdownValue(count);
        playMetronomeClick(false);
      } else if (count === 0) {
        setCountdownValue(0);
        playMetronomeClick(true);
      } else {
        if (countdownTimerRef.current !== null) {
          clearInterval(countdownTimerRef.current);
          countdownTimerRef.current = null;
        }
        void startTake();
      }
    }, tickIntervalMs);
  }, [selectedExerciseId, startTake]);

  const stopTake = useCallback(async () => {
    setStage("scoring");
    const recorder = recorderRef.current;
    const socket = socketRef.current;
    const notes = recorder === null ? notesRef.current : await recorder.stop();
    const posture = usePostureStore.getState().observation();
    usePostureStore.getState().end();

    if (socket !== null && socket.isOpen) {
      socket.finalize(notes, { posture });
    } else if (socket !== null) {
      try {
        const session = await api.createPracticeSession(selectedExerciseId ?? "");
        const result = await api.submitPerformanceAttempt(
          session.id,
          notes,
          socket.idempotencyKey,
          null,
          posture,
        );
        setAttempt(result);
        setStage("result");
      } catch (caught: unknown) {
        setError(caught instanceof Error ? caught.message : "The take could not be scored.");
        setStage("preview");
      }
    }
    recorderRef.current = null;
  }, [selectedExerciseId]);

  const progress = cue === null ? 0 : Math.round(cue.progress_ratio * 100);
  const currentCueInfo = cue?.cue ? CUE_LABEL[cue.cue] : null;

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* Navigation & Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <div className="flex items-center gap-3">
              <Link
                href={`/courses/${courseId}`}
                className="flex items-center gap-1.5 text-xs font-semibold text-red-400 hover:text-red-300 transition"
              >
                ← Back to Course
              </Link>
              <span className="text-slate-600">/</span>
              <span className="text-xs uppercase tracking-wider text-slate-400 font-medium">
                Live Coaching Studio
              </span>
            </div>
            <h1 className="mt-1 font-display text-2xl font-bold tracking-tight text-slate-100 sm:text-3xl">
              {course?.title ?? "Practice Studio"}
            </h1>
          </div>

          <div className="flex items-center gap-3">
            {stage !== "preview" && (
              <button
                type="button"
                onClick={() => {
                  cancelCountdown();
                  socketRef.current?.close();
                  void recorderRef.current?.stop();
                  setStage("preview");
                }}
                className={BUTTON_SECONDARY}
              >
                Exit Studio Take
              </button>
            )}
          </div>
        </header>

        {error && (
          <div
            role="alert"
            className="rounded-xl border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-200"
          >
            {error}
          </div>
        )}

        {loading ? (
          <div className={`${CARD} p-12 text-center text-slate-400`}>
            <p className="animate-pulse">Loading coaching studio…</p>
          </div>
        ) : (
          <>
            {/* STAGE 1: REHEARSAL & NOTE SHEET PREVIEW */}
            {stage === "preview" && selectedExercise && (
              <div className="grid gap-6 lg:grid-cols-12">
                {/* Left Column: Exercise Details & Note Breakdown */}
                <div className="lg:col-span-8 space-y-6">
                  {/* Exercise Header & Selector */}
                  <div className={CARD}>
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                      <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Choose Exercise / Drill
                      </label>
                      <select
                        className={`rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 ${FOCUS_RING}`}
                        value={selectedExerciseId ?? ""}
                        onChange={(e) => {
                          setSelectedExerciseId(e.target.value);
                          setCustomBpm(null);
                        }}
                      >
                        {exercises.map((ex) => (
                          <option key={ex.id} value={ex.id}>
                            {ex.title} ({ex.tempo_bpm} BPM · Level {ex.difficulty})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="rounded-xl bg-slate-950/80 border border-slate-800 p-5 space-y-4">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
                        <div>
                          <h2 className="text-xl font-bold text-slate-100">{selectedExercise.title}</h2>
                          <p className="text-xs text-slate-400 mt-0.5">
                            Target Score: {selectedExercise.score_title}
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs font-bold text-red-300">
                            {tempoBpm} BPM
                          </span>
                          <span className="rounded-md border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs font-medium text-slate-300">
                            Difficulty Level {selectedExercise.difficulty}/5
                          </span>
                        </div>
                      </div>

                      <div>
                        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
                          Playing Instructions
                        </h3>
                        <p className="text-sm leading-relaxed text-slate-200 bg-slate-900/60 p-3 rounded-lg border border-slate-800/60">
                          {selectedExercise.instructions ||
                            "Play the exercise cleanly with steady pulse and accurate pitch."}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Tempo Customizer & Metronome Speed Control */}
                  <div className={CARD}>
                    <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                      <div>
                        <h3 className="font-display text-base font-bold text-slate-100 flex items-center gap-2">
                          <span>⏱️ Drill Tempo & Metronome</span>
                          {customBpm !== null && customBpm !== selectedExercise.tempo_bpm && (
                            <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-[10px] font-bold text-red-300 border border-red-500/30">
                              Custom Tempo
                            </span>
                          )}
                        </h3>
                        <p className="text-xs text-slate-400">
                          Adjust the tempo slider to slow down for practice or speed up as you master the exercise.
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setCustomBpm(Math.max(30, tempoBpm - 5))}
                          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-800 bg-slate-900 text-sm font-bold text-slate-200 hover:border-red-500/50 hover:bg-slate-800 transition active:scale-95"
                          title="Decrease tempo by 5 BPM"
                        >
                          -5
                        </button>
                        <div className="flex items-baseline gap-1 rounded-xl border border-red-500/30 bg-red-500/10 px-3.5 py-1 text-red-200 font-mono font-black text-lg shadow-inner">
                          <span>{tempoBpm}</span>
                          <span className="text-[10px] font-sans font-bold text-red-400">BPM</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => setCustomBpm(Math.min(180, tempoBpm + 5))}
                          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-800 bg-slate-900 text-sm font-bold text-slate-200 hover:border-red-500/50 hover:bg-slate-800 transition active:scale-95"
                          title="Increase tempo by 5 BPM"
                        >
                          +5
                        </button>
                      </div>
                    </div>

                    <div className="space-y-4 rounded-xl bg-slate-950/80 border border-slate-800 p-4">
                      {/* Range Slider */}
                      <div className="space-y-1.5">
                        <div className="flex justify-between text-[11px] font-mono text-slate-400">
                          <span>30 BPM (Slow Practice)</span>
                          <span className="font-bold text-slate-300">{(60 / tempoBpm).toFixed(2)}s per beat</span>
                          <span>180 BPM (Presto)</span>
                        </div>
                        <input
                          type="range"
                          min="30"
                          max="180"
                          step="5"
                          value={tempoBpm}
                          onChange={(e) => setCustomBpm(Number(e.target.value))}
                          className="w-full h-2.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-red-500 focus:outline-none focus:ring-2 focus:ring-red-500/50"
                        />
                      </div>

                      {/* Quick Preset Buttons */}
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mr-1">
                          Presets:
                        </span>
                        {[
                          { bpm: 40, label: "40 Slow Practice" },
                          { bpm: 60, label: "60 Relaxed Standard" },
                          { bpm: 80, label: "80 Flow Pace" },
                          { bpm: 100, label: "100 Upbeat" },
                        ].map((preset) => (
                          <button
                            key={preset.bpm}
                            type="button"
                            onClick={() => setCustomBpm(preset.bpm)}
                            className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition-all ${
                              tempoBpm === preset.bpm
                                ? "bg-red-600 text-white shadow-md shadow-red-600/30 ring-1 ring-red-400"
                                : "bg-slate-900 border border-slate-800 text-slate-300 hover:border-slate-700 hover:text-slate-100"
                            }`}
                          >
                            {preset.label}
                          </button>
                        ))}
                        {customBpm !== null && (
                          <button
                            type="button"
                            onClick={() => setCustomBpm(null)}
                            className="ml-auto text-[11px] font-semibold text-slate-400 hover:text-red-400 underline transition"
                          >
                            Reset ({selectedExercise.tempo_bpm} BPM)
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Note Sheet / Visual Sequence Preview */}
                  <div className={CARD}>
                    <div className="mb-4 flex items-center justify-between">
                      <div>
                        <h3 className="font-display text-base font-bold text-slate-100">Notes to Play</h3>
                        <p className="text-xs text-slate-400">
                          Click any note card to highlight its key and preview its tone before recording.
                        </p>
                      </div>
                      <span className="text-xs text-slate-400 font-mono">
                        {selectedExercise.notes?.length ?? 0} notes · {selectedExercise.duration_beats}{" "}
                        beats
                      </span>
                    </div>

                    {selectedExercise.notes && selectedExercise.notes.length > 0 ? (
                      <div className="space-y-4">
                        <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2.5">
                          {selectedExercise.notes.map((note, idx) => {
                            const isSelected = previewNoteIndex === idx;
                            return (
                              <button
                                key={idx}
                                type="button"
                                onClick={() => {
                                  setPreviewNoteIndex(idx);
                                  if (note.pitch_midi !== null) playMidiTone(note.pitch_midi);
                                }}
                                className={`group flex flex-col items-center justify-between rounded-xl border p-3 text-center transition-all hover:scale-105 active:scale-95 ${
                                  isSelected
                                    ? "border-red-500 bg-red-500/20 text-red-100 shadow-lg shadow-red-500/40 ring-2 ring-red-500/60"
                                    : "border-slate-800 bg-slate-950 text-slate-100 hover:border-red-500/50 hover:bg-slate-900"
                                }`}
                                title={
                                  note.pitch_midi
                                    ? `MIDI ${note.pitch_midi} · Click to highlight & hear tone`
                                    : undefined
                                }
                              >
                                <span
                                  className={`text-[10px] font-mono ${
                                    isSelected
                                      ? "text-red-300 font-bold"
                                      : "text-slate-500 group-hover:text-red-400"
                                  }`}
                                >
                                  #{idx + 1}
                                </span>
                                <span
                                  className={`my-1.5 font-display text-lg font-black ${
                                    isSelected
                                      ? "text-red-200"
                                      : "text-slate-100 group-hover:text-red-300"
                                  }`}
                                >
                                  {note.note_name}
                                </span>
                                <span className="text-[10px] text-slate-400">
                                  Beat {note.onset_beats + 1}
                                </span>
                                {note.fret !== null && (
                                  <span className="mt-1 text-[9px] text-red-400 font-mono">
                                    Fret {note.fret}
                                  </span>
                                )}
                              </button>
                            );
                          })}
                        </div>

                        {/* Interactive Instrument Diagram (Fretboard or Keyboard) */}
                        <div className="pt-2">
                          <InstrumentVisualizer
                            exercise={selectedExercise}
                            activeNote={
                              previewNoteIndex !== null
                                ? selectedExercise.notes?.[previewNoteIndex]
                                : null
                            }
                            allNotes={selectedExercise.notes ?? []}
                            onNoteClick={(midi) => playMidiTone(midi)}
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="rounded-xl border border-dashed border-slate-800 p-8 text-center text-xs text-slate-400">
                        Follow the playing instructions at {tempoBpm} BPM.
                      </div>
                    )}
                  </div>
                </div>

                {/* Right Column: Pre-Flight Checklist, AI Live Tips & Start Take CTA */}
                <div className="lg:col-span-4 space-y-6">
                  {/* AI Live Coach Card */}
                  <div className={`${CARD} border-red-500/30 bg-slate-900/50 relative overflow-hidden space-y-4`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="relative flex h-3 w-3">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
                        </span>
                        <h3 className="font-display text-sm font-bold uppercase tracking-wider text-red-300">
                          AI Live Coach Insights
                        </h3>
                      </div>
                      <button
                        type="button"
                        onClick={() => void fetchLiveAiTip()}
                        disabled={isFetchingTip}
                        className="rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs font-bold text-red-300 hover:bg-red-500/20 disabled:opacity-50 transition"
                      >
                        {isFetchingTip ? "Thinking…" : "💡 Ask for AI Tip"}
                      </button>
                    </div>

                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 space-y-2.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-slate-400">Focus Area:</span>
                        <span className="font-bold text-red-300 rounded bg-red-500/10 px-2 py-0.5 border border-red-500/20">
                          {aiTip?.focus_area ?? "Ergonomics & Pacing"}
                        </span>
                      </div>
                      <p className="text-xs leading-relaxed text-slate-200">
                        {aiTip?.tip ??
                          `At ${tempoBpm} BPM, prioritize clean articulation over speed. Use relaxed wrist movement and let each note ring evenly.`}
                      </p>
                      {aiTip?.suggested_action && (
                        <div className="rounded-lg bg-slate-900 p-2.5 border border-slate-800/80">
                          <span className="text-[10px] font-bold uppercase tracking-wider text-red-400 block mb-0.5">
                            Actionable Cue
                          </span>
                          <p className="text-xs font-medium text-slate-300">{aiTip.suggested_action}</p>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className={CARD}>
                    <h3 className="font-display text-base font-bold text-slate-100 mb-3">
                      Live Coach Briefing
                    </h3>
                    <ul className="space-y-3 text-xs text-slate-300 mb-6">
                      <li className="flex items-start gap-2.5">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-500/20 text-red-300 font-bold">
                          1
                        </span>
                        <div>
                          <strong className="text-slate-100">Review Notes:</strong> Inspect the note cards
                          or click them to hear expected pitches on the red keyboard/fretboard.
                        </div>
                      </li>
                      <li className="flex items-start gap-2.5">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-500/20 text-red-300 font-bold">
                          2
                        </span>
                        <div>
                          <strong className="text-slate-100">Custom Tempo:</strong> Practicing at {tempoBpm} BPM.
                          Adjust anytime using the tempo slider on the left.
                        </div>
                      </li>
                      <li className="flex items-start gap-2.5">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-500/20 text-red-300 font-bold">
                          3
                        </span>
                        <div>
                          <strong className="text-slate-100">Phrase Rests:</strong> Pause briefly at
                          measure boundaries (~0.6s) to allow the coach to speak corrections.
                        </div>
                      </li>
                    </ul>

                    <button
                      type="button"
                      onClick={triggerCountdown}
                      className={`w-full py-3.5 text-base font-bold rounded-xl bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-600/30 transition-all flex items-center justify-center gap-2 ${FOCUS_RING}`}
                    >
                      <span>Start Coached Take ({tempoBpm} BPM)</span>
                      <span className="text-lg">🎙️</span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* COUNTDOWN STAGE: GET READY BEFORE RECORDING */}
            {stage === "countdown" && selectedExercise && (
              <div
                className={`${CARD} p-12 text-center space-y-6 flex flex-col items-center justify-center min-h-[460px]`}
              >
                <div className="space-y-2">
                  <span className="text-xs uppercase tracking-widest font-bold text-red-400">
                    Count-In · Get Ready
                  </span>
                  <h2 className="text-3xl font-black text-slate-100">{selectedExercise.title}</h2>
                  <p className="text-xs text-slate-400">
                    Drill Tempo: {tempoBpm} BPM · Starting in...
                  </p>
                </div>

                <div className="relative flex items-center justify-center my-8">
                  {/* Outer Pulsing Glow Rings Synchronized to 1.2s */}
                  <div
                    key={`ring-ping-${countdownValue}`}
                    className="absolute h-56 w-56 rounded-full bg-red-500/20 animate-ping pointer-events-none"
                    style={{ animationDuration: "1.2s" }}
                  />
                  <div
                    key={`ring-pulse-${countdownValue}`}
                    className="absolute h-48 w-48 rounded-full border-2 border-red-500/50 animate-pulse pointer-events-none"
                    style={{ animationDuration: "1.2s" }}
                  />

                  {/* Main Center Countdown Dial */}
                  <div
                    key={`dial-${countdownValue}`}
                    className="relative flex h-40 w-40 sm:h-44 sm:w-44 items-center justify-center rounded-full bg-gradient-to-br from-red-500 via-rose-600 to-red-700 text-white shadow-2xl shadow-red-500/60 transform transition-all duration-300 scale-100 hover:scale-105"
                  >
                    {countdownValue > 0 ? (
                      <span className="font-display text-6xl sm:text-7xl font-black tracking-tighter drop-shadow-md">
                        {countdownValue}
                      </span>
                    ) : (
                      <div className="flex flex-col items-center justify-center">
                        <span className="font-display text-3xl sm:text-4xl font-black tracking-wider uppercase drop-shadow-md">
                          PLAY!
                        </span>
                        <span className="text-sm font-bold opacity-90 mt-0.5">🎵</span>
                      </div>
                    )}
                  </div>
                </div>

                <p className="text-sm font-medium text-slate-300 max-w-md">
                  Position your fingers on the keyboard or fretboard. The coach will begin listening when the count reaches zero.
                </p>

                <button
                  type="button"
                  onClick={cancelCountdown}
                  className={`${BUTTON_SECONDARY} px-6 py-2.5 text-sm font-semibold hover:border-rose-500/50 hover:text-rose-200 transition`}
                >
                  Cancel Countdown
                </button>
              </div>
            )}

            {/* STAGE 2: ACTIVE LIVE COACHED TAKE */}
            {(stage === "connecting" || stage === "listening" || stage === "scoring") && (
              <div className="space-y-6">
                {/* Active Header & Metronome Strip */}
                <div className={`${CARD} p-6 space-y-6`}>
                  <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
                    <div>
                      <span className="text-xs uppercase tracking-wider text-red-400 font-semibold">
                        Live Coached Take
                      </span>
                      <h2 className="text-2xl font-bold text-slate-100">{selectedExercise?.title}</h2>
                    </div>

                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => void stopTake()}
                        disabled={stage !== "listening"}
                        className="rounded-xl bg-rose-600 px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-rose-600/30 hover:bg-rose-500 disabled:opacity-50 transition"
                      >
                        Stop & Score Take ⏹️
                      </button>
                    </div>
                  </div>

                  {/* Large Visual Metronome Pulse Bar */}
                  <div className="rounded-2xl border border-slate-800 bg-slate-950 p-6 flex flex-col sm:flex-row items-center justify-between gap-6">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Tempo Pulse
                      </p>
                      <p className="text-xl font-black text-slate-100">{tempoBpm} BPM</p>
                    </div>

                    <div className="flex items-center gap-3" aria-label={`Beat ${displayedBeat}`}>
                      {[1, 2, 3, 4].map((beatNum) => {
                        const isActive = displayedBeat === beatNum;
                        const isDownbeat = beatNum === 1;
                        return (
                          <div
                            key={beatNum}
                            className={`flex h-14 w-14 sm:h-16 sm:w-16 items-center justify-center rounded-2xl font-display text-xl sm:text-2xl font-black transition-all duration-100 ${
                              isActive
                                ? isDownbeat
                                  ? "bg-red-500 text-white scale-110 shadow-lg shadow-red-500/60 ring-2 ring-red-400/50"
                                  : "bg-rose-500 text-white scale-105 shadow-lg shadow-rose-500/50"
                                : "bg-slate-900 border border-slate-800 text-slate-500"
                            }`}
                          >
                            {beatNum}
                          </div>
                        );
                      })}
                    </div>

                    <div className="text-right">
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Progress
                      </p>
                      <p className="text-xl font-black text-red-400">{progress}%</p>
                    </div>
                  </div>

                  {/* Active Instructions Reminder */}
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
                      Drill Objective
                    </p>
                    <p className="text-sm font-medium text-slate-200">
                      {selectedExercise?.instructions}
                    </p>
                  </div>

                  {/* Live Visual Instrument & Note Highway */}
                  {selectedExercise && (
                    <div className="space-y-4">
                      {/* Live Instrument Visualizer (Lights up active key/fret instantly) */}
                      <InstrumentVisualizer
                        exercise={selectedExercise}
                        activeNote={selectedExercise.notes?.[cue?.cursor ?? 0] ?? null}
                        allNotes={selectedExercise.notes ?? []}
                        onNoteClick={(midi) => playMidiTone(midi)}
                      />

                      {/* Live Highway */}
                      {selectedExercise.notes && selectedExercise.notes.length > 0 && (
                        <NoteHighway
                          notes={selectedExercise.notes}
                          cursor={cue?.cursor ?? 0}
                          expectedCount={cue?.expected_note_count ?? selectedExercise.notes.length}
                        />
                      )}
                    </div>
                  )}

                  {/* Real-time AI Coach Live Guidance Section */}
                  <div className="rounded-2xl border border-red-500/30 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-5 space-y-4 shadow-xl">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5">
                        <span className="relative flex h-3 w-3">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
                        </span>
                        <h3 className="font-display text-sm font-bold uppercase tracking-wider text-red-200 flex items-center gap-2">
                          <span>🤖 Real-Time AI Coach Analysis</span>
                          <span className="text-[10px] font-normal text-slate-400 border border-slate-800 bg-slate-900 px-2 py-0.5 rounded-full">
                            Live Stream
                          </span>
                        </h3>
                      </div>

                      <button
                        type="button"
                        onClick={() => void fetchLiveAiTip()}
                        disabled={isFetchingTip}
                        className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs font-bold text-red-300 hover:bg-red-500/20 disabled:opacity-50 transition flex items-center gap-1.5"
                      >
                        <span>{isFetchingTip ? "Analyzing…" : "💡 Instant AI Tip"}</span>
                      </button>
                    </div>

                    {/* Live Streamed Verbal Utterance Bubble */}
                    {utterance !== null && utterance.streaming && (
                      <div className="rounded-xl border border-red-500/50 bg-red-500/20 p-4 text-red-100 shadow-lg shadow-red-500/20 animate-pulse">
                        <div className="flex items-center gap-2 text-xs font-bold text-red-300 mb-1">
                          <span>🗣️ Live Coach Speaking:</span>
                        </div>
                        <p className="text-base font-semibold leading-relaxed">{utterance.text}▍</p>
                      </div>
                    )}

                    {/* Contextual Real-Time Insight Cards */}
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3.5 space-y-1">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                          AI Pedagogical Focus
                        </span>
                        <p className="text-xs text-slate-200 leading-relaxed">
                          {aiTip?.tip ??
                            (currentActiveNote
                              ? `Playing ${currentActiveNote.note_name} on Beat ${currentActiveNote.onset_beats + 1}. Keep wrists supple and land evenly on the ${tempoBpm} BPM click.`
                              : `Maintain a steady pulse lock with the ${tempoBpm} BPM downbeat.`)}
                        </p>
                        {aiTip?.suggested_action && (
                          <p className="text-[11px] font-medium text-red-300 pt-1 border-t border-slate-800/80 mt-1">
                            🎯 {aiTip.suggested_action}
                          </p>
                        )}
                      </div>

                      <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3.5 space-y-1">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                          Micro-Timing & Pitch Bias
                        </span>
                        <p className="text-xs text-slate-200">
                          {cue?.signed_timing_bias_seconds !== null && cue?.signed_timing_bias_seconds !== undefined
                            ? cue.signed_timing_bias_seconds < -0.03
                              ? `Rushing by +${Math.abs(Math.round(cue.signed_timing_bias_seconds * 1000))}ms. Relax slightly.`
                              : cue.signed_timing_bias_seconds > 0.03
                              ? `Dragging by -${Math.abs(Math.round(cue.signed_timing_bias_seconds * 1000))}ms. Prepare finger early.`
                              : "Timing is right on the center of the beat! ✨"
                            : "Listening to live note attacks…"}
                        </p>
                        <p className="text-[11px] text-slate-400">
                          Pace: {(60 / tempoBpm).toFixed(2)}s per beat · {cue?.matched_count ?? 0} notes matched
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Live Cue Badge & Real-Time Stats */}
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Live Readout
                      </span>
                      <p
                        className={`mt-1 text-sm font-bold ${
                          currentCueInfo?.tone ?? "text-slate-300"
                        }`}
                      >
                        {currentCueInfo?.label ?? "Listening for notes…"}
                      </p>
                    </div>

                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-center">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Matched Notes
                      </span>
                      <p className="mt-1 font-display text-2xl font-black text-emerald-400">
                        {cue?.matched_count ?? 0}
                      </p>
                    </div>

                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-center">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Missed Notes
                      </span>
                      <p className="mt-1 font-display text-2xl font-black text-rose-400">
                        {cue?.missed_count ?? 0}
                      </p>
                    </div>

                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-center">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Extra Notes
                      </span>
                      <p className="mt-1 font-display text-2xl font-black text-amber-400">
                        {cue?.extra_count ?? 0}
                      </p>
                    </div>
                  </div>

                  {/* Transcript History */}
                  {transcript.length > 0 && (
                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 space-y-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Coach Guidance Log
                      </h4>
                      <div className="space-y-1.5 max-h-40 overflow-y-auto">
                        {transcript.map((line, idx) => (
                          <p key={idx} className="rounded-lg bg-slate-900 px-3 py-2 text-xs text-slate-200">
                            {line}
                          </p>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STAGE 3: COMPREHENSIVE PERFORMANCE DEBRIEF */}
            {stage === "result" && attempt && (
              <div className="space-y-6">
                <div className={`${CARD} p-8 space-y-6`}>
                  <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-6">
                    <div>
                      <span className="text-xs font-bold uppercase tracking-wider text-emerald-400">
                        Take Graded & Finalized
                      </span>
                      <h2 className="text-3xl font-black text-slate-100 mt-1">
                        {selectedExercise?.title}
                      </h2>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className="rounded-2xl border border-emerald-500/40 bg-emerald-500/10 px-6 py-3 text-center">
                        <p className="text-xs uppercase font-bold tracking-wider text-emerald-400">
                          Overall Grade
                        </p>
                        <p className="font-display text-3xl font-black text-emerald-300">
                          {Math.round(attempt.overall_score * 100)}%
                        </p>
                      </div>

                      <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-6 py-3 text-center">
                        <p className="text-xs uppercase font-bold tracking-wider text-red-400">Reward</p>
                        <p className="font-display text-3xl font-black text-red-300">
                          +{attempt.exp_awarded} EXP
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Examiner Overview */}
                  <div className="rounded-2xl border border-slate-800 bg-slate-950 p-6 space-y-4">
                    <h3 className="font-display text-lg font-bold text-slate-100">
                      Examiner Assessment
                    </h3>
                    <p className="text-base text-slate-200 leading-relaxed">
                      {attempt.feedback.summary}
                    </p>

                    <div className="grid gap-6 md:grid-cols-2 pt-2 border-t border-slate-800/80">
                      {attempt.feedback.strengths && attempt.feedback.strengths.length > 0 && (
                        <div>
                          <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-2">
                            Key Strengths
                          </h4>
                          <ul className="space-y-1.5 text-sm text-slate-300">
                            {attempt.feedback.strengths.map((str, idx) => (
                              <li key={idx} className="flex items-start gap-2">
                                <span className="text-emerald-400 font-bold">✓</span>
                                <span>{str}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {attempt.feedback.corrections && attempt.feedback.corrections.length > 0 && (
                        <div>
                          <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400 mb-2">
                            Focus Areas / Corrections
                          </h4>
                          <ul className="space-y-1.5 text-sm text-slate-300">
                            {attempt.feedback.corrections.map((corr, idx) => (
                              <li key={idx} className="flex items-start gap-2">
                                <span className="text-amber-400 font-bold">!</span>
                                <span>{corr}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>

                    {attempt.feedback.next_step && (
                      <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
                        <span className="font-bold text-red-300">Recommended Next Step: </span>
                        {attempt.feedback.next_step}
                      </div>
                    )}
                  </div>

                  {/* Action Buttons */}
                  <div className="flex flex-wrap items-center gap-4 pt-4">
                    <button
                      type="button"
                      onClick={() => setStage("preview")}
                      className={`px-6 py-3 font-bold rounded-xl bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-600/30 transition ${FOCUS_RING}`}
                    >
                      Practice Again 🔄
                    </button>
                    <Link
                      href={`/courses/${courseId}`}
                      className={`px-6 py-3 font-bold ${BUTTON_SECONDARY}`}
                    >
                      Return to Course Graph 🗺️
                    </Link>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}

/** Memoized lightweight note highway to prevent full DOM re-renders during active takes */
const NoteHighway = memo(function NoteHighway({
  notes,
  cursor,
  expectedCount,
}: {
  notes: ExerciseNote[];
  cursor: number;
  expectedCount: number;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>Note Sequence Highway</span>
        <span>
          Note {cursor} of {expectedCount}
        </span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-3 pt-1">
        {notes.map((note, idx) => {
          const isCurrent = cursor === idx;
          const isPast = cursor > idx;
          return (
            <div
              key={idx}
              className={`flex min-w-[70px] flex-col items-center justify-between rounded-xl border p-3 text-center transition-transform duration-100 ${
                isCurrent
                  ? "border-red-500 bg-red-500/20 text-red-100 scale-110 shadow-lg shadow-red-500/50 ring-2 ring-red-400/60"
                  : isPast
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                    : "border-slate-800 bg-slate-950 text-slate-400 opacity-60"
              }`}
            >
              <span className="text-[10px] font-mono opacity-80">#{idx + 1}</span>
              <span className="my-1 font-display text-lg font-black">{note.note_name}</span>
              <span className="text-[10px]">Beat {note.onset_beats + 1}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

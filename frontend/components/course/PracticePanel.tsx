"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { MicRecorder } from "@/lib/pitchDetection";
import type { Exercise, PerformanceAttempt, PerformedNote } from "@/lib/types";
import { CARD, FOCUS_RING } from "@/lib/ui";

interface PracticePanelProps {
  courseId: string;
  refreshKey: number;
  onCompleted: () => void;
  /**
   * The exercise the learner chose elsewhere -- in a skill's realm, where the
   * lesson run actually lives. Null leaves the panel on its own selection, so
   * the dropdown still works when nobody has picked from a realm.
   */
  exerciseId?: string | null;
  /**
   * The exercise is not the learner's to choose here -- they picked a lesson in
   * a realm and this is that lesson. Hides the picker, so the panel cannot
   * silently become a different exercise than the one they clicked.
   */
  pinned?: boolean;
}

/**
 * A flawless take of whatever exercise is selected, played from its own score.
 *
 * This used to be four hard-coded notes -- a C-D-E-F run that was perfect for
 * exactly one piano exercise and scored around 12% against everything else. It
 * held while each skill had one hand-written exercise. It stopped holding the
 * moment skills grew generated lesson runs, and it took the whole no-microphone
 * path down with it: every lesson failed, so no lesson cleared, so no test ever
 * opened.
 *
 * Beats become seconds through the exercise's own tempo, which is the same
 * conversion the scorer does on the other side.
 */
function perfectTakeOf(exercise: Exercise): PerformedNote[] {
  const secondsPerBeat = 60 / (exercise.tempo_bpm || 60);
  return (exercise.notes ?? [])
    .filter((note) => note.pitch_midi !== null)
    .map((note) => ({
      pitch_midi: note.pitch_midi as number,
      onset_seconds: note.onset_beats * secondsPerBeat,
      duration_seconds: note.duration_beats * secondsPerBeat,
      confidence: 1,
    }));
}

const RECORD_STATUS_LABEL: Record<string, string> = {
  idle: "Ready",
  requesting: "Requesting microphone…",
  listening: "Listening — play the exercise, then stop",
  stopping: "Scoring take…",
};

// @spec CAP-PERM-002
export function PracticePanel({ courseId, refreshKey, onCompleted, exerciseId, pinned = false }: PracticePanelProps) {
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [selectedExerciseId, setSelectedExerciseId] = useState<string | null>(null);

  // A realm choosing a lesson wins over whatever the dropdown was showing:
  // the learner just clicked the thing they want to play.
  useEffect(() => {
    if (exerciseId) setSelectedExerciseId(exerciseId);
  }, [exerciseId]);
  const [result, setResult] = useState<PerformanceAttempt | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recordStatus, setRecordStatus] = useState<string>("idle");
  const recorderRef = useRef<MicRecorder | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .listPracticeExercises(courseId)
      .then((items) => {
        if (!cancelled) {
          setExercises(items);
          setSelectedExerciseId((current) => current ?? items[0]?.id ?? null);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load exercises.");
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, refreshKey]);

  useEffect(() => {
    return () => {
      recorderRef.current?.stop();
    };
  }, []);

  async function submitNotes(notes: PerformedNote[], label: string, recordingId: string | null = null) {
    if (selectedExerciseId === null) return;
    setLoading(true);
    setError(null);
    try {
      const session = await api.createPracticeSession(selectedExerciseId);
      const attempt = await api.submitPerformanceAttempt(session.id, notes, crypto.randomUUID(), recordingId);
      setResult(attempt);
      setRecordStatus(`Recorded ${label} · ${attempt.metrics.observed_note_count} notes detected`);
      onCompleted();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Performance submission failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runFixturePerformance() {
    const exercise = exercises.find((candidate) => candidate.id === selectedExerciseId);
    if (exercise === undefined) return;
    const take = perfectTakeOf(exercise);
    if (take.length === 0) {
      // A rhythm-only score has no pitches to replay. Saying so beats
      // submitting an empty take and showing the learner a 0%.
      setError("This exercise has no written pitches, so there is nothing to replay. Record it instead.");
      return;
    }
    await submitNotes(take, "fixture");
  }

  async function speakFeedback() {
    if (result === null) return;
    setError(null);
    try {
      const artifact = await api.speakAttemptFeedback(result.id);
      if (artifact.audio_base64 !== null) {
        const audio = new Audio(`data:audio/${artifact.format};base64,${artifact.audio_base64}`);
        void audio.play();
      } else if (typeof window !== "undefined" && "speechSynthesis" in window) {
        const utterance = new SpeechSynthesisUtterance(artifact.spoken_text);
        window.speechSynthesis.speak(utterance);
      }
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Could not speak the feedback.");
    }
  }

  async function toggleRecording() {
    if (recorderRef.current !== null && recorderRef.current.currentStatus === "listening") {
      const recorder = recorderRef.current;
      recorderRef.current = null;
      setRecordStatus("stopping");
      const take = await recorder.stopTake();
      if (take.notes.length === 0) {
        setError("No notes were detected. Try again closer to the microphone.");
        setRecordStatus("idle");
        return;
      }
      let recordingId: string | null = null;
      if (take.blob !== null) {
        try {
          const recording = await api.uploadRecording(courseId, take.blob, take.durationSeconds);
          recordingId = recording.id;
        } catch (caught: unknown) {
          // A failed upload must not sink the take — the notes are the score.
          setError(
            `Recording could not be preserved (${caught instanceof Error ? caught.message : "upload failed"}). The take was still scored.`,
          );
        }
      }
      await submitNotes(take.notes, "performance", recordingId);
      return;
    }
    setError(null);
    try {
      const recorder = new MicRecorder(setRecordStatus);
      recorderRef.current = recorder;
      await recorder.start();
    } catch (caught: unknown) {
      recorderRef.current = null;
      setRecordStatus("idle");
      setError(caught instanceof Error ? caught.message : "Could not start the microphone.");
    }
  }

  const listening = recordStatus === "listening";

  return (
    <section className={CARD} aria-labelledby="practice-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="practice-heading" className="font-display text-sm font-semibold">Practice</h2>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
            Record with your microphone and the browser turns the take into note observations, or run the
            deterministic fixture. Both use the same submission contract.
          </p>
        </div>
        <span className="rounded-full border border-cyan-900/60 bg-cyan-950/20 px-2 py-1 text-[10px] text-cyan-300">
          {listening ? "LIVE" : "DTW"}
        </span>
      </div>

      {exercises.length > 0 ? (
        <>
          {pinned ? null : (
            <>
              <label className="mt-3 block text-[11px] text-slate-400" htmlFor="practice-exercise">
                Exercise
              </label>
              <select
                id="practice-exercise"
                value={selectedExerciseId ?? ""}
                onChange={(event) => setSelectedExerciseId(event.target.value)}
                className={`mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-xs text-slate-200 ${FOCUS_RING}`}
              >
                {exercises.map((exercise) => (
                  <option key={exercise.id} value={exercise.id}>
                    {exercise.title} · {exercise.tempo_bpm} BPM
                  </option>
                ))}
              </select>
            </>
          )}
          <button
            type="button"
            disabled={loading || selectedExerciseId === null || recordStatus === "requesting"}
            onClick={() => void toggleRecording()}
            className={`mt-3 w-full rounded-md border px-3 py-2 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING} ${
              listening
                ? "border-rose-800 bg-rose-950/40 text-rose-200 hover:bg-rose-900/50"
                : "border-cyan-800 bg-cyan-950/40 text-cyan-200 hover:bg-cyan-900/50"
            }`}
          >
            {listening ? "Stop and score recording" : "Record performance"}
          </button>
          <p className="mt-1.5 text-center text-[10px] text-slate-500">{RECORD_STATUS_LABEL[recordStatus] ?? "Ready"}</p>
          <button
            type="button"
            disabled={loading || selectedExerciseId === null || listening}
            onClick={() => void runFixturePerformance()}
            className={`mt-2 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-300 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING}`}
          >
            {loading ? "Scoring performance…" : "Run perfect fixture performance"}
          </button>
        </>
      ) : (
        <p className="mt-3 text-xs text-slate-500">No score-backed exercises are seeded for this course yet.</p>
      )}

      {error && <p className="mt-2 text-xs text-rose-300" role="alert">{error}</p>}
      {result && (
        <div className="mt-3 rounded-md border border-emerald-900/60 bg-emerald-950/20 p-2.5 text-xs">
          <p className="font-medium text-emerald-200">
            Score {Math.round(result.overall_score * 100)}% · +{result.exp_awarded} EXP
          </p>
          <p className="mt-1 text-[11px] text-slate-400">
            {result.metrics.pitch_accuracy !== null && (
              <>Pitch {Math.round(result.metrics.pitch_accuracy * 100)}% · </>
            )}
            rhythm {Math.round(result.metrics.rhythm_accuracy * 100)}% · {result.metrics.missed_note_count} missed · {result.metrics.extra_note_count} extra
            {result.metrics.technique_accuracy !== null && (
              <> · technique {Math.round(result.metrics.technique_accuracy * 100)}%</>
            )}
            {result.metrics.intonation_accuracy !== null && (
              <> · intonation {Math.round(result.metrics.intonation_accuracy * 100)}%</>
            )}
          </p>
          {result.metrics.low_confidence && (
            <p className="mt-1 text-[11px] text-amber-300">Low-confidence alignment — EXP was withheld for review.</p>
          )}
          <p className="mt-2 text-[11px] italic leading-relaxed text-slate-300">
            {result.feedback.persona}: {result.feedback.summary}
          </p>
          {result.feedback.strengths.length > 0 && (
            <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-[11px] text-emerald-300/90">
              {result.feedback.strengths.map((strength) => (
                <li key={strength}>{strength}</li>
              ))}
            </ul>
          )}
          {result.feedback.corrections.length > 0 && (
            <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-[11px] text-amber-300/90">
              {result.feedback.corrections.map((correction) => (
                <li key={correction}>{correction}</li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] text-cyan-300">Next: {result.feedback.next_step}</p>
          <button
            type="button"
            onClick={() => void speakFeedback()}
            className="mt-2 w-full rounded-md border border-violet-800 bg-violet-950/40 px-3 py-1.5 text-[11px] font-medium text-violet-200 transition hover:bg-violet-900/50"
          >
            Speak feedback
          </button>
        </div>
      )}
    </section>
  );
}

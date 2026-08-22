/**
 * Browser microphone capture -> canonical `PerformedNote` observations.
 *
 * This is the missing front of the evaluation boundary: the backend scores
 * canonical note events, and this module produces them from a live recording
 * using only the Web Audio API (no ML, no build dependencies). Pitch is found
 * by normalized autocorrelation over the time-domain buffer, a well-known
 * robust-enough approach for the monophonic fixtures this demo ships.
 *
 * Notes are emitted as `PerformedNote` values with onsets relative to the first
 * detected note, so a short silence before the user starts playing does not
 * penalize rhythm. Guitar position (string/fret) cannot be derived from pitch
 * alone and is left null; the backend scorer handles that explicitly.
 */

import type { PerformedNote } from "@/lib/types";

export interface PitchDetection {
  frequency: number;
  clarity: number;
}

export interface NoteSegment extends PerformedNote {
  pitch_midi: number;
  onset_seconds: number;
  duration_seconds: number;
  confidence: number;
}

/** MIDI pitch of a frequency, in 12-EDO tuning (A4 = 440 Hz = MIDI 69). */
// @spec CAP-PITCH-008
export function frequencyToMidi(frequency: number): number {
  return 69 + 12 * Math.log2(frequency / 440);
}

/**
 * Detect the dominant pitch of one time-domain window by autocorrelation.
 *
 * Returns null for silence or for a window whose periodicity is too weak to
 * trust. `clarity` is the normalized autocorrelation at the winning lag
 * (1.0 = perfect periodicity, 0 = noise).
 */
// @spec CAP-PITCH-001, CAP-PITCH-002, CAP-PITCH-003, CAP-PITCH-004, CAP-PITCH-005, CAP-PITCH-006, CAP-PITCH-007
export function detectPitch(timeDomain: Float32Array, sampleRate: number): PitchDetection | null {
  const size = timeDomain.length;

  let energy = 0;
  for (let i = 0; i < size; i += 1) {
    energy += timeDomain[i] * timeDomain[i];
  }
  if (energy < 1e-6) return null;

  const minLag = Math.max(2, Math.floor(sampleRate / 1200));
  const maxLag = Math.floor(sampleRate / 55);
  if (minLag >= maxLag) return null;

  let bestLag = -1;
  let bestCorrelation = 0;
  for (let lag = minLag; lag <= maxLag; lag += 1) {
    let correlation = 0;
    for (let i = 0; i < size - lag; i += 1) {
      correlation += timeDomain[i] * timeDomain[i + lag];
    }
    if (correlation > bestCorrelation) {
      bestCorrelation = correlation;
      bestLag = lag;
    }
  }
  if (bestLag < 0) return null;

  const clarity = bestCorrelation / energy;
  if (clarity < 0.4) return null;

  // Parabolic interpolation around the winning lag for sub-sample precision.
  const before = bestLag > minLag
    ? (() => {
      let correlation = 0;
      for (let i = 0; i < size - (bestLag - 1); i += 1) {
        correlation += timeDomain[i] * timeDomain[i + bestLag - 1];
      }
      return correlation;
    })()
    : bestCorrelation;
  const after = bestLag < maxLag
    ? (() => {
      let correlation = 0;
      for (let i = 0; i < size - (bestLag + 1); i += 1) {
        correlation += timeDomain[i] * timeDomain[i + bestLag + 1];
      }
      return correlation;
    })()
    : bestCorrelation;
  const denominator = before - 2 * bestCorrelation + after;
  let refinedLag = bestLag;
  if (Math.abs(denominator) > 1e-9) {
    const offset = 0.5 * (before - after) / denominator;
    if (offset > -1 && offset < 1) refinedLag = bestLag + offset;
  }

  return { frequency: sampleRate / refinedLag, clarity };
}

const MIN_NOTE_DURATION_SECONDS = 0.12;
const DEFAULT_CLARITY_THRESHOLD = 0.55;
const PITCH_CHANGE_FRAMES = 6;
// Below this the learner has stopped playing. The coach only speaks at a rest,
// so this threshold is what separates coaching from talking over someone.
const SILENCE_LEVEL_DB = -50;

interface _CurrentNote {
  midi: number;
  onsetSeconds: number;
  confidenceSum: number;
  frames: number;
}

export type RecordingStatus = "idle" | "requesting" | "listening" | "stopping";

/** The preserved raw take plus the canonical notes the scorer will use. */
export interface RecordingTake {
  notes: NoteSegment[];
  /** Null when MediaRecorder is unavailable or produced no data. */
  blob: Blob | null;
  /** The container format of `blob` ("webm"); null when there is no blob. */
  format: string | null;
  /** Wall-clock length of the take in seconds. */
  durationSeconds: number;
}

/**
 * Records a monophonic performance from the microphone and segments it into
 * canonical note observations. Call `start()`, wait for the status to become
 * `listening`, then `stop()` to get the notes.
 */
// @spec CAP-MIC-001, CAP-MIC-002, CAP-MIC-003, CAP-MIC-004, CAP-MIC-005, CAP-MIC-006, CAP-MIC-007, CAP-MIC-008, CAP-PERM-001
export class MicRecorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private timeDomain: Float32Array<ArrayBuffer> | null = null;
  private rafId: number | null = null;
  private startedAt = 0;
  private current: _CurrentNote | null = null;
  private pendingChange = 0;
  private notes: NoteSegment[] = [];
  private status: RecordingStatus = "idle";
  private clarityThreshold = DEFAULT_CLARITY_THRESHOLD;
  private onStatus: (status: RecordingStatus) => void = () => {};
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  private onNote: (note: NoteSegment) => void = () => {};
  private onLevel: (rmsDb: number, silenceSeconds: number) => void = () => {};
  private quietSince: number | null = null;

  /**
   * `options` is how the live coach observes a take as it happens. Both
   * callbacks default to no-ops and `stopTake()`'s return value is unchanged,
   * so the clip path behaves exactly as it did -- which matters, because
   * nothing here is covered by a browser test.
   */
  constructor(
    onStatus: (status: RecordingStatus) => void,
    options: {
      onNote?: (note: NoteSegment) => void;
      onLevel?: (rmsDb: number, silenceSeconds: number) => void;
    } = {},
  ) {
    this.onStatus = onStatus;
    if (options.onNote !== undefined) this.onNote = options.onNote;
    if (options.onLevel !== undefined) this.onLevel = options.onLevel;
  }

  private setStatus(status: RecordingStatus): void {
    this.status = status;
    this.onStatus(status);
  }

  async start(): Promise<void> {
    if (this.status === "listening" || this.status === "requesting") return;
    this.setStatus("requesting");
    this.notes = [];
    this.current = null;
    this.pendingChange = 0;

    const AudioContextCtor = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (AudioContextCtor === undefined) {
      this.setStatus("idle");
      throw new Error("Web Audio is not supported in this browser.");
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.setStatus("idle");
      throw new Error("Microphone access was denied or unavailable.");
    }

    this.context = new AudioContextCtor();
    const source = this.context.createMediaStreamSource(this.stream);
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 4096;
    this.analyser.smoothingTimeConstant = 0;
    source.connect(this.analyser);
    this.timeDomain = new Float32Array(this.analyser.fftSize);
    this.sampleRate = this.context.sampleRate;
    this.startedAt = performance.now();
    // Preserve the raw take alongside the note segmentation. WebM/opus is the
    // only container guaranteed to be supported everywhere MediaRecorder is;
    // when it is not, capture is skipped and the take has no blob.
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported("audio/webm")) {
      this.mediaRecorder = new MediaRecorder(this.stream, { mimeType: "audio/webm" });
      this.chunks = [];
      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) this.chunks.push(event.data);
      };
      this.mediaRecorder.start();
    }
    this.setStatus("listening");
    this.rafId = requestAnimationFrame(this.tick);
  }

  private sampleRate = 48000;

  private tick = (): void => {
    if (this.analyser === null || this.timeDomain === null) return;
    this.analyser.getFloatTimeDomainData(this.timeDomain);
    const now = (performance.now() - this.startedAt) / 1000;
    const detection = detectPitch(this.timeDomain, this.sampleRate);
    const midi = detection === null ? null : Math.round(frequencyToMidi(detection.frequency));
    const clarity = detection === null ? 0 : detection.clarity;

    // Level and silence, for the coach's turn policy. A phrase boundary is the
    // only moment it is allowed to speak, so this is what earns an utterance.
    let energy = 0;
    for (let index = 0; index < this.timeDomain.length; index += 1) {
      energy += this.timeDomain[index] * this.timeDomain[index];
    }
    const rms = Math.sqrt(energy / this.timeDomain.length);
    const rmsDb = rms > 1e-8 ? 20 * Math.log10(rms) : -100;
    if (rmsDb < SILENCE_LEVEL_DB) {
      if (this.quietSince === null) this.quietSince = now;
    } else {
      this.quietSince = null;
    }
    this.onLevel(rmsDb, this.quietSince === null ? 0 : now - this.quietSince);

    if (midi !== null && clarity >= this.clarityThreshold) {
      if (this.current === null) {
        this.current = { midi, onsetSeconds: now, confidenceSum: clarity, frames: 1 };
        this.pendingChange = 0;
      } else if (midi !== this.current.midi) {
        this.pendingChange += 1;
        if (this.pendingChange >= PITCH_CHANGE_FRAMES) {
          this.closeNote(now);
          this.current = { midi, onsetSeconds: now, confidenceSum: clarity, frames: 1 };
          this.pendingChange = 0;
        } else {
          this.current.confidenceSum += clarity;
          this.current.frames += 1;
        }
      } else {
        this.current.confidenceSum += clarity;
        this.current.frames += 1;
        this.pendingChange = 0;
      }
    } else {
      this.pendingChange = 0;
      this.closeNote(now);
    }

    this.rafId = requestAnimationFrame(this.tick);
  };

  private closeNote(now: number): void {
    if (this.current === null) return;
    const duration = now - this.current.onsetSeconds;
    if (duration >= MIN_NOTE_DURATION_SECONDS) {
      const segment: NoteSegment = {
        pitch_midi: this.current.midi,
        onset_seconds: this.current.onsetSeconds,
        duration_seconds: duration,
        confidence: Math.min(1, this.current.confidenceSum / this.current.frames),
        string: null,
        fret: null,
      };
      this.notes.push(segment);
      // The live listener gets the un-normalized onset: the coach follows a
      // wall clock, while `stopTake` rebases onto the first note for scoring.
      this.onNote(segment);
    }
    this.current = null;
  }

  /**
   * Stop the analyser loop and release the microphone, returning the segmented
   * notes (onsets relative to the first note). The MediaRecorder, when one is
   * running, is stopped first so its final chunk lands before the tracks close.
   */
  private teardown(): NoteSegment[] {
    if (this.status !== "listening" && this.status !== "stopping") return [];
    this.setStatus("stopping");
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    const now = (performance.now() - this.startedAt) / 1000;
    this.closeNote(now);

    if (this.stream !== null) {
      for (const track of this.stream.getTracks()) {
        track.stop();
      }
      this.stream = null;
    }
    if (this.context !== null) {
      void this.context.close().catch(() => {});
      this.context = null;
    }
    this.analyser = null;
    this.timeDomain = null;

    const notes = this.notes;
    this.notes = [];
    this.setStatus("idle");

    const ordered = [...notes].sort((left, right) => left.onset_seconds - right.onset_seconds);
    if (ordered.length === 0) return [];
    const firstOnset = ordered[0].onset_seconds;
    return ordered.map((note) => ({
      ...note,
      onset_seconds: Number((note.onset_seconds - firstOnset).toFixed(3)),
      duration_seconds: Number(note.duration_seconds.toFixed(3)),
    }));
  }

  /** Stop recording and return the segmented notes. */
  stop(): NoteSegment[] {
    if (this.status !== "listening") return [];
    // A running MediaRecorder must be stopped synchronously enough that its
    // final dataavailable event fires before the tracks close; `stop()` alone
    // is used on unmount where the blob is discarded anyway.
    if (this.mediaRecorder !== null && this.mediaRecorder.state === "recording") {
      try {
        this.mediaRecorder.stop();
      } catch {
        // The stream is already gone; nothing to preserve.
      }
      this.mediaRecorder = null;
      this.chunks = [];
    }
    return this.teardown();
  }

  /**
   * Stop and collect the full take: the segmented notes plus the preserved raw
   * audio blob (null when MediaRecorder could not capture it).
   */
  async stopTake(): Promise<RecordingTake> {
    const durationSeconds = this.status === "listening"
      ? Number(((performance.now() - this.startedAt) / 1000).toFixed(1))
      : 0;
    let blob: Blob | null = null;
    if (this.mediaRecorder !== null && this.mediaRecorder.state === "recording") {
      const recorder = this.mediaRecorder;
      this.mediaRecorder = null;
      blob = await new Promise<Blob | null>((resolve) => {
        recorder.onstop = () => {
          const chunks = this.chunks;
          this.chunks = [];
          if (chunks.length === 0) {
            resolve(null);
            return;
          }
          resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
        };
        try {
          recorder.stop();
        } catch {
          this.chunks = [];
          resolve(null);
        }
      });
    } else {
      this.chunks = [];
    }
    const notes = this.teardown();
    return { notes, blob, format: blob === null ? null : "webm", durationSeconds };
  }

  get currentStatus(): RecordingStatus {
    return this.status;
  }
}

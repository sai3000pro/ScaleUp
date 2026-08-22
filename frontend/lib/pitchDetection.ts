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
  if (energy < 1e-8) return null;

  const minLag = Math.max(2, Math.floor(sampleRate / 1200));
  const maxLag = Math.floor(sampleRate / 55);
  if (minLag >= maxLag) return null;

  const correlations = new Float32Array(maxLag + 2);
  let bestLag = -1;
  let bestCorrelation = 0;
  for (let lag = minLag; lag <= maxLag; lag += 1) {
    let correlation = 0;
    for (let i = 0; i < size - lag; i += 1) {
      correlation += timeDomain[i] * timeDomain[i + lag];
    }
    correlations[lag] = correlation;
    if (correlation > bestCorrelation) {
      bestCorrelation = correlation;
      bestLag = lag;
    }
  }
  if (bestLag < 0) return null;

  const clarity = bestCorrelation / energy;
  if (clarity < 0.12) return null;

  // Subharmonic correction: only divide lag if the shorter lag is genuinely as periodic (>= 0.92)
  for (const divisor of [2, 3, 4]) {
    const subLag = Math.round(bestLag / divisor);
    if (subLag >= minLag && subLag <= maxLag) {
      // Find local peak around subLag
      let localMax = subLag;
      for (let delta = -2; delta <= 2; delta += 1) {
        const testLag = subLag + delta;
        if (testLag >= minLag && testLag <= maxLag && correlations[testLag] > correlations[localMax]) {
          localMax = testLag;
        }
      }
      if (correlations[localMax] >= bestCorrelation * 0.92) {
        bestLag = localMax;
        bestCorrelation = correlations[localMax];
        break;
      }
    }
  }

  // Parabolic interpolation around the winning lag for sub-sample precision.
  const before = bestLag > minLag ? correlations[bestLag - 1] : bestCorrelation;
  const after = bestLag < maxLag ? correlations[bestLag + 1] : bestCorrelation;
  const denominator = before - 2 * bestCorrelation + after;
  let refinedLag = bestLag;
  if (Math.abs(denominator) > 1e-9) {
    const offset = 0.5 * (before - after) / denominator;
    if (offset > -1 && offset < 1) refinedLag = bestLag + offset;
  }

  return { frequency: sampleRate / refinedLag, clarity };
}

const MIN_NOTE_DURATION_SECONDS = 0.12;
const DEFAULT_CLARITY_THRESHOLD = 0.32;
const PITCH_CHANGE_FRAMES = 4;
const SILENCE_FRAMES_TO_CLOSE = 10;
const NEW_NOTE_CONFIRM_FRAMES = 3;
// Below this the learner has stopped playing. The coach only speaks at a rest,
// so this threshold is what separates coaching from talking over someone.
const SILENCE_LEVEL_DB = -48;

import {
  DEFAULT_SEGMENTER_CONFIG,
  finalizeSegments,
  initialSegmenterState,
  pushFrame,
  type PitchFrame,
  type SegmenterConfig,
  type SegmenterState,
} from "@/lib/noteSegmentation";

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
  private status: RecordingStatus = "idle";
  private onStatus: (status: RecordingStatus) => void = () => {};
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  private onNote: (note: NoteSegment) => void = () => {};
  private onLevel: (rmsDb: number, silenceSeconds: number) => void = () => {};
  private quietSince: number | null = null;

  private segmenterState: SegmenterState = initialSegmenterState();
  private segmenterConfig: SegmenterConfig = {
    ...DEFAULT_SEGMENTER_CONFIG,
    confidenceOn: 0.42,
    confidenceOff: 0.28,
    noteOnRmsDb: -38,
    noteOffRmsDb: -48,
    pitchChangeFrames: 6,
    minNoteDurationSeconds: 0.16,
    pitchMedianWindow: 5,
    reattackRiseDb: 10,
    noteOffFrames: 5,
  };

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
    if (this.status !== "idle") return;
    this.setStatus("requesting");

    const AudioContextCtor = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (AudioContextCtor === undefined) {
      this.setStatus("idle");
      throw new Error("Web Audio is not supported in this browser.");
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
    } catch {
      this.setStatus("idle");
      throw new Error("Microphone access was denied or unavailable.");
    }

    this.context = new AudioContextCtor();
    const source = this.context.createMediaStreamSource(this.stream);

    // Hardware/DSP Biquad Bandpass Filter to isolate musical instruments & reject room noise
    const highpass = this.context.createBiquadFilter();
    highpass.type = "highpass";
    highpass.frequency.value = 65; // Strip sub-bass rumble, HVAC hum & handling thumps

    const lowpass = this.context.createBiquadFilter();
    lowpass.type = "lowpass";
    lowpass.frequency.value = 3600; // Strip high frequency hiss & room clicks

    source.connect(highpass);
    highpass.connect(lowpass);

    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 4096;
    this.analyser.smoothingTimeConstant = 0;
    lowpass.connect(this.analyser);

    this.timeDomain = new Float32Array(this.analyser.fftSize);
    this.sampleRate = this.context.sampleRate;
    this.startedAt = performance.now();
    this.segmenterState = initialSegmenterState();

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
    const midiExact = detection === null ? null : frequencyToMidi(detection.frequency);
    const clarity = detection === null ? 0 : detection.clarity;

    let energy = 0;
    for (let index = 0; index < this.timeDomain.length; index += 1) {
      energy += this.timeDomain[index] * this.timeDomain[index];
    }
    const rms = Math.sqrt(energy / this.timeDomain.length);
    const rmsDb = rms > 1e-8 ? 20 * Math.log10(rms) : -100;

    if (rmsDb < this.segmenterConfig.noteOffRmsDb) {
      if (this.quietSince === null) this.quietSince = now;
    } else {
      this.quietSince = null;
    }
    this.onLevel(rmsDb, this.quietSince === null ? 0 : now - this.quietSince);

    const prevCount = this.segmenterState.completed.length;
    const frame: PitchFrame = {
      timeSeconds: now,
      midiExact: clarity >= this.segmenterConfig.confidenceOff ? midiExact : null,
      confidence: clarity,
      rmsDb,
    };
    this.segmenterState = pushFrame(this.segmenterState, frame, this.segmenterConfig);

    if (this.segmenterState.completed.length > prevCount) {
      for (let i = prevCount; i < this.segmenterState.completed.length; i++) {
        const seg = this.segmenterState.completed[i];
        this.onNote(seg);
      }
    }

    this.rafId = requestAnimationFrame(this.tick);
  };

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
    const finalized = finalizeSegments(this.segmenterState, now, this.segmenterConfig);

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
    this.segmenterState = initialSegmenterState();
    this.setStatus("idle");
    return finalized;
  }

  /** Stop recording and return the segmented notes. */
  stop(): NoteSegment[] {
    if (this.status !== "listening") return [];
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

/**
 * The live coaching socket, `coach.v1`.
 *
 * Two rules shape this client:
 *
 * 1. **The client keeps every note.** The socket is a delivery channel, not the
 *    record. If it drops, `finalizeOverHttp` submits the same notes with the
 *    same idempotency key the socket would have used, so a lost connection
 *    costs the learner nothing and cannot produce two attempts.
 * 2. **Audio is best-effort, text is not.** Chunks are buffered and decoded at
 *    the end of an utterance when the browser can, and the spoken text is read
 *    aloud by the OS voice when it cannot. The learner always hears something.
 */

import { readToken } from "@/lib/api";
import type { PerformanceAttempt, PerformedNote } from "@/lib/types";

export const COACH_PROTOCOL_VERSION = "coach.v1";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const NOTE_BATCH_MS = 100;
const MAX_NOTES_PER_FRAME = 32;
const HEARTBEAT_MS = 5000;

function socketUrl(): string {
  const url = new URL("/api/practice/coach", BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export interface CoachCue {
  cue: string | null;
  severity: string;
  cursor: number;
  expected_note_count: number;
  matched_count: number;
  missed_count: number;
  extra_count: number;
  signed_timing_bias_seconds: number | null;
  mean_pitch_error_semitones: number | null;
  signed_pitch_bias_semitones: number | null;
  progress_ratio: number;
  suppressed_by: string | null;
}

export interface CoachUtteranceState {
  id: string;
  cue: string;
  severity: string;
  text: string;
  streaming: boolean;
  cancelled: boolean;
}

export interface CoachExercise {
  id: string;
  title: string;
  instrument: string;
  tempo_bpm: number;
  expected_note_count: number;
}

export interface CoachHandlers {
  onReady?: (exercise: CoachExercise | null) => void;
  onCue?: (cue: CoachCue) => void;
  onUtterance?: (utterance: CoachUtteranceState) => void;
  onResult?: (attempt: PerformanceAttempt) => void;
  onError?: (message: string) => void;
  onClosed?: (code: number) => void;
}

export class CoachSocket {
  private socket: WebSocket | null = null;
  private queue: PerformedNote[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private utterance: CoachUtteranceState | null = null;
  private audioChunks: string[] = [];
  private audioFormat = "wav";
  private clockSeconds = 0;
  private started = 0;
  private ready = false;
  private lastLevelSentAt = 0;

  readonly takeId: string;
  readonly practiceSessionId: string;

  constructor(
    practiceSessionId: string,
    private readonly handlers: CoachHandlers = {},
    takeId: string = crypto.randomUUID(),
  ) {
    this.practiceSessionId = practiceSessionId;
    this.takeId = takeId;
  }

  /** The key both this socket and the HTTP fallback submit under. */
  get idempotencyKey(): string {
    return `coach:${this.takeId}`;
  }

  async connect(): Promise<void> {
    const token = readToken();
    if (token === null) throw new Error("Sign in before starting a coached take.");

    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(socketUrl());
      this.socket = socket;
      socket.onopen = () => {
        socket.send(JSON.stringify({ v: 1, type: "hello", seq: 0, token, protocol_version: COACH_PROTOCOL_VERSION }));
        socket.send(
          JSON.stringify({
            v: 1,
            type: "take.start",
            seq: 1,
            take_id: this.takeId,
            practice_session_id: this.practiceSessionId,
            protocol_version: COACH_PROTOCOL_VERSION,
          }),
        );
        this.started = performance.now();
        resolve();
      };
      socket.onerror = () => reject(new Error("The coaching connection could not be opened."));
      socket.onmessage = (event) => this.receive(event);
      socket.onclose = (event) => {
        this.stopTimers();
        this.handlers.onClosed?.(event.code);
      };
    });

    this.flushTimer = setInterval(() => this.flush(), NOTE_BATCH_MS);
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: "heartbeat", take_clock_seconds: this.clock() });
    }, HEARTBEAT_MS);
  }

  private clock(): number {
    return (performance.now() - this.started) / 1000;
  }

  private send(payload: Record<string, unknown>): void {
    if (this.socket === null || this.socket.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ v: 1, seq: 0, ...payload }));
  }

  /** Queue one detected note. Batched so a fast passage is not one frame per note. */
  pushNote(note: PerformedNote): void {
    this.queue.push(note);
    if (this.queue.length >= MAX_NOTES_PER_FRAME) this.flush();
  }

  /** Report the current level and how long the learner has been quiet (throttled to 10 FPS). */
  pushLevel(rmsDb: number, silenceSeconds: number): void {
    if (!this.ready) return;
    const nowMs = performance.now();
    if (nowMs - this.lastLevelSentAt < 100) return;
    this.lastLevelSentAt = nowMs;

    this.clockSeconds = this.clock();
    this.send({
      type: "frame",
      take_id: this.takeId,
      take_clock_seconds: this.clockSeconds,
      rms_db: rmsDb,
      silence_seconds: silenceSeconds,
    });
  }

  private flush(): void {
    if (!this.ready || this.queue.length === 0) return;
    const notes = this.queue.splice(0, MAX_NOTES_PER_FRAME);
    this.send({
      type: "notes",
      take_id: this.takeId,
      take_clock_seconds: this.clock(),
      notes,
    });
  }

  private receive(event: MessageEvent): void {
    let frame: Record<string, unknown>;
    try {
      frame = JSON.parse(String(event.data));
    } catch {
      return;
    }
    const type = String(frame.type ?? "");

    if (type === "session.ready") {
      this.ready = true;
      this.audioFormat = String(frame.audio_format ?? "wav");
      this.handlers.onReady?.((frame.exercise as CoachExercise | null) ?? null);
    } else if (type === "cue") {
      this.handlers.onCue?.(frame as unknown as CoachCue);
    } else if (type === "coach.begin") {
      this.audioChunks = [];
      this.utterance = {
        id: String(frame.utterance_id),
        cue: String(frame.cue ?? ""),
        severity: String(frame.severity ?? "info"),
        text: "",
        streaming: true,
        cancelled: false,
      };
      this.handlers.onUtterance?.(this.utterance);
    } else if (type === "coach.delta" && this.utterance !== null) {
      this.utterance = { ...this.utterance, text: this.utterance.text + String(frame.text ?? "") };
      this.handlers.onUtterance?.(this.utterance);
    } else if (type === "coach.audio") {
      this.audioChunks.push(String(frame.audio_base64 ?? ""));
    } else if (type === "coach.end" && this.utterance !== null) {
      const spoken = String(frame.spoken_text ?? this.utterance.text);
      this.utterance = { ...this.utterance, text: spoken, streaming: false, cancelled: Boolean(frame.cancelled) };
      this.handlers.onUtterance?.(this.utterance);
      if (!this.utterance.cancelled) void this.play(spoken);
      this.utterance = null;
    } else if (type === "coach.cancel" && this.utterance !== null) {
      this.utterance = { ...this.utterance, streaming: false, cancelled: true };
      this.handlers.onUtterance?.(this.utterance);
      this.utterance = null;
    } else if (type === "take.result") {
      this.handlers.onResult?.(frame.attempt as PerformanceAttempt);
    } else if (type === "error") {
      const detail = String(frame.detail ?? "");
      const errorKind = String(frame.error ?? "");
      if (errorKind !== "no_take" && !detail.toLowerCase().includes("start a take")) {
        this.handlers.onError?.(detail || "The coach hit a problem.");
      }
    }
  }

  /**
   * Play an utterance. The ladder, in order of preference:
   *   1. decode the buffered audio chunks;
   *   2. speak the text with the OS voice.
   * The second is the default in fake mode, needs no key, and works everywhere,
   * which is why the contract always carries the spoken text.
   */
  private async play(text: string): Promise<void> {
    if (this.audioChunks.length > 0) {
      try {
        const bytes = this.audioChunks.flatMap((chunk) => Array.from(atob(chunk), (c) => c.charCodeAt(0)));
        const blob = new Blob([new Uint8Array(bytes)], { type: this.audioFormat === "mp3" ? "audio/mpeg" : "audio/wav" });
        const audio = new Audio(URL.createObjectURL(blob));
        this.audioChunks = [];
        await audio.play();
        return;
      } catch {
        // Fall through to speech synthesis.
      }
    }
    this.audioChunks = [];
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    }
  }

  /** Tell the server the learner started playing again. */
  bargeIn(): void {
    this.send({ type: "barge_in", take_id: this.takeId, utterance_id: this.utterance?.id ?? this.takeId });
  }

  finalize(notes: PerformedNote[], options: { recordingId?: string | null; posture?: unknown; analyzer?: string } = {}): void {
    this.flush();
    this.send({
      type: "take.finalize",
      take_id: this.takeId,
      notes,
      recording_id: options.recordingId ?? null,
      posture: options.posture ?? null,
      analyzer: options.analyzer ?? null,
      duration_seconds: this.clock(),
    });
  }

  abandon(): void {
    this.send({ type: "take.abandon", take_id: this.takeId });
    this.close();
  }

  private stopTimers(): void {
    if (this.flushTimer !== null) clearInterval(this.flushTimer);
    if (this.heartbeatTimer !== null) clearInterval(this.heartbeatTimer);
    this.flushTimer = null;
    this.heartbeatTimer = null;
  }

  close(): void {
    this.stopTimers();
    this.socket?.close();
    this.socket = null;
  }

  get isOpen(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN;
  }
}

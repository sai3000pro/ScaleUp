/**
 * High-performance, zero-latency Web Audio synthesizer and metronome clock.
 *
 * Reuses a single pre-warmed AudioContext singleton to prevent OS audio
 * driver negotiation lag and garbage collection stalls.
 */

let sharedAudioCtx: AudioContext | null = null;

export function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (sharedAudioCtx === null) {
    const AudioCtxCtor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (AudioCtxCtor) {
      sharedAudioCtx = new AudioCtxCtor();
    }
  }
  if (sharedAudioCtx && sharedAudioCtx.state === "suspended") {
    void sharedAudioCtx.resume().catch(() => {});
  }
  return sharedAudioCtx;
}

/** Play a high-precision, zero-latency metronome beep. */
export function playMetronomeClick(isAccent = false): void {
  const ctx = getAudioContext();
  if (ctx === null) return;

  try {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(isAccent ? 1200 : 800, now);

    gain.gain.setValueAtTime(0.3, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.07);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start(now);
    osc.stop(now + 0.07);
  } catch {
    // Audio playback blocked
  }
}

/** Play a synthesized musical tone for a given MIDI pitch with warm harmonics. */
export function playMidiTone(midi: number, durationSeconds = 0.5): void {
  const ctx = getAudioContext();
  if (ctx === null || midi < 0 || midi > 127) return;

  try {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    const frequency = 440 * Math.pow(2, (midi - 69) / 12);
    osc.type = "triangle";
    osc.frequency.setValueAtTime(frequency, now);

    // Smooth ADSR envelope: fast attack, gradual decay
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.linearRampToValueAtTime(0.35, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + durationSeconds);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start(now);
    osc.stop(now + durationSeconds);
  } catch {
    // Audio playback blocked
  }
}

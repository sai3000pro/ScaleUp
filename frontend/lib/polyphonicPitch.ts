/**
 * Resolve the pitches sounding at once in one time-domain window.
 *
 * Harmonic-salience peak picking with iterative spectral subtraction: the
 * spectrum is scored at every candidate fundamental by the weighted magnitude
 * found at its harmonics, the strongest candidate is taken as a voice, the bins
 * it explains are removed, and the search repeats until nothing salient is
 * left. Pure functions only -- no audio device, no ML, no dependencies -- so a
 * chord can be scored from what was played and the detector can be tested with
 * a synthesised signal.
 */

/** MIDI pitch of a frequency, in 12-EDO tuning (A4 = 440 Hz = MIDI 69). */
// @spec CAP-PITCH-008
export function frequencyToMidi(frequency: number): number {
  return 69 + 12 * Math.log2(frequency / 440);
}

export interface VoiceDetection {
  frequency: number;
  /** Fractional MIDI pitch of `frequency`. */
  midiExact: number;
  /** 0..1: how completely the harmonic series is present. */
  clarity: number;
  /** Weighted harmonic magnitude; comparable across the voices of one window. */
  salience: number;
}

export interface PolyphonicConfig {
  minMidi: number;
  maxMidi: number;
  maxVoices: number;
  harmonics: number;
  /** A voice weaker than this fraction of the strongest voice is noise. */
  relativeSalienceFloor: number;
  /** A harmonic weaker than this fraction of the window's peak bin is absent. */
  harmonicPresenceFloor: number;
  /** Half-width of the band searched around each harmonic, as a fraction of its frequency. */
  harmonicTolerance: number;
  /** A fundamental carrying less than this share of its own salience is a coincidence of other notes' harmonics. */
  fundamentalShare: number;
  silenceEnergy: number;
}

export const DEFAULT_POLYPHONIC_CONFIG: PolyphonicConfig = {
  minMidi: 36,
  maxMidi: 96,
  maxVoices: 6,
  harmonics: 6,
  relativeSalienceFloor: 0.3,
  harmonicPresenceFloor: 0.05,
  harmonicTolerance: 0.03,
  fundamentalShare: 0.15,
  silenceEnergy: 1e-8,
};

export const POLYPHONIC_ANALYZER_ID = "harmonic-salience-v1";

/** In-place iterative radix-2 FFT; `real.length` must be a power of two. */
export function fft(real: Float64Array, imag: Float64Array): void {
  const n = real.length;
  for (let i = 1, j = 0; i < n; i += 1) {
    let bit = n >> 1;
    for (; (j & bit) !== 0; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [real[i], real[j]] = [real[j], real[i]];
      [imag[i], imag[j]] = [imag[j], imag[i]];
    }
  }
  for (let length = 2; length <= n; length <<= 1) {
    const angle = (-2 * Math.PI) / length;
    const wReal = Math.cos(angle);
    const wImag = Math.sin(angle);
    for (let start = 0; start < n; start += length) {
      let curReal = 1;
      let curImag = 0;
      for (let k = 0; k < length / 2; k += 1) {
        const a = start + k;
        const b = a + length / 2;
        const tReal = real[b] * curReal - imag[b] * curImag;
        const tImag = real[b] * curImag + imag[b] * curReal;
        real[b] = real[a] - tReal;
        imag[b] = imag[a] - tImag;
        real[a] += tReal;
        imag[a] += tImag;
        const nextReal = curReal * wReal - curImag * wImag;
        curImag = curReal * wImag + curImag * wReal;
        curReal = nextReal;
      }
    }
  }
}

function nextPowerOfTwo(n: number): number {
  let size = 1;
  while (size < n) size <<= 1;
  return size;
}

/** Hann-windowed magnitude spectrum (bins 0..N/2). */
export function magnitudeSpectrum(timeDomain: Float32Array): Float64Array {
  const size = nextPowerOfTwo(timeDomain.length);
  const real = new Float64Array(size);
  const imag = new Float64Array(size);
  const count = timeDomain.length;
  for (let i = 0; i < count; i += 1) {
    const window = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (count - 1));
    real[i] = timeDomain[i] * window;
  }
  fft(real, imag);
  const magnitudes = new Float64Array(size / 2 + 1);
  for (let bin = 0; bin <= size / 2; bin += 1) {
    magnitudes[bin] = Math.hypot(real[bin], imag[bin]);
  }
  return magnitudes;
}

function midiToFrequency(midi: number): number {
  return 440 * 2 ** ((midi - 69) / 12);
}

interface HarmonicPeak {
  bin: number;
  magnitude: number;
}

function peakNear(magnitudes: Float64Array, frequency: number, binHz: number, tolerance: number): HarmonicPeak | null {
  const low = Math.max(1, Math.floor((frequency * (1 - tolerance)) / binHz));
  const high = Math.min(magnitudes.length - 2, Math.ceil((frequency * (1 + tolerance)) / binHz));
  if (low > high) return null;
  let best = low;
  for (let bin = low; bin <= high; bin += 1) {
    if (magnitudes[bin] > magnitudes[best]) best = bin;
  }
  return { bin: best, magnitude: magnitudes[best] };
}

/** Parabolic interpolation on the log spectrum around a peak bin. */
function refinedBin(magnitudes: Float64Array, bin: number): number {
  if (bin <= 0 || bin >= magnitudes.length - 1) return bin;
  const before = Math.log(magnitudes[bin - 1] + 1e-12);
  const centre = Math.log(magnitudes[bin] + 1e-12);
  const after = Math.log(magnitudes[bin + 1] + 1e-12);
  const denominator = before - 2 * centre + after;
  if (Math.abs(denominator) < 1e-9) return bin;
  const offset = (0.5 * (before - after)) / denominator;
  return offset > -1 && offset < 1 ? bin + offset : bin;
}

function salienceAt(
  magnitudes: Float64Array,
  f0: number,
  binHz: number,
  peakMagnitude: number,
  config: PolyphonicConfig,
): { salience: number; present: number; fundamental: HarmonicPeak | null } {
  let salience = 0;
  let present = 0;
  let fundamental: HarmonicPeak | null = null;
  for (let h = 1; h <= config.harmonics; h += 1) {
    const peak = peakNear(magnitudes, f0 * h, binHz, config.harmonicTolerance);
    if (peak !== null) {
      salience += peak.magnitude / Math.sqrt(h);
      if (peak.magnitude >= peakMagnitude * config.harmonicPresenceFloor) present += 1;
      if (h === 1) {
        // A leaked shoulder of a neighbouring note's peak is not a fundamental:
        // it must be a local maximum that refines back onto this candidate.
        const isPeak = peak.magnitude >= magnitudes[peak.bin - 1] && peak.magnitude >= magnitudes[peak.bin + 1];
        const refinedMidi = frequencyToMidi(refinedBin(magnitudes, peak.bin) * binHz);
        fundamental = isPeak && Math.abs(refinedMidi - frequencyToMidi(f0)) <= 0.5 ? peak : null;
      }
    }
  }
  return { salience, present, fundamental };
}

/**
 * Remove a voice's expected spectrum, not its bins: a harmonic rolls off as
 * `1/h` from the fundamental, and only that much is taken, so a second note
 * whose fundamental sits on this voice's harmonic keeps the energy that is its own.
 */
function subtractVoice(magnitudes: Float64Array, f0: number, amplitude: number, binHz: number, config: PolyphonicConfig): void {
  for (let h = 1; h <= config.harmonics * 2; h += 1) {
    const frequency = f0 * h;
    const low = Math.max(1, Math.floor((frequency * (1 - config.harmonicTolerance)) / binHz));
    const high = Math.min(magnitudes.length - 1, Math.ceil((frequency * (1 + config.harmonicTolerance)) / binHz));
    const expected = amplitude / h;
    for (let bin = low; bin <= high; bin += 1) magnitudes[bin] = Math.max(0, magnitudes[bin] - expected);
  }
}

/**
 * Every pitch sounding in the window, strongest first. Empty for silence or
 * for a window with no salient harmonic structure.
 */
// @spec CAP-PITCH-001, CAP-PITCH-002, CAP-PITCH-004, CAP-PITCH-005, CAP-PITCH-006, CAP-PITCH-007
export function detectPitches(
  timeDomain: Float32Array,
  sampleRate: number,
  overrides: Partial<PolyphonicConfig> = {},
): VoiceDetection[] {
  const config = { ...DEFAULT_POLYPHONIC_CONFIG, ...overrides };
  let energy = 0;
  for (let i = 0; i < timeDomain.length; i += 1) energy += timeDomain[i] * timeDomain[i];
  if (energy < config.silenceEnergy) return [];

  const magnitudes = magnitudeSpectrum(timeDomain);
  const binHz = sampleRate / ((magnitudes.length - 1) * 2);
  let peakMagnitude = 0;
  for (let bin = 1; bin < magnitudes.length; bin += 1) peakMagnitude = Math.max(peakMagnitude, magnitudes[bin]);
  if (peakMagnitude <= 0) return [];

  const voices: VoiceDetection[] = [];
  let firstSalience = 0;
  // The fundamental must itself be audible: a candidate an octave below a real
  // note shares every harmonic of that note but has nothing at its own f0.
  const fundamentalFloor = peakMagnitude * config.harmonicPresenceFloor;

  while (voices.length < config.maxVoices) {
    let bestMidi = Number.NaN;
    let best = { salience: 0, present: 0, fundamental: null as HarmonicPeak | null };
    for (let midi = config.minMidi; midi <= config.maxMidi; midi += 1) {
      const scored = salienceAt(magnitudes, midiToFrequency(midi), binHz, peakMagnitude, config);
      const audible = scored.fundamental !== null
        && scored.fundamental.magnitude >= fundamentalFloor
        && scored.fundamental.magnitude >= scored.salience * config.fundamentalShare;
      if (audible && scored.salience > best.salience) {
        best = scored;
        bestMidi = midi;
      }
    }
    const fundamental = best.fundamental;
    const strongEnough = voices.length === 0 || best.salience >= firstSalience * config.relativeSalienceFloor;
    if (Number.isNaN(bestMidi) || fundamental === null || !strongEnough) break;
    if (voices.length === 0) firstSalience = best.salience;

    const frequency = refinedBin(magnitudes, fundamental.bin) * binHz;
    voices.push({
      frequency,
      midiExact: frequencyToMidi(frequency),
      clarity: best.present / config.harmonics,
      salience: best.salience,
    });
    subtractVoice(magnitudes, frequency, fundamental.magnitude, binHz, config);
  }
  return voices;
}

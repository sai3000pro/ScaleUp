import { create } from "zustand";

import { POSTURE_THRESHOLD_VERSION, POSTURE_VERSION } from "@/lib/posture";
import type { TechniqueMetrics } from "@/lib/technique";
import type { PostureObservation } from "@/lib/types";

/**
 * The bridge between the camera panel and the panel that submits a take.
 *
 * Posture is sampled continuously by whichever panel owns the camera, but it is
 * only meaningful as a summary over a whole take -- a single frame at the moment
 * of submission is a snapshot, not a measurement. So samples accumulate here
 * while a take is running, and the submitting panel reads one reduced
 * observation at the end.
 *
 * Only derived metrics ever land in this store. Landmarks stay in the tracking
 * module and video never leaves the page at all.
 */
interface PostureState {
  instrument: string | null;
  samples: TechniqueMetrics[];
  recording: boolean;
  begin: (instrument: string | null) => void;
  sample: (metrics: TechniqueMetrics) => void;
  end: () => void;
  /** Null when nothing usable was captured -- which is not a failure. */
  observation: () => PostureObservation | null;
}

// A take is a couple of minutes at a few samples a second; this bounds memory
// without thinning the summary.
const MAX_SAMPLES = 600;

// @spec OBS-RED-001, OBS-RED-002, OBS-RED-003, OBS-RED-007
export const usePostureStore = create<PostureState>((set, get) => ({
  instrument: null,
  samples: [],
  recording: false,

  begin: (instrument) => set({ instrument, samples: [], recording: true }),

  sample: (metrics) => {
    if (!get().recording) return;
    set((state) => ({ samples: [...state.samples, metrics].slice(-MAX_SAMPLES) }));
  },

  end: () => set({ recording: false }),

  observation: () => {
    const { samples, instrument } = get();
    if (samples.length === 0) return null;

    // One reading per metric key: the median value, the mean confidence, and
    // the worst status seen. Median rather than mean because one frame where
    // the learner reached for a page turn should not become the take's posture.
    const byKey = new Map<string, { values: number[]; confidences: number[]; statuses: string[]; raw: number[]; unit: string | null }>();
    for (const frame of samples) {
      for (const metric of frame.metrics) {
        const entry = byKey.get(metric.key) ?? { values: [], confidences: [], statuses: [], raw: [], unit: null };
        entry.values.push(metric.value);
        entry.confidences.push(metric.confidence);
        entry.statuses.push(metric.status);
        if (typeof metric.raw === "number") entry.raw.push(metric.raw);
        entry.unit = metric.unit ?? entry.unit;
        byKey.set(metric.key, entry);
      }
    }

    const median = (values: number[]): number => {
      const ordered = [...values].sort((left, right) => left - right);
      const middle = Math.floor(ordered.length / 2);
      return ordered.length % 2 === 1 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
    };
    const worst = (statuses: string[]): string => {
      const order = ["not_detected", "low_confidence", "needs_attention", "good"];
      let index = order.length - 1;
      for (const status of statuses) {
        const found = order.indexOf(status);
        if (found >= 0 && found < index) index = found;
      }
      return order[index];
    };

    const metrics = [...byKey.entries()].map(([key, entry]) => ({
      key,
      value: Math.round(median(entry.values) * 100) / 100,
      confidence: Math.round((entry.confidences.reduce((a, b) => a + b, 0) / entry.confidences.length) * 100) / 100,
      status: worst(entry.statuses),
      raw: entry.raw.length > 0 ? Math.round(median(entry.raw) * 1000) / 1000 : null,
      unit: entry.unit,
    }));

    const detectedFrames = samples.filter((frame) => frame.detected).length;
    return {
      version: samples[0]?.version ?? POSTURE_VERSION,
      threshold_version: POSTURE_THRESHOLD_VERSION,
      instrument,
      metrics: metrics.slice(0, 12),
      frame_count: samples.length,
      coverage: Math.round((detectedFrames / samples.length) * 100) / 100,
    };
  },
}));

/**
 * MediaPipe hand-landmark tracker.
 *
 * Loads the model from the standard Google CDN at runtime and feeds landmark
 * frames into the pure technique reducer in `lib/technique.ts`. Raw video is
 * never uploaded anywhere — only the derived metrics leave this module, and
 * only as state in the UI.
 *
 * Every failure mode is graceful: no network, no model, no camera, or a denied
 * permission all surface as a status the panel can render, and audio practice
 * is never affected.
 */

import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";

import { HISTORY_SIZE, reduceTechnique, type Landmark, type TechniqueMetrics } from "@/lib/technique";

// The WASM runtime ships inside the installed npm package; jsDelivr serves the
// matching version so no extra build config is needed.
const VISION_VERSION = "0.10.14";
const WASM_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VISION_VERSION}/wasm`;
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

export type TrackingStatus = "idle" | "loading" | "tracking" | "unavailable";

interface HandTrackerOptions {
  onMetrics: (metrics: TechniqueMetrics) => void;
  onStatus: (status: TrackingStatus) => void;
}

// @spec CAP-CAM-001, CAP-CAM-002, CAP-CAM-003, CAP-CAM-004, CAP-CAM-005, CAP-CAM-006, CAP-CAM-007
export class HandTracker {
  private landmarker: HandLandmarker | null = null;
  private video: HTMLVideoElement | null = null;
  private rafId: number | null = null;
  private lastVideoTime = -1;
  private history: (Landmark[] | null)[] = [];
  private onMetrics: (metrics: TechniqueMetrics) => void;
  private onStatus: (status: TrackingStatus) => void;

  constructor(options: HandTrackerOptions) {
    this.onMetrics = options.onMetrics;
    this.onStatus = options.onStatus;
  }

  async start(video: HTMLVideoElement): Promise<void> {
    this.video = video;
    this.onStatus("loading");
    try {
      const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
      this.landmarker = await HandLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
        runningMode: "VIDEO",
        numHands: 1,
      });
    } catch {
      this.onStatus("unavailable");
      this.stop();
      return;
    }
    this.onStatus("tracking");
    this.rafId = requestAnimationFrame(this.tick);
  }

  private tick = (): void => {
    if (this.landmarker === null || this.video === null) return;
    if (this.video.currentTime !== this.lastVideoTime) {
      this.lastVideoTime = this.video.currentTime;
      const result = this.landmarker.detectForVideo(this.video, performance.now());
      const current: Landmark[] | null = result.landmarks[0] ?? null;
      this.history.push(current);
      if (this.history.length > HISTORY_SIZE) {
        this.history.shift();
      }
      const frames = this.history.filter((frame): frame is Landmark[] => frame !== null);
      this.onMetrics(reduceTechnique(current, frames));
    }
    this.rafId = requestAnimationFrame(this.tick);
  };

  stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.landmarker !== null) {
      this.landmarker.close();
      this.landmarker = null;
    }
    this.video = null;
  }
}

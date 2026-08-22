/**
 * Thin MediaPipe adapter shared by live camera and selected-video analysis.
 * It owns browser/model resources but no technique thresholds or grading.
 */

import {
  FilesetResolver,
  HandLandmarker,
  PoseLandmarker,
} from "@mediapipe/tasks-vision";

import {
  HISTORY_SIZE,
  type Landmark,
} from "@/lib/technique";
import {
  reduceVisualLandmarkFrame,
  type VisualObservationFrame,
} from "@/lib/videoAnalysis";

// Keep the runtime byte-for-byte aligned with the installed JS package. A
// mismatched WASM bundle can compile successfully and fail only when the first
// landmarker is constructed in the browser.
const VISION_VERSION = "1.0.1";
const WASM_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VISION_VERSION}/wasm`;
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const POSE_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task";
const SAMPLE_INTERVAL_MS = 200;

export type VisualTrackingStatus = "idle" | "loading" | "tracking" | "unavailable";

interface VisualTrackerOptions {
  instrument: string;
  onFrame: (frame: VisualObservationFrame) => void;
  onStatus: (status: VisualTrackingStatus) => void;
}

function asLandmarks(input: readonly { x: number; y: number; z: number; visibility?: number }[]): Landmark[] {
  return input.map((landmark) => ({
    x: landmark.x,
    y: landmark.y,
    z: landmark.z,
    visibility: landmark.visibility,
  }));
}

/**
 * The one production adapter for both live and prerecorded visual sources.
 * Media time labels the observation; performance time is supplied to
 * MediaPipe so seeking or replaying a file never sends a decreasing inference
 * timestamp.
 *
 * @spec CAP-CAM-001, CAP-CAM-002, CAP-CAM-003, CAP-CAM-004, CAP-CAM-005, CAP-CAM-006, CAP-CAM-008, CAP-VID-003, CAP-VID-004, CAP-VID-006
 */
export class VisualTracker {
  private handLandmarker: HandLandmarker | null = null;
  private poseLandmarker: PoseLandmarker | null = null;
  private video: HTMLVideoElement | null = null;
  private rafId: number | null = null;
  private lastSampleMediaTimeMs = -1;
  private handHistory: Landmark[][] = [];
  private poseHistory: Landmark[][] = [];
  private readonly instrument: string;
  private readonly onFrame: (frame: VisualObservationFrame) => void;
  private readonly onStatus: (status: VisualTrackingStatus) => void;

  constructor(options: VisualTrackerOptions) {
    this.instrument = options.instrument;
    this.onFrame = options.onFrame;
    this.onStatus = options.onStatus;
  }

  async start(video: HTMLVideoElement): Promise<boolean> {
    this.stop(false);
    this.video = video;
    this.onStatus("loading");
    try {
      const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
      try {
        await this.createModels(fileset, "GPU");
      } catch {
        // GPU delegation is an optimisation, not a product requirement. Some
        // browsers expose WebGL but cannot create both task delegates; retry on
        // CPU before reporting the models unavailable.
        this.releaseModels();
        await this.createModels(fileset);
      }
    } catch {
      this.releaseModels();
      this.video = null;
      this.onStatus("unavailable");
      return false;
    }

    this.onStatus("tracking");
    this.resume(video);
    return true;
  }

  resume(video: HTMLVideoElement = this.video as HTMLVideoElement): void {
    if (this.handLandmarker === null || this.poseLandmarker === null || video === null) return;
    this.video = video;
    if (this.rafId === null) this.rafId = requestAnimationFrame(this.tick);
  }

  pause(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
  }

  stop(reportIdle = true): void {
    this.pause();
    this.releaseModels();
    this.video = null;
    this.lastSampleMediaTimeMs = -1;
    this.handHistory = [];
    this.poseHistory = [];
    if (reportIdle) this.onStatus("idle");
  }

  private releaseModels(): void {
    if (this.handLandmarker !== null) {
      this.handLandmarker.close();
      this.handLandmarker = null;
    }
    if (this.poseLandmarker !== null) {
      this.poseLandmarker.close();
      this.poseLandmarker = null;
    }
  }

  private async createModels(
    fileset: Awaited<ReturnType<typeof FilesetResolver.forVisionTasks>>,
    delegate?: "GPU",
  ): Promise<void> {
    const handBaseOptions = delegate
      ? { modelAssetPath: HAND_MODEL_URL, delegate }
      : { modelAssetPath: HAND_MODEL_URL };
    const poseBaseOptions = delegate
      ? { modelAssetPath: POSE_MODEL_URL, delegate }
      : { modelAssetPath: POSE_MODEL_URL };

    this.handLandmarker = await HandLandmarker.createFromOptions(fileset, {
      baseOptions: handBaseOptions,
      runningMode: "VIDEO",
      numHands: 2,
    });
    this.poseLandmarker = await PoseLandmarker.createFromOptions(fileset, {
      baseOptions: poseBaseOptions,
      runningMode: "VIDEO",
      numPoses: 1,
      outputSegmentationMasks: false,
    });
  }

  private tick = (): void => {
    this.rafId = null;
    const video = this.video;
    if (this.handLandmarker === null || this.poseLandmarker === null || video === null) return;

    const mediaTimeMs = Math.max(0, video.currentTime * 1000);
    const enoughMediaElapsed =
      this.lastSampleMediaTimeMs < 0 ||
      mediaTimeMs < this.lastSampleMediaTimeMs ||
      mediaTimeMs - this.lastSampleMediaTimeMs >= SAMPLE_INTERVAL_MS;

    if (!video.paused && !video.ended && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && enoughMediaElapsed) {
      try {
        const inferenceTimestampMs = performance.now();
        const handResult = this.handLandmarker.detectForVideo(video, inferenceTimestampMs);
        const poseResult = this.poseLandmarker.detectForVideo(video, inferenceTimestampMs);
        const hand = handResult.landmarks[0] ? asLandmarks(handResult.landmarks[0]) : null;
        const pose = poseResult.landmarks[0] ? asLandmarks(poseResult.landmarks[0]) : null;

        if (hand !== null) this.handHistory.push(hand);
        if (pose !== null) this.poseHistory.push(pose);
        this.handHistory = this.handHistory.slice(-HISTORY_SIZE);
        this.poseHistory = this.poseHistory.slice(-HISTORY_SIZE);

        this.onFrame(
          reduceVisualLandmarkFrame({
            instrument: this.instrument,
            timestampMs: mediaTimeMs,
            hand,
            pose,
            handHistory: this.handHistory,
            poseHistory: this.poseHistory,
          }),
        );
        this.lastSampleMediaTimeMs = mediaTimeMs;
      } catch {
        this.pause();
        this.onStatus("unavailable");
        return;
      }
    }

    this.rafId = requestAnimationFrame(this.tick);
  };
}

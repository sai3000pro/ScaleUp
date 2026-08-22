"use client";

import { useEffect, useRef, useState } from "react";

import { usePostureStore } from "@/stores/usePostureStore";

import { HandTracker, type TrackingStatus } from "@/lib/handTracking";
import {
  HISTORY_SIZE,
  mockHandLandmarks,
  reduceTechnique,
  type Landmark,
  type TechniqueMetrics,
} from "@/lib/technique";
import { CARD, FOCUS_RING } from "@/lib/ui";

type CameraStatus = "idle" | "loading" | "active" | "denied";

const STATUS_LABEL: Record<string, string> = {
  idle: "Technique camera is off",
  loading: "Loading hand-tracking model…",
  tracking: "Tracking your hand",
  unavailable: "Hand model unavailable (offline?) — audio practice is unaffected",
  denied: "Camera permission denied — audio practice is unaffected",
};

const METRIC_COLOR: Record<string, string> = {
  good: "text-emerald-300",
  needs_attention: "text-amber-300",
  low_confidence: "text-slate-400",
  not_detected: "text-slate-500",
};

// @spec CAP-CAM-008, CAP-PERM-003, CAP-PERM-004
export function TechniquePanel() {
  const [cameraStatus, setCameraStatus] = useState<CameraStatus>("idle");
  const [trackingStatus, setTrackingStatus] = useState<TrackingStatus>("idle");
  const [metrics, setMetrics] = useState<TechniqueMetrics | null>(null);
  const [mockMode, setMockMode] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const trackerRef = useRef<HandTracker | null>(null);
  const mockIntervalRef = useRef<number | null>(null);
  const mockHistoryRef = useRef<Landmark[][]>([]);

  function stopCamera() {
    if (trackerRef.current !== null) {
      trackerRef.current.stop();
      trackerRef.current = null;
    }
    if (streamRef.current !== null) {
      for (const track of streamRef.current.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
    }
    if (videoRef.current !== null) {
      videoRef.current.srcObject = null;
    }
  }

  useEffect(() => {
    return () => {
      stopCamera();
      if (mockIntervalRef.current !== null) {
        window.clearInterval(mockIntervalRef.current);
        mockIntervalRef.current = null;
      }
    };
  }, []);

  async function enableCamera() {
    setCameraStatus("loading");
    setMockMode(false);
    if (mockIntervalRef.current !== null) {
      window.clearInterval(mockIntervalRef.current);
      mockIntervalRef.current = null;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current !== null) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      const tracker = new HandTracker({ onMetrics: setMetrics, onStatus: setTrackingStatus });
      trackerRef.current = tracker;
      if (videoRef.current !== null) {
        void tracker.start(videoRef.current);
      }
      setCameraStatus("active");
    } catch {
      setCameraStatus("denied");
    }
  }

  function enableMock() {
    stopCamera();
    setCameraStatus("idle");
    setMockMode(true);
    mockHistoryRef.current = [];
    const started = performance.now();
    mockIntervalRef.current = window.setInterval(() => {
      const elapsed = (performance.now() - started) / 1000;
      const variant = Math.floor(elapsed / 6) % 2 === 0 ? "good" : "collapsed";
      const frame = mockHandLandmarks(variant, elapsed);
      mockHistoryRef.current.push(frame);
      if (mockHistoryRef.current.length > HISTORY_SIZE) {
        mockHistoryRef.current.shift();
      }
      const reduced = reduceTechnique(frame, mockHistoryRef.current);
      setMetrics(reduced);
      // Accumulate for the take's posture summary. A single frame at submission
      // time is a snapshot, not a measurement.
      usePostureStore.getState().sample(reduced);
    }, 200);
    setTrackingStatus("tracking");
  }

  const active = cameraStatus === "active" || mockMode;
  const summary = mockMode
    ? "Mock landmarks — a camera-free demo of the metric pipeline"
    : STATUS_LABEL[trackingStatus] ?? STATUS_LABEL.idle;

  return (
    <section className={CARD} aria-labelledby="technique-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="technique-heading" className="font-display text-sm font-semibold">Technique</h2>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
            MediaPipe tracks your hand in the browser. Raw video never leaves the page — only derived
            metrics are shown, and a camera denial never blocks audio practice.
          </p>
        </div>
        <span className="rounded-full border border-violet-900/60 bg-violet-950/20 px-2 py-1 text-[10px] text-violet-300">
          {mockMode ? "MOCK" : cameraStatus === "active" ? "LIVE" : "OFF"}
        </span>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => void enableCamera()}
          disabled={cameraStatus === "loading" || cameraStatus === "active"}
          className={`flex-1 rounded-md border border-violet-800 bg-violet-950/40 px-3 py-2 text-xs font-medium text-violet-200 transition hover:bg-violet-900/50 disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING}`}
        >
          {cameraStatus === "active" ? "Camera on" : "Enable technique camera"}
        </button>
        <button
          type="button"
          onClick={enableMock}
          disabled={mockMode}
          className={`flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-300 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING}`}
        >
          {mockMode ? "Mock running" : "Use mock landmarks"}
        </button>
      </div>

      {cameraStatus === "active" && (
        <video
          ref={videoRef}
          muted
          playsInline
          className="mt-3 h-28 w-full rounded-md border border-slate-800 bg-slate-950 object-cover"
        />
      )}

      <p className="mt-2 text-[11px] text-slate-400">{summary}</p>

      {metrics && metrics.metrics.length > 0 && (
        <ul className="mt-2 space-y-2">
          {metrics.metrics.map((metric) => (
            <li key={metric.key} className="rounded-md border border-slate-800 bg-slate-950/60 p-2 text-[11px]">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium capitalize text-slate-200">{metric.key.replace(/_/g, " ")}</span>
                <span className={METRIC_COLOR[metric.status] ?? "text-slate-400"}>{metric.status.replace(/_/g, " ")}</span>
              </div>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full bg-violet-400/80"
                  style={{ width: `${Math.round(metric.value * 100)}%` }}
                />
              </div>
              <p className="mt-1.5 leading-relaxed text-slate-400">{metric.explanation}</p>
              <p className="mt-0.5 text-[10px] text-slate-500">
                {Math.round(metric.value * 100)}% · confidence {Math.round(metric.confidence * 100)}%
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

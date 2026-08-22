"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { CARD, FOCUS_RING, INPUT } from "@/lib/ui";
import {
  appendVisualFrame,
  isSupportedSelectedVideo,
  summarizeVisualFrames,
  type VisualObservationFrame,
} from "@/lib/videoAnalysis";
import {
  VISUAL_ASSESSMENT_PROFILES,
  assessVisualFrames,
  createVisualAssessmentExport,
} from "@/lib/visualAssessment";
import { VisualTracker } from "@/lib/visualTracking";

type AnalysisStatus =
  | "idle"
  | "ready"
  | "loading-model"
  | "analysing"
  | "paused"
  | "completed"
  | "cancelled"
  | "unsupported"
  | "failed";

const DEFAULT_PROFILE_ID = VISUAL_ASSESSMENT_PROFILES[0].id;

const STATUS_COPY: Record<AnalysisStatus, string> = {
  idle: "Choose an MP4 to begin.",
  ready: "Video ready. Analysis starts only when you press Analyze.",
  "loading-model": "Loading the hand and body models…",
  analysing: "Analysing locally while the video plays.",
  paused: "Analysis paused. Resume when you are ready.",
  completed: "Analysis complete. Review or export the derived observations below.",
  cancelled: "Analysis cancelled. The selected video remains available to restart.",
  unsupported: "This file is not a supported MP4.",
  failed: "Visual analysis could not run. Check network access to the MediaPipe models and try again.",
};

const STATUS_COLOR: Record<string, string> = {
  good: "text-emerald-300",
  needs_attention: "text-amber-300",
  low_confidence: "text-slate-400",
  not_detected: "text-slate-500",
};

const OUTCOME_COPY = {
  pass: "Pass",
  retry: "Retry",
  insufficient_evidence: "Insufficient evidence",
} as const;

const OUTCOME_COLOR = {
  pass: "border-emerald-800 bg-emerald-950/30 text-emerald-300",
  retry: "border-amber-800 bg-amber-950/30 text-amber-300",
  insufficient_evidence: "border-slate-700 bg-slate-900 text-slate-300",
} as const;

function assessmentProfile(profileId: string) {
  const selected = VISUAL_ASSESSMENT_PROFILES.find((profile) => profile.id === profileId);
  if (selected === undefined) throw new Error(`Unknown visual assessment profile: ${profileId}`);
  return selected;
}

function formatTime(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * Local selected-video analysis. The file is bound to a browser object URL;
 * this component makes no API call and imports no audio observation module.
 *
 * @spec CAP-VID-001, CAP-VID-002, CAP-VID-003, CAP-VID-004, CAP-VID-005, CAP-VID-006, CAP-VID-007, OBS-TIME-001, OBS-TIME-003, OBS-TIME-004, OBS-TIME-005, OBS-ASSESS-002, OBS-ASSESS-013
 */
export function VideoAnalysisWorkspace() {
  const [profileId, setProfileId] = useState(DEFAULT_PROFILE_ID);
  const [file, setFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [frames, setFrames] = useState<VisualObservationFrame[]>([]);
  const [latestFrame, setLatestFrame] = useState<VisualObservationFrame | null>(null);
  const [durationMs, setDurationMs] = useState(0);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const trackerRef = useRef<VisualTracker | null>(null);
  const videoUrlRef = useRef<string | null>(null);

  const selectedProfile = useMemo(() => assessmentProfile(profileId), [profileId]);
  const summary = useMemo(() => summarizeVisualFrames(frames), [frames]);
  const assessment = useMemo(() => assessVisualFrames(selectedProfile, frames), [selectedProfile, frames]);
  const progress = durationMs > 0 ? Math.min(100, Math.round((currentTimeMs / durationMs) * 100)) : 0;

  function stopTracker() {
    if (trackerRef.current !== null) {
      trackerRef.current.stop();
      trackerRef.current = null;
    }
  }

  function revokeVideoUrl() {
    if (videoUrlRef.current !== null) {
      URL.revokeObjectURL(videoUrlRef.current);
      videoUrlRef.current = null;
    }
  }

  useEffect(() => {
    return () => {
      stopTracker();
      revokeVideoUrl();
    };
  }, []);

  function selectFile(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    stopTracker();
    revokeVideoUrl();
    setFrames([]);
    setLatestFrame(null);
    setDurationMs(0);
    setCurrentTimeMs(0);

    if (selected === null) {
      setFile(null);
      setVideoUrl(null);
      setStatus("idle");
      return;
    }

    if (!isSupportedSelectedVideo(selected)) {
      setFile(null);
      setVideoUrl(null);
      setStatus("unsupported");
      event.target.value = "";
      return;
    }

    const nextUrl = URL.createObjectURL(selected);
    videoUrlRef.current = nextUrl;
    setFile(selected);
    setVideoUrl(nextUrl);
    setStatus("ready");
  }

  function selectProfile(nextProfileId: string) {
    const nextProfile = assessmentProfile(nextProfileId);
    stopTracker();
    videoRef.current?.pause();
    if (videoRef.current !== null) videoRef.current.currentTime = 0;
    setProfileId(nextProfile.id);
    setFrames([]);
    setLatestFrame(null);
    setCurrentTimeMs(0);
    setStatus(file === null ? "idle" : "ready");
  }

  async function startAnalysis() {
    const video = videoRef.current;
    if (video === null || file === null) return;

    stopTracker();
    if (status === "completed" || video.ended) {
      video.currentTime = 0;
      setFrames([]);
      setLatestFrame(null);
      setCurrentTimeMs(0);
    }

    setStatus("loading-model");
    const tracker = new VisualTracker({
      instrument: selectedProfile.instrument,
      onStatus: (trackingStatus) => {
        if (trackingStatus === "unavailable") setStatus("failed");
      },
      onFrame: (frame) => {
        setFrames((existing) => appendVisualFrame(existing, frame));
        setLatestFrame(frame);
        setCurrentTimeMs(frame.timestampMs);
      },
    });
    trackerRef.current = tracker;
    const started = await tracker.start(video);
    if (!started) return;

    try {
      await video.play();
      setStatus("analysing");
    } catch {
      stopTracker();
      setStatus("failed");
    }
  }

  function pauseAnalysis() {
    videoRef.current?.pause();
    trackerRef.current?.pause();
    setStatus("paused");
  }

  async function resumeAnalysis() {
    const video = videoRef.current;
    if (video === null || trackerRef.current === null) return;
    try {
      await video.play();
      trackerRef.current.resume(video);
      setStatus("analysing");
    } catch {
      setStatus("failed");
    }
  }

  function cancelAnalysis() {
    videoRef.current?.pause();
    stopTracker();
    setStatus("cancelled");
  }

  function completeAnalysis() {
    stopTracker();
    setCurrentTimeMs(durationMs);
    setStatus("completed");
  }

  function exportAnalysis() {
    if (file === null) return;
    const result = createVisualAssessmentExport({
      fileName: file.name,
      durationMs,
      profile: selectedProfile,
      frames,
    });
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${file.name.replace(/\.mp4$/i, "")}-visual-analysis.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const busy = status === "loading-model" || status === "analysing";

  return (
    <main id="main-content" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-8 outline-none">
      <Link href="/courses" className={`text-xs text-slate-400 hover:text-slate-200 ${FOCUS_RING}`}>
        ← Back to courses
      </Link>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Video technique analysis</h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-400">
            Select an MP4 and run hand plus body analysis locally. The video and its audio track are never
            uploaded or scored; only timestamped visual metrics exist outside the player.
          </p>
        </div>
        <span className="w-fit rounded-full border border-violet-900/60 bg-violet-950/30 px-3 py-1 text-[11px] text-violet-300">
          VIDEO ONLY
        </span>
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
        <section className={CARD} aria-labelledby="video-input-heading">
          <h2 id="video-input-heading" className="font-display text-sm font-semibold">1. Choose the visual source</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-slate-300">
              Skill assessment
              <select
                className={`${INPUT} mt-1 w-full`}
                value={profileId}
                disabled={busy}
                onChange={(event) => selectProfile(event.target.value)}
              >
                {VISUAL_ASSESSMENT_PROFILES.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.title} — {profile.instrument}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-[10px] text-slate-500">
                Only this skill&apos;s declared visual requirements affect the final verdict.
              </span>
            </label>
            <label className="text-xs text-slate-300">
              MP4 file
              <input
                type="file"
                accept="video/mp4,.mp4"
                disabled={busy}
                onChange={selectFile}
                className={`mt-1 block w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-violet-900/50 file:px-2 file:py-1 file:text-violet-200 ${FOCUS_RING}`}
              />
            </label>
          </div>

          <div className="mt-3 rounded-lg border border-amber-900/50 bg-amber-950/15 px-3 py-2 text-[11px] leading-relaxed text-amber-200/80">
            <strong className="font-semibold text-amber-300">MVP calibration:</strong> these visual bars are lighter demo defaults,
            not teacher-validated technique standards. The verdict requires {Math.round(selectedProfile.coverageFloor * 100)}% visible evidence,
            {` ${Math.round(selectedProfile.overallPassFloor * 100)}%`} overall, and {Math.round(selectedProfile.requirements[0].passFloor * 100)}% per critical requirement.
          </div>

          {videoUrl !== null && (
            <video
              ref={videoRef}
              src={videoUrl}
              muted
              playsInline
              controls={status !== "analysing"}
              preload="metadata"
              onLoadedMetadata={(event) => setDurationMs(Math.round(event.currentTarget.duration * 1000))}
              onEnded={completeAnalysis}
              onError={() => setStatus("failed")}
              className="mt-4 aspect-video w-full rounded-lg border border-slate-800 bg-black object-contain"
            />
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            {(status === "ready" || status === "cancelled" || status === "completed" || status === "failed") && (
              <button
                type="button"
                onClick={() => void startAnalysis()}
                disabled={file === null}
                className={`rounded-md bg-violet-500 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-400 disabled:opacity-50 ${FOCUS_RING}`}
              >
                {status === "completed" ? "Analyze again" : "Analyze video"}
              </button>
            )}
            {status === "analysing" && (
              <button type="button" onClick={pauseAnalysis} className={`rounded-md border border-slate-700 px-4 py-2 text-xs text-slate-200 ${FOCUS_RING}`}>
                Pause
              </button>
            )}
            {status === "paused" && (
              <button type="button" onClick={() => void resumeAnalysis()} className={`rounded-md bg-violet-500 px-4 py-2 text-xs font-semibold text-white ${FOCUS_RING}`}>
                Resume
              </button>
            )}
            {(status === "analysing" || status === "paused" || status === "loading-model") && (
              <button type="button" onClick={cancelAnalysis} className={`rounded-md border border-slate-700 px-4 py-2 text-xs text-slate-300 ${FOCUS_RING}`}>
                Cancel
              </button>
            )}
            {frames.length > 0 && (
              <button type="button" onClick={exportAnalysis} className={`rounded-md border border-emerald-800 px-4 py-2 text-xs text-emerald-300 ${FOCUS_RING}`}>
                Export visual JSON
              </button>
            )}
          </div>

          <div className="mt-4" aria-live="polite">
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span>{STATUS_COPY[status]}</span>
              <span>{formatTime(currentTimeMs)} / {formatTime(durationMs)}</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full rounded-full bg-violet-400 transition-[width]" style={{ width: `${progress}%` }} />
            </div>
          </div>
        </section>

        <aside className="space-y-5">
          <section className={CARD} aria-labelledby="live-feedback-heading">
            <h2 id="live-feedback-heading" className="font-display text-sm font-semibold">2. Current visual feedback</h2>
            {latestFrame === null ? (
              <p className="mt-3 text-xs leading-relaxed text-slate-400">Feedback will appear as timestamped frames are analysed.</p>
            ) : (
              <>
                <p className="mt-1 text-[11px] text-slate-500">At {formatTime(latestFrame.timestampMs)}</p>
                <ul className="mt-3 space-y-2">
                  {latestFrame.metrics.map((metric) => (
                    <li key={metric.key} className="rounded-md border border-slate-800 bg-slate-950/70 p-2.5 text-[11px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium capitalize text-slate-200">{metric.key.replace(/_/g, " ")}</span>
                        <span className={STATUS_COLOR[metric.status]}>{metric.status.replace(/_/g, " ")}</span>
                      </div>
                      <p className="mt-1 leading-relaxed text-slate-400">{metric.explanation}</p>
                      <p className="mt-1 text-[10px] text-slate-500">confidence {Math.round(metric.confidence * 100)}%</p>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <section className={CARD} aria-labelledby="summary-heading" aria-live="polite">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 id="summary-heading" className="font-display text-sm font-semibold">3. Final skill verdict</h2>
                <p className="mt-1 text-[11px] capitalize text-slate-500">
                  {selectedProfile.title} · {selectedProfile.instrument}
                </p>
              </div>
              {status === "completed" && (
                <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${OUTCOME_COLOR[assessment.outcome]}`}>
                  {OUTCOME_COPY[assessment.outcome]}
                </span>
              )}
            </div>
            <p className="mt-1 text-[11px] text-slate-500">
              {summary.frameCount} sampled frames · {summary.measuredFrameCount} with countable visual evidence
            </p>
            {status !== "completed" ? (
              <p className="mt-3 text-xs leading-relaxed text-slate-400">
                Play the complete video to produce a take-level verdict.
              </p>
            ) : assessment.outcome === "insufficient_evidence" ? (
              <p className="mt-3 text-xs leading-relaxed text-slate-400">
                The camera did not provide enough trustworthy evidence for every required metric. Reframe the player and instrument, then retry.
              </p>
            ) : (
              <p className="mt-3 text-xs leading-relaxed text-slate-400">
                {assessment.outcome === "pass"
                  ? "The full-window aggregate met the overall bar and every critical requirement."
                  : "The video was measurable, but the aggregate or a critical requirement remained below its bar."}
              </p>
            )}
            {status === "completed" && (
              <>
                <dl className="mt-4 grid grid-cols-2 gap-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs">
                  <div>
                    <dt className="text-[10px] uppercase tracking-wide text-slate-500">Overall score</dt>
                    <dd className="mt-1 font-semibold text-slate-200">
                      {assessment.overallScore === null ? "Not graded" : `${Math.round(assessment.overallScore * 100)}%`}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] uppercase tracking-wide text-slate-500">Evidence coverage</dt>
                    <dd className="mt-1 font-semibold text-slate-200">{Math.round(assessment.evidenceCoverage * 100)}%</dd>
                  </div>
                </dl>
                <ul className="mt-3 space-y-2">
                  {assessment.requirements.map((requirement) => (
                    <li key={requirement.metricKey} className="rounded-md border border-slate-800 bg-slate-950/70 p-2.5 text-[11px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-200">
                          {requirement.label}{requirement.critical ? " · critical" : ""}
                        </span>
                        <span className={
                          requirement.passState === "pass"
                            ? "text-emerald-300"
                            : requirement.passState === "retry"
                              ? "text-amber-300"
                              : "text-slate-400"
                        }>
                          {requirement.passState === "insufficient_evidence"
                            ? "not measured"
                            : `${Math.round((requirement.score as number) * 100)}%`}
                        </span>
                      </div>
                      <p className="mt-1 text-[10px] text-slate-500">
                        {Math.round(requirement.coverage * 100)}% coverage
                        {requirement.goodFrameRatio === null ? "" : ` · ${Math.round(requirement.goodFrameRatio * 100)}% good frames`}
                        {` · ${requirement.corrections.length} correction period${requirement.corrections.length === 1 ? "" : "s"}`}
                      </p>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </aside>
      </div>

      <section className={`${CARD} mt-5`} aria-labelledby="timeline-heading">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2 id="timeline-heading" className="font-display text-sm font-semibold">Technique timeline</h2>
            <p className="mt-1 text-[11px] text-slate-500">Adjacent frames with the same correction are grouped into one event.</p>
          </div>
          <span className="text-[11px] text-slate-500">{summary.highlights.length} corrections</span>
        </div>
        {summary.highlights.length === 0 ? (
          <p className="mt-4 text-xs text-slate-400">No countable corrections have been observed.</p>
        ) : (
          <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {summary.highlights.map((highlight, index) => (
              <li key={`${highlight.key}-${highlight.startMs}-${index}`} className="rounded-lg border border-amber-900/50 bg-amber-950/10 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                  {formatTime(highlight.startMs)}{highlight.endMs > highlight.startMs ? `–${formatTime(highlight.endMs)}` : ""}
                </p>
                <p className="mt-1 text-xs font-medium capitalize text-slate-200">{highlight.key.replace(/_/g, " ")}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{highlight.explanation}</p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  );
}

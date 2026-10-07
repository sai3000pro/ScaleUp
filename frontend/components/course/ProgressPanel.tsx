"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { ProgressAnalytics } from "@/lib/types";
import { CARD, MUTED } from "@/lib/ui";

function shortDate(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export function ProgressPanel({
  courseId,
  refreshKey,
  onProgressLoaded,
}: {
  courseId: string;
  refreshKey: number;
  onProgressLoaded?: (progress: ProgressAnalytics) => void;
}) {
  const [progress, setProgress] = useState<ProgressAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setError(null);
    void api
      .getCourseProgress(courseId)
      .then((result) => {
        if (active) {
          setProgress(result);
          onProgressLoaded?.(result);
        }
      })
      .catch((caught) => {
        if (active) setError((caught as Error).message);
      });
    return () => {
      active = false;
    };
  }, [courseId, onProgressLoaded, refreshKey]);

  return (
    <section className={CARD} aria-labelledby="progress-heading">
      <h2 id="progress-heading" className="font-display text-sm font-semibold">
        Progress
      </h2>
      {error && (
        <p role="alert" className="mt-2 text-xs text-rose-400">
          {error}
        </p>
      )}
      {!progress && !error && (
        <p className={`mt-2 text-xs ${MUTED}`}>Loading your progress…</p>
      )}

      {progress && (
        <>
          {/* No mastered count here: the Guided path beside this panel already
              reports completed / total, and the same figure in two panels reads
              as two measurements. @spec UI-PAGE-007 */}
          <dl className="mt-3 grid grid-cols-2 gap-2 text-mini">
            <div>
              <dt className={`${MUTED}`}>Skills learned</dt>
              <dd className="text-slate-200">
                {progress.started_skills} / {progress.total_skills}
              </dd>
            </div>
            <div>
              <dt className={`${MUTED}`}>EXP earned</dt>
              <dd className="text-slate-200">
                {progress.exp_earned.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt className={`${MUTED}`}>Average score</dt>
              <dd className="text-slate-200">
                {progress.average_score === null
                  ? "—"
                  : `${Math.round(progress.average_score * 100)}%`}
              </dd>
            </div>
          </dl>

          <p className={`mt-3 text-mini ${MUTED}`}>
            Review consistency:{" "}
            <span className="text-slate-200">
              {Math.round(progress.consistency * 100)}%
            </span>
            <span>
              {" "}
              · {progress.review_days} review day
              {progress.review_days === 1 ? "" : "s"}
            </span>
            {progress.tracked_days > 0 && (
              <span>
                {" "}
                across {progress.tracked_days} day
                {progress.tracked_days === 1 ? "" : "s"}
              </span>
            )}
          </p>

          {progress.mastery_trend.length > 0 && (
            <div className="mt-4">
              <p className={`text-mini ${MUTED}`}>Mastery trend</p>
              <div
                className="mt-2 flex h-20 items-end gap-1"
                aria-label="Mastery trend chart"
              >
                {progress.mastery_trend.slice(-14).map((point) => (
                  <div
                    key={point.date}
                    className="group flex h-full flex-1 flex-col justify-end"
                  >
                    <div
                      className="min-h-1 rounded-t-sm bg-sky-400/80 transition group-hover:bg-sky-300"
                      style={{ height: `${Math.max(4, point.mastery * 100)}%` }}
                      title={`${shortDate(point.date)}: ${Math.round(point.mastery * 100)}% mastery`}
                    />
                    <span className="mt-1 truncate text-center text-micro text-slate-500">
                      {shortDate(point.date)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {progress.source_coverage.length > 0 && (
            <div className="mt-4">
              <p className={`text-mini ${MUTED}`}>Source coverage</p>
              <ul className="mt-2 space-y-1.5">
                {progress.source_coverage.map((source) => (
                  <li key={source.document_id} className="text-mini">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-slate-300">
                        {source.filename}
                      </span>
                      <span className={`shrink-0 ${MUTED}`}>
                        {source.attempts} attempt
                        {source.attempts === 1 ? "" : "s"}
                      </span>
                    </div>
                    <p className="text-slate-500">
                      {source.skills_started} / {source.skills_total} skills
                      practiced
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {progress.total_attempts === 0 && (
            <p className={`mt-3 text-mini ${MUTED}`}>
              Complete your first drill to start building this history.
            </p>
          )}
        </>
      )}
    </section>
  );
}

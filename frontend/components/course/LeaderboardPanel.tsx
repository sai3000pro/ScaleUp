"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { CARD } from "@/lib/ui";
import type { CourseLeaderboard } from "@/lib/types";

/**
 * The cohort scoreboard. A cohort is the original course plus every copy made
 * from its share link, so this panel is the social face of sharing: the more
 * learners race the same tree, the more this means.
 *
 * Refetched whenever `refreshKey` changes (the course page bumps it after
 * every grade), because the caller's own rank moves with their EXP.
 */
export function LeaderboardPanel({ courseId, refreshKey }: { courseId: string; refreshKey: number }) {
  const [board, setBoard] = useState<CourseLeaderboard | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    api
      .getLeaderboard(courseId)
      .then((result) => {
        if (!cancelled) setBoard(result);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, refreshKey]);

  if (failed) return null; // A dead leaderboard must never take the page down.

  const entries = board?.entries ?? [];
  if (entries.length <= 1) {
    return (
      <div className={CARD}>
        <h2 className="font-display text-sm font-semibold">Cohort leaderboard</h2>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
          No cohort yet — you are the only learner on this tree. Share the
          course link and anyone who copies it joins your leaderboard.
        </p>
      </div>
    );
  }

  return (
    <div className={CARD}>
      <h2 className="font-display text-sm font-semibold">Cohort leaderboard</h2>
      <p className="mt-1 text-[11px] text-slate-400">
        {board?.cohort_size} learners on this tree · you are #{board?.my_rank}
      </p>
      <ol className="mt-3 space-y-1.5">
        {entries.map((entry, index) => (
          <li
            // Display names are intentionally not unique identifiers; two
            // learners may choose the same name, so rank is the stable key in
            // this sorted, one-row-per-course list.
            key={`${entry.display_name}-${index}`}
            className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-[11px] ${
              entry.me ? "bg-sky-950/40 ring-1 ring-sky-800/60" : ""
            }`}
          >
            <span className="w-5 shrink-0 text-right text-slate-500">{index + 1}</span>
            <span className={`min-w-0 flex-1 truncate ${entry.me ? "font-semibold text-sky-200" : "text-slate-300"}`}>
              {entry.display_name}
              {entry.me && <span className="ml-1 text-sky-400">(you)</span>}
            </span>
            <span className="shrink-0 tabular-nums text-slate-400">Lv {entry.level}</span>
            <span className="shrink-0 tabular-nums text-amber-300">{entry.total_exp} EXP</span>
            <span className="hidden w-16 shrink-0 text-right text-slate-500 sm:block">
              {entry.mastered_count}/{entry.started_count} mastered
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

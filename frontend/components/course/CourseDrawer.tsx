"use client";

/**
 * Everything about a course that is not what you came here to do.
 *
 * The course page had thirteen panels stacked in one column, and the column was
 * what made the page four screens tall. Most of them are not per-visit: you
 * build the tree once, upload sources once, share once, and look at the
 * leaderboard when you feel like it. Only three answer the question a learner
 * has while looking at the tree.
 *
 * So the rest live here, behind one control, and the page is one viewport again.
 * Nothing was deleted -- a panel that was scrolled past nine others is not more
 * discoverable than a panel behind a button labelled with what it holds.
 *
 * It is a <dialog>-shaped slide-over rather than a route, because everything in
 * it acts on the course you are already looking at: sending the learner
 * somewhere else and back would lose the tree's camera and their selection.
 *
 * @spec UI-PAGE-004, UI-PAGE-005
 */
import { useEffect, useRef } from "react";

import { CampaignBriefing } from "@/components/course/CampaignBriefing";
import { CurriculumPlanner } from "@/components/course/CurriculumPlanner";
import { LeaderboardPanel } from "@/components/course/LeaderboardPanel";
import { SharePanel } from "@/components/course/SharePanel";
import { AskPanel } from "@/components/explore/AskPanel";
import type { CourseDetail, CoursePath, ProgressAnalytics } from "@/lib/types";
import { FOCUS_RING } from "@/lib/ui";

export interface CourseDrawerProps {
  open: boolean;
  onClose: () => void;
  courseId: string;
  course: CourseDetail | null;
  campaignGoal: string;
  campaignPath: CoursePath | null;
  campaignProgress: ProgressAnalytics | null;
  refreshKey: number;
  onRefresh: () => void;
}

export function CourseDrawer({
  open,
  onClose,
  courseId,
  course,
  campaignGoal,
  campaignPath,
  campaignProgress,
  refreshKey,
  onRefresh,
}: CourseDrawerProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Escape closes it, and focus moves in when it opens. Both are what a reader
  // expects of anything that covers the page, and neither is free on a <div>.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* The scrim closes on click but is not the only way out -- Escape and the
          button both work, because a scrim is invisible to a keyboard. */}
      <button
        type="button"
        aria-label="Close course settings"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-slate-50/20 backdrop-blur-[2px]"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Course settings and sources"
        tabIndex={-1}
        className="relative flex h-full w-full max-w-md flex-col border-l border-slate-700 bg-slate-950 shadow-2xl outline-none"
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
          <h2 className="font-display text-sm font-semibold text-slate-100">Course</h2>
          <button
            type="button"
            onClick={onClose}
            className={`rounded-md px-2 py-1 text-xs text-slate-400 hover:text-slate-200 ${FOCUS_RING}`}
          >
            Close
          </button>
        </div>

        {/* The drawer scrolls, not the page behind it. */}
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          <CampaignBriefing
            courseId={courseId}
            refreshKey={refreshKey}
            path={campaignPath}
            progress={campaignProgress}
            isBuilding={course?.status === "ingesting"}
          />
          <CurriculumPlanner courseId={courseId} initialGoal={campaignGoal} onComplete={onRefresh} />
          <AskPanel courseId={courseId} documents={course?.documents ?? []} />
          <SharePanel courseId={courseId} shareable={course?.status === "ready"} />
          <LeaderboardPanel courseId={courseId} refreshKey={refreshKey} />
        </div>
      </div>
    </div>
  );
}

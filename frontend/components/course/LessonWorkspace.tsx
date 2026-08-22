"use client";

/**
 * The three ways to play a lesson, in the one place a lesson is played.
 *
 * Recording a take, being coached live, and watching your hands are three views
 * of one activity, and all three used to sit in the sidebar beside the tree --
 * which meant the practice panel existed twice over once lessons moved into the
 * realm, and meant a learner mid-take was looking at the wrong half of the
 * screen. They are here now, on the lesson, where the take actually happens.
 *
 * Tabs rather than a stack: the three are alternatives, not steps. Stacking them
 * would put the camera below the fold of an overlay that is already scrolling,
 * and would suggest an order that does not exist.
 *
 * Practice is the default because it is the one that works with nothing but a
 * microphone, and the deterministic path is the floor everywhere else in this
 * system too.
 *
 * @spec PROG-REALM-006, UI-PAGE-003
 */
import { useState } from "react";

import { LiveCoachPanel } from "@/components/course/LiveCoachPanel";
import { PracticePanel } from "@/components/course/PracticePanel";
import { TechniquePanel } from "@/components/course/TechniquePanel";
import { FOCUS_RING } from "@/lib/ui";

const VIEWS = [
  { key: "practice", label: "Practice", hint: "Record a take and be graded on it" },
  { key: "live", label: "Live coach", hint: "Be coached while you play" },
  { key: "technique", label: "Camera", hint: "Watch your hands and posture" },
] as const;

type View = (typeof VIEWS)[number]["key"];

export interface LessonWorkspaceProps {
  courseId: string;
  /** The lesson being played. Practice is pinned to this exercise. */
  exerciseId: string;
  refreshKey: number;
  onCompleted: () => void;
}

export function LessonWorkspace({ courseId, exerciseId, refreshKey, onCompleted }: LessonWorkspaceProps) {
  const [view, setView] = useState<View>("practice");

  return (
    <div className="space-y-3">
      <div role="tablist" aria-label="How to play this lesson" className="flex gap-1 rounded-lg border border-slate-800 bg-slate-900/60 p-1">
        {VIEWS.map((option) => (
          <button
            key={option.key}
            type="button"
            role="tab"
            id={`lesson-tab-${option.key}`}
            aria-selected={view === option.key}
            aria-controls={`lesson-view-${option.key}`}
            title={option.hint}
            onClick={() => setView(option.key)}
            className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold transition ${FOCUS_RING} ${
              view === option.key
                ? "bg-sky-500 text-slate-950"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* Only the selected view is mounted. The camera holds a getUserMedia
          stream and the live coach holds a socket, and keeping either alive
          behind a hidden tab would leave a light on and a connection open for a
          learner who is doing neither. */}
      <div
        role="tabpanel"
        id={`lesson-view-${view}`}
        aria-labelledby={`lesson-tab-${view}`}
        tabIndex={0}
        className={FOCUS_RING}
      >
        {view === "practice" && (
          <PracticePanel
            courseId={courseId}
            refreshKey={refreshKey}
            exerciseId={exerciseId}
            pinned
            onCompleted={onCompleted}
          />
        )}
        {view === "live" && (
          <LiveCoachPanel courseId={courseId} refreshKey={refreshKey} onCompleted={onCompleted} />
        )}
        {view === "technique" && <TechniquePanel />}
      </div>
    </div>
  );
}

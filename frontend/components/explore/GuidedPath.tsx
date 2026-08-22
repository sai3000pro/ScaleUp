"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { stateStyle } from "@/lib/nodeState";
import type { CoursePath, PathStep } from "@/lib/types";
import { BUTTON_SECONDARY, CARD, FOCUS_RING } from "@/lib/ui";
import { useGraphStore } from "@/stores/useGraphStore";

/**
 * Start here → next.
 *
 * The dependency order has been computed on every ingest since the first
 * version and thrown away after layout. This renders it. The one thing a
 * learner opening a 79-node tree needs and cannot get from the picture is
 * "which of these am I supposed to do first", and every orb in the top rank
 * looks equally like an answer.
 *
 * The route does not reorder as you progress -- see `path_service` -- so the
 * list is stable between visits and the only thing that moves is the cursor.
 */
interface Props {
  courseId: string;
  /** Bumped by the page after a grade, so the cursor advances without a reload. */
  refreshKey: number;
  /** Lets the course briefing reuse this already-loaded path response. */
  onPathLoaded?: (path: CoursePath) => void;
}

const PREVIEW = 4;

export function GuidedPath({ courseId, refreshKey, onPathLoaded }: Props) {
  const focusNode = useGraphStore((state) => state.focusNode);
  const [path, setPath] = useState<CoursePath | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .getCoursePath(courseId)
      .then((found) => {
        if (live) {
          setPath(found);
          onPathLoaded?.(found);
          setError(null);
        }
      })
      .catch(() => {
        if (live) setError("Could not load the path.");
      });
    return () => {
      live = false;
    };
  }, [courseId, onPathLoaded, refreshKey]);

  const go = useCallback((nodeId: string) => focusNode(nodeId), [focusNode]);

  if (error) return <p className={`${CARD} text-xs text-rose-400`}>{error}</p>;
  if (!path || path.total === 0) return null;

  const next = path.steps.find((step) => step.node_id === path.next_node_id) ?? null;
  const upcoming = next ? path.steps.filter((step) => !step.done && step.order > next.order) : [];
  const shown = expanded ? upcoming : upcoming.slice(0, PREVIEW);

  return (
    <div className={CARD}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-display text-sm font-semibold">Guided path</h2>
        <span className="text-[11px] text-slate-400">
          {path.completed} / {path.total}
        </span>
      </div>

      {next ? (
        <>
          <p className="mt-0.5 text-[11px] text-slate-400">
            {path.completed === 0 ? "Start here." : "Next up."}
          </p>
          <StepButton step={next} onGo={go} primary />

          {shown.length > 0 && (
            <>
              <h3 className="mt-3 text-[11px] font-semibold text-slate-400">Then</h3>
              <ol className="mt-1 space-y-1">
                {shown.map((step) => (
                  <li key={step.node_id}>
                    <StepButton step={step} onGo={go} />
                  </li>
                ))}
              </ol>
              {upcoming.length > PREVIEW && (
                <button
                  type="button"
                  onClick={() => setExpanded((open) => !open)}
                  className={`mt-2 rounded-sm text-[11px] text-slate-400 underline underline-offset-2 hover:text-slate-200 ${FOCUS_RING}`}
                >
                  {expanded ? "Show fewer" : `Show all ${upcoming.length} remaining`}
                </button>
              )}
            </>
          )}
        </>
      ) : (
        <p className="mt-2 text-xs text-slate-300">
          Every skill on this path is above the mastery threshold. Keep them there — the Daily Quest
          board is where decay shows up.
        </p>
      )}
    </div>
  );
}

function StepButton({ step, onGo, primary = false }: { step: PathStep; onGo: (id: string) => void; primary?: boolean }) {
  const style = stateStyle(step.state);
  return (
    <button
      type="button"
      onClick={() => onGo(step.node_id)}
      className={
        primary
          ? `${BUTTON_SECONDARY} mt-1.5 flex w-full items-start gap-2 text-left`
          : `flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-slate-800/60 ${FOCUS_RING}`
      }
    >
      <span
        aria-hidden
        className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: style.accent }}
      />
      <span className="min-w-0">
        <span className="block truncate text-xs font-semibold text-slate-100">{step.title}</span>
        <span className="block truncate text-[10px] text-slate-400">
          {style.label} · step {step.order + 1}
        </span>
      </span>
    </button>
  );
}

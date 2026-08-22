"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { learnerCourses, prebuiltCourses } from "@/lib/courses";
import type { Course, CourseStatus, KnownCourseStatus } from "@/lib/types";
import { BUTTON_PRIMARY, CARD, FOCUS_RING, INPUT } from "@/lib/ui";

const STATUS_STYLE: Record<KnownCourseStatus, string> = {
  draft: "bg-slate-800 text-slate-400",
  ingesting: "bg-sky-500/15 text-sky-300",
  ready: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-rose-500/15 text-rose-300",
};

// `status` is a bare `str` over the wire. Indexing the table directly put the
// literal text "undefined" into the className for any status added after this
// build, which renders an unstyled, invisible badge.
function statusStyle(status: CourseStatus): string {
  return STATUS_STYLE[status as KnownCourseStatus] ?? "bg-slate-800 text-slate-400";
}

// The learner's own trees are what they came for; the ready-made ones are a way
// in for someone who has not chosen yet. Everything the seed writes for
// development purposes is on neither and is never shown.
const SHELVES = [
  { key: "mine", label: "Your courses" },
  { key: "prebuilt", label: "Prebuilt courses" },
] as const;

// @spec CURR-SHELF-002, CURR-SHELF-003
export default function CoursesPage() {
  const router = useRouter();
  const [courses, setCourses] = useState<Course[]>([]);
  const [title, setTitle] = useState("");
  const [campaignGoal, setCampaignGoal] = useState("");
  const [startingCampaign, setStartingCampaign] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [shelf, setShelf] = useState<"mine" | "prebuilt">("mine");

  const refresh = useCallback(async () => {
    try {
      setCourses((await api.listCourses()).courses);
      // Clear on success: without this a single network blip pins a red banner
      // under the header for the rest of the session.
      setError(null);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const mine = learnerCourses(courses);
  const prebuilt = prebuiltCourses(courses);
  const shown = shelf === "mine" ? mine : prebuilt;

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    try {
      await api.createCourse(title.trim());
      setTitle("");
      await refresh();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  // @spec CURR-GOAL-001, CURR-GOAL-003, CURR-GOAL-005
  async function startCampaign(event: React.FormEvent) {
    event.preventDefault();
    const goal = campaignGoal.trim();
    if (!goal || startingCampaign) return;

    setStartingCampaign(true);
    setError(null);
    try {
      const course = await api.createCourseFromGoal(goal);
      router.push(`/courses/${course.id}`);
    } catch (caught) {
      setError((caught as Error).message);
      setStartingCampaign(false);
    }
  }

  return (
    <main id="main-content" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-8 outline-none">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold tracking-tight">Your courses</h1>
          <p className="mt-1 text-sm text-slate-400">
            Each campaign is an RPG skill tree: learn skills, unlock prerequisites, earn EXP, and defeat decay with quests.
          </p>
        </div>
        <form onSubmit={create} className="flex gap-2">
          <label htmlFor="newCourse" className="sr-only">
            Empty skill tree title
          </label>
          <input
            id="newCourse"
            className={`${INPUT} sm:w-56`}
            placeholder="Empty skill tree title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <button type="submit" className={`${BUTTON_PRIMARY} shrink-0`}>
            Create empty
          </button>
        </form>
      </div>

      <section className={`${CARD} mt-6 border-sky-900/60 bg-sky-950/10`} aria-labelledby="start-campaign-heading">
        <div>
          <h2 id="start-campaign-heading" className="font-display text-sm font-semibold text-sky-100">
            Start a skill campaign
          </h2>
          <p className="mt-1 max-w-2xl text-xs text-slate-400">
            Name the instrument you want to learn and we will build your skill tree now — shared skills
            like reading, pulse and phrasing come from the same catalogue every instrument draws on, so
            what you learn here counts everywhere.
          </p>
        </div>
        <form onSubmit={startCampaign} className="mt-4 flex flex-col gap-2 sm:flex-row">
          <label htmlFor="campaignGoal" className="sr-only">
            Campaign learning goal
          </label>
          <input
            id="campaignGoal"
            className={`${INPUT} min-w-0 flex-1`}
            placeholder="I want to learn how to play guitar"
            value={campaignGoal}
            onChange={(event) => setCampaignGoal(event.target.value)}
            maxLength={500}
            disabled={startingCampaign}
          />
          <button type="submit" disabled={startingCampaign || !campaignGoal.trim()} className={`${BUTTON_PRIMARY} shrink-0`}>
            {startingCampaign ? "Opening campaign…" : "Begin campaign"}
          </button>
        </form>
      </section>

      {error && (
        <p role="alert" className="mt-4 text-sm text-rose-400">
          {error}
        </p>
      )}

      <div className="mt-8 flex items-center gap-1 border-b border-slate-800" role="tablist" aria-label="Which courses to show">
        {SHELVES.map((option) => (
          <button
            key={option.key}
            type="button"
            role="tab"
            aria-selected={shelf === option.key}
            onClick={() => setShelf(option.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${FOCUS_RING} ${
              shelf === option.key
                ? "border-sky-400 text-slate-100"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {option.label}
            <span className="ml-2 text-[11px] text-slate-500 tabular-nums">
              {option.key === "mine" ? mine.length : prebuilt.length}
            </span>
          </button>
        ))}
      </div>

      {loading ? (
        <p className="mt-8 text-sm text-slate-400">Loading…</p>
      ) : shown.length === 0 ? (
        <div className="mt-6 rounded-xl border border-dashed border-slate-800 p-10 text-center">
          <p className="text-sm text-slate-300">
            {shelf === "mine" ? "No courses yet." : "Nothing prebuilt is available."}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {shelf === "mine"
              ? "Name an instrument above and your skill tree is built now — or open a prebuilt course to start straight away."
              : "Run the seed to load the ready-made guitar and piano trees."}
          </p>
        </div>
      ) : (
        <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((course) => (
            <li key={course.id}>
              <Link
                href={`/courses/${course.id}`}
                className={`block ${CARD} transition hover:border-slate-700 hover:bg-slate-900 ${FOCUS_RING}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-display text-sm font-semibold">{course.title}</h2>
                  <span
                    className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium ${statusStyle(course.status)}`}
                  >
                    {course.status}
                  </span>
                </div>
                {course.description && (
                  <p className="mt-1 line-clamp-2 text-xs text-slate-400">{course.description}</p>
                )}
                <p className="mt-3 text-[11px] text-slate-400">
                  {course.node_count} skills · {course.edge_count} links · {course.mastered_count} mastered
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

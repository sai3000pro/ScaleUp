"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ProgressPanel } from "@/components/course/ProgressPanel";
import { CourseDrawer } from "@/components/course/CourseDrawer";
import { LessonWorkspace } from "@/components/course/LessonWorkspace";
import { DrillPanel } from "@/components/drill/DrillPanel";
import { GuidedPath } from "@/components/explore/GuidedPath";
import { SkillGraph3D } from "@/components/skill-tree/SkillGraph3D";
import { SkillRealm3D } from "@/components/skill-tree/SkillRealm3D";
import { SkillTreeOutline } from "@/components/skill-tree/SkillTreeOutline";
import { api } from "@/lib/api";
import {
  STATE_STYLES,
  STRUCTURAL_STYLE,
  difficultyLabel,
  stateStyle,
  type StateStyle,
} from "@/lib/nodeState";
import { dueLabel } from "@/lib/time";
import type {
  CourseDetail,
  CoursePath,
  KnownNodeState,
  ProgressAnalytics,
  SkillRealm,
} from "@/lib/types";
import { BUTTON_SECONDARY, CARD, FOCUS_RING } from "@/lib/ui";
import { canOpenLesson } from "@/lib/lesson";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { useGraphStore } from "@/stores/useGraphStore";

const LEGEND: { key: string; style: StateStyle }[] = [
  ...(
    [
      "available",
      "learning",
      "decaying",
      "mastered",
      "locked",
    ] as KnownNodeState[]
  ).map((state) => ({
    key: state,
    style: STATE_STYLES[state],
  })),
  // Not a state, but it is a sixth thing an orb can look like, and it is the
  // one whose meaning is least guessable from its appearance.
  { key: "structural", style: STRUCTURAL_STYLE },
];

/**
 * How a tree was built, said plainly.
 *
 * Assembled and proposed are both playable and neither is hidden -- the
 * difference is whether a person reviewed this curriculum or the system put it
 * together from the shared catalogue, and a learner is entitled to know which.
 */
const PROVENANCE_LABEL: Record<string, string> = {
  "catalogue-assembly-v1":
    "Built from a reviewed curriculum for this instrument.",
  "catalogue-plan-v1":
    "Assembled from the shared skill catalogue for your goal — not yet reviewed by a person.",
  "curriculum-compiler-v1":
    "Compiled from your sources, with a quote behind every prerequisite.",
};

export default function CoursePage() {
  // `useSearchParams` opts the subtree into client-side bailout, so Next 15
  // requires it to sit under a Suspense boundary.
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-[1400px] px-4 py-6 text-sm text-slate-400">
          Loading…
        </main>
      }
    >
      <CourseView />
    </Suspense>
  );
}

function CourseView() {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const searchParams = useSearchParams();
  const requestedNodeId = searchParams.get("node");
  const campaignGoal = searchParams.get("goal") ?? "";

  const {
    snapshot,
    positions,
    status,
    error,
    selectedNodeId,
    lessonFor,
    load,
    select,
    openLesson,
    focusNode,
  } = useGraphStore();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // The guided path's cursor is a function of mastery, so it has to be refetched
  // after a grade. Bumped rather than refetched inline so the panel owns its own
  // request and a failure there cannot blank the tree.
  const [pathVersion, setPathVersion] = useState(0);
  const [campaignPath, setCampaignPath] = useState<CoursePath | null>(null);
  const [campaignProgress, setCampaignProgress] =
    useState<ProgressAnalytics | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [realmFade, setRealmFade] = useState<
    "idle" | "to-black" | "from-black"
  >("idle");
  const realmFadeTimer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    setPathVersion((version) => version + 1);
    // Independent and concurrent: the header must not wait on the graph, and a
    // failure in either must not blank the other.
    await Promise.all([
      load(courseId),
      api
        .getCourse(courseId)
        .then(setCourse)
        .catch(() => {
          // The graph is the important half; a stale header is survivable.
        }),
    ]);
  }, [courseId, load]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // A quest links to /courses/{id}?node={nodeId}. Without this the board's
  // primary call-to-action dropped you into an unselected tree with no detail
  // panel and no drill button -- the decay-fighting loop had no landing.
  //
  // `focusNode` rather than `select`: selecting alone filled the inspector but
  // left the canvas wherever `fitView` had put it, which on a real tree means
  // the node you were sent to is a 72px orb somewhere off screen.
  //
  // Applied once per requested id: re-applying on every graph refresh would
  // yank the selection back after the user clicked elsewhere.
  const appliedNodeParam = useRef<string | null>(null);
  useEffect(() => {
    if (
      !requestedNodeId ||
      status !== "ready" ||
      appliedNodeParam.current === requestedNodeId
    )
      return;
    if (snapshot?.nodes.some((node) => node.id === requestedNodeId)) {
      appliedNodeParam.current = requestedNodeId;
      focusNode(requestedNodeId);
    }
  }, [requestedNodeId, status, snapshot, focusNode]);

  const selected = useMemo(
    () => snapshot?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [snapshot, selectedNodeId],
  );

  const inspectorRef = useRef<HTMLDivElement | null>(null);

  /** The realm the learner is standing in, and the runs behind every skill. */
  const [realmNodeId, setRealmNodeId] = useState<string | null>(null);
  const [leftRealmAt, setLeftRealmAt] = useState<string | null>(null);
  const [realmsVersion, setRealmsVersion] = useState(0);
  const [realms, setRealms] = useState<SkillRealm[]>([]);

  useEffect(() => {
    return () => {
      if (realmFadeTimer.current !== null)
        window.clearTimeout(realmFadeTimer.current);
    };
  }, []);

  /**
   * Bring the lesson into view when it opens from the tree.
   *
   * The inspector sits at the foot of a long column, so without this a learner
   * double-clicks an orb, the lesson starts somewhere below the fold, and the
   * gesture reads as having done nothing at all.
   *
   * @spec PROG-DRILL-001
   */
  useEffect(() => {
    if (lessonFor === null) return;
    inspectorRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "center",
    });
  }, [lessonFor]);

  /**
   * The learner double-clicked a skill, or pressed Enter on one already selected.
   *
   * Two skills do not open a lesson, and both refusals still select so the
   * inspector can explain itself. A structural heading owns no skill to drill,
   * and a locked skill has unmet prerequisites the inspector names -- silently
   * starting a lesson there would contradict the tree the learner is looking at.
   *
   * @spec PROG-DRILL-001, PROG-DRILL-002, PROG-DRILL-003, PROG-DRILL-004
   */
  const requestLesson = useCallback(
    (nodeId: string) => {
      const node = snapshot?.nodes.find((candidate) => candidate.id === nodeId);
      if (canOpenLesson(node)) {
        // Into the skill's realm, not straight into its test. The lessons are
        // the middle ground between never having tried the skill and being
        // examined on it, and skipping them is what the run exists to prevent.
        select(nodeId);
        setLeftRealmAt(null);
        if (prefersReducedMotion) {
          setRealmNodeId(nodeId);
        } else {
          setRealmFade("to-black");
          if (realmFadeTimer.current !== null)
            window.clearTimeout(realmFadeTimer.current);
          realmFadeTimer.current = window.setTimeout(() => {
            setRealmNodeId(nodeId);
            setRealmFade("from-black");
            realmFadeTimer.current = window.setTimeout(() => {
              setRealmFade("idle");
              realmFadeTimer.current = null;
            }, 420);
          }, 420);
        }
      } else {
        select(nodeId);
      }
    },
    [prefersReducedMotion, select, snapshot],
  );

  /**
   * Runs are fetched once for the whole course rather than per realm: opening
   * one is a double-click, which is not a moment to start a round trip.
   *
   * @spec PROG-REALM-001, PROG-REALM-004
   */
  useEffect(() => {
    let cancelled = false;
    api
      .listSkillRealms(courseId)
      .then((found) => {
        if (!cancelled) setRealms(found);
      })
      // A realm that cannot load is a realm the learner cannot enter; the tree
      // behind it still works, so this must not take the page down.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [courseId, lessonFor, realmsVersion]);

  const realm = useMemo(
    () => realms.find((entry) => entry.node_id === realmNodeId) ?? null,
    [realms, realmNodeId],
  );

  /**
   * The counts under the title.
   *
   * Derived here rather than read from `snapshot.stats`, because the two
   * numbers mean different things. `stats.available` is a census of the *state
   * machine* -- and a structural node genuinely is in state `available`, on
   * purpose: `gating_masteries` walks through containers, so they have to be
   * able to reach `available` or every subtree behind one would be locked for
   * ever. But "N ready" is a promise about what you can go and DO, and a
   * container is not something you can do. On a freshly ingested textbook the
   * whole top rank is containers, so the two numbers diverge by a lot exactly
   * when a new user is reading them.
   *
   * The snapshot already carries every node, so nothing is fetched for this.
   */
  const counts = useMemo(() => {
    const nodes = snapshot?.nodes ?? [];
    const skills = nodes.filter((node) => node.assessable);
    return {
      skills: skills.length,
      sections: nodes.length - skills.length,
      ready: skills.filter((node) => node.progress.state === "available")
        .length,
      fading: skills.filter((node) => node.progress.state === "decaying")
        .length,
      mastered: skills.filter((node) => node.progress.state === "mastered")
        .length,
    };
  }, [snapshot]);

  const selectedDue = selected ? dueLabel(selected.progress.due_at) : null;
  const selectedPrerequisiteEdges = useMemo(
    () =>
      snapshot?.edges.filter((edge) => edge.target === selectedNodeId) ?? [],
    [snapshot, selectedNodeId],
  );
  const sourceName = (documentId: string) =>
    course?.documents.find((document) => document.id === documentId)
      ?.filename ?? "Source document";

  // On a wide screen the page is exactly one viewport: the header takes what it
  // needs and the grid takes the rest, so neither column can make the document
  // grow. Below the breakpoint it flows normally -- a phone has no room for two
  // columns and scrolling is the right answer there.
  //
  // @spec UI-PAGE-001, UI-PAGE-002
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="mx-auto flex max-w-[1400px] flex-col px-4 py-6 outline-none lg:h-[calc(100dvh-var(--hud-h))]"
    >
      <div className="flex shrink-0 items-start justify-between gap-4">
        <div>
          <Link
            href="/courses"
            className={`text-xs text-slate-400 hover:text-slate-200 ${FOCUS_RING}`}
          >
            ← All courses
          </Link>
          <h1 className="mt-1 font-display text-xl font-semibold tracking-tight">
            {course?.title ?? "Course"}
          </h1>
          {/* @spec CURR-GOAL-013 -- everything here is playable; the label is
              what stops a proposed tree claiming an authority it does not have. */}
          {course?.curriculum_provenance && (
            <p className="mt-1 text-[11px] text-slate-400">
              {PROVENANCE_LABEL[course.curriculum_provenance] ??
                "Built from your goal."}
            </p>
          )}
          {snapshot && (
            <p className="mt-1 text-xs text-slate-400">
              {counts.skills} skills · {counts.ready} ready · {counts.fading}{" "}
              fading · {counts.mastered} mastered
              {counts.sections > 0 && ` · ${counts.sections} sections`}
            </p>
          )}
          {/* The store deliberately keeps the last good snapshot when a refresh
              fails, so `status` stays "ready" and the error branch below the
              canvas is unreachable by construction -- which made the refresh
              after EVERY grade fail silently: you answer correctly, see the EXP,
              and the tree just does not change. */}
          {error && status === "ready" && (
            <p
              role="alert"
              className="mt-1 flex items-center gap-2 text-xs text-node-decaying"
            >
              <span>
                Showing the last loaded tree — refresh failed: {error}
              </span>
              <button
                type="button"
                onClick={() => void refresh()}
                className={`rounded-sm underline underline-offset-2 hover:text-amber-200 ${FOCUS_RING}`}
              >
                Retry
              </button>
            </p>
          )}
        </div>

        {/* The legend is the only place the meaning of an orb is explained, and
            it used to live entirely in `title=` attributes on non-focusable
            spans -- the exact pattern SkillNodeCard rejects by name, because a
            title never appears on touch and is unreliable for screen readers.
            A <details> is reachable by keyboard, works on touch, and can hold
            the full sentence rather than a truncated tooltip. */}
        <div className="flex shrink-0 items-start gap-3">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className={`${BUTTON_SECONDARY} whitespace-nowrap text-xs`}
          >
            Course ▸
          </button>
          <details className="max-w-xs">
            <summary
              className={`cursor-pointer text-[11px] text-slate-400 hover:text-slate-200 ${FOCUS_RING}`}
            >
              What the orbs mean
            </summary>
            <dl className="mt-2 space-y-1.5">
              {LEGEND.map(({ key, style }) => (
                <div
                  key={key}
                  className="flex items-baseline gap-1.5 text-[11px]"
                >
                  <span
                    aria-hidden
                    className="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: style.accent }}
                  />
                  <dt className="shrink-0 text-slate-300">{style.label}</dt>
                  <dd className="text-slate-400">— {style.hint}</dd>
                </div>
              ))}
            </dl>
          </details>
        </div>
      </div>

      <div className="mt-5 grid min-h-0 gap-4 lg:flex-1 lg:grid-cols-[1fr_340px]">
        <div className="relative hidden min-h-0 overflow-hidden rounded-xl border border-slate-800 bg-slate-950 md:block lg:h-full max-lg:h-[70vh]">
          {status === "loading" && (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              Loading the tree…
            </div>
          )}
          {status === "error" && (
            <div className="flex h-full items-center justify-center text-sm text-rose-400">
              {error}
            </div>
          )}
          {status === "ready" && snapshot && snapshot.nodes.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
              <p className="text-sm text-slate-400">No skills yet.</p>
              <p className="text-xs text-slate-400">
                Upload a PDF and the tree will build itself.
              </p>
            </div>
          )}
          {status === "ready" &&
            snapshot &&
            snapshot.nodes.length > 0 &&
            (realm ? (
              <SkillRealm3D
                realm={realm}
                onExit={() => {
                  // Remembered so the tree can pick the camera up where the
                  // realm left it, rather than cutting back to the wide shot.
                  setLeftRealmAt(realm.node_id);
                  setRealmNodeId(null);
                }}
                // The practice panel, rendered INSIDE the realm. It is already
                // the one place a take is recorded, so the realm borrows it
                // rather than growing a second recorder.
                renderLesson={(lesson) => (
                  <LessonWorkspace
                    courseId={courseId}
                    exerciseId={lesson.exercise_id}
                    refreshKey={pathVersion}
                    onCompleted={() => {
                      // Refetch so the chain behind this overlay reflects the
                      // take. Deliberately NOT closing: the learner just earned a
                      // score and some feedback, and closing over it would throw
                      // away the only moment they can read it. `close` is the
                      // back button, which is theirs to press.
                      refresh();
                      setRealmsVersion((version) => version + 1);
                    }}
                  />
                )}
                onOpenTest={() => openLesson(realm.node_id)}
              />
            ) : (
              <SkillGraph3D
                snapshot={snapshot}
                selectedNodeId={selectedNodeId}
                onOpenLesson={requestLesson}
                onSelect={select}
                arriveFrom={leftRealmAt}
              />
            ))}
        </div>

        <div className="md:hidden">
          {status === "loading" && (
            <p className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400">
              Loading the skill outline…
            </p>
          )}
          {status === "error" && (
            <p
              role="alert"
              className="rounded-xl border border-rose-900/60 bg-slate-950 p-4 text-sm text-rose-400"
            >
              {error}
            </p>
          )}
          {status === "ready" && snapshot && snapshot.nodes.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-800 bg-slate-950 p-6 text-center">
              <p className="text-sm text-slate-400">No skills yet.</p>
              <p className="mt-1 text-xs text-slate-400">
                Upload a PDF and the tree will build itself.
              </p>
            </div>
          )}
          {status === "ready" && snapshot && snapshot.nodes.length > 0 && (
            <SkillTreeOutline
              snapshot={snapshot}
              selectedNodeId={selectedNodeId}
              onSelect={select}
            />
          )}
        </div>

        {/* Three panels, in the order a learner needs them: what you just
            clicked, what to do next, how it is going. The other twelve moved to
            the course drawer or into the realm -- a column of fifteen stacked
            panels was what made this page four screens tall, and the grid row
            stretched to it.
            @spec UI-PAGE-001, UI-PAGE-004 */}
        <aside className="min-h-0 space-y-4 lg:h-full lg:overflow-y-auto lg:pr-1">
          <div className={CARD} ref={inspectorRef}>
            {selected ? (
              <>
                <h2 className="font-display text-sm font-semibold">
                  {selected.title}
                </h2>
                {/* `depth` used to be printed beside `difficulty`, but
                    `difficulty_from_depth` computes 1 + round(depth / max(max_depth, 4) * 4),
                    so for any graph four levels deep or less difficulty IS
                    depth + 1, exactly. Two names for one number read as two
                    independent judgements. */}
                <p className="mt-0.5 text-[11px] text-slate-400">
                  {selected.assessable
                    ? `${stateStyle(selected.progress.state).label} · ${difficultyLabel(selected.difficulty)}`
                    : STRUCTURAL_STYLE.label}
                </p>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">
                  {selected.summary}
                </p>

                {selected.assessable && (
                  <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                    <div>
                      <dt className="text-slate-400">Level</dt>
                      <dd className="text-slate-300">
                        {selected.progress.level} / 5
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-400">EXP</dt>
                      <dd className="text-slate-300">
                        {selected.progress.exp}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-400">Mastery</dt>
                      <dd className="text-slate-300">
                        {Math.round(selected.progress.mastery * 100)}%
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-400">Proficiency now</dt>
                      <dd className="text-slate-300">
                        {Math.round(selected.progress.proficiency * 100)}%
                      </dd>
                    </div>
                    <div className="col-span-2">
                      <dt className="text-slate-400">Next review</dt>
                      {/* The schedule, forwards. `due_at` has been on the
                          contract since the first version and was rendered
                          nowhere, so the app showed time only after a skill had
                          already decayed. */}
                      <dd
                        className={
                          selected.progress.overdue_days > 0
                            ? "text-node-decaying"
                            : "text-slate-300"
                        }
                      >
                        {selectedDue ??
                          "Not scheduled yet — drill it once to start the clock"}
                      </dd>
                    </div>
                  </dl>
                )}

                {selected.blocked_by.length > 0 && (
                  <p className="mt-3 text-[11px] text-slate-400">
                    Blocked by{" "}
                    {selected.blocked_by.map((b) => b.title).join(", ")}
                  </p>
                )}

                {selected.sources.length > 0 && (
                  <div
                    className="mt-3 rounded-lg border border-emerald-900/50 bg-emerald-950/10 p-2.5"
                    aria-label="Skill source evidence"
                  >
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                      Skill source evidence
                    </h3>
                    <ul className="mt-2 space-y-2">
                      {selected.sources.map((source) => (
                        <li
                          key={source.chunk_id}
                          className="text-[10px] text-slate-400"
                        >
                          <p className="text-slate-300">
                            {sourceName(source.document_id)} · page{" "}
                            {source.page_start + 1}
                            {source.section_path
                              ? ` · ${source.section_path}`
                              : ""}
                          </p>
                          <p className="mt-0.5 leading-relaxed text-slate-500">
                            “{source.excerpt}”
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {selectedPrerequisiteEdges.length > 0 && (
                  <div
                    className="mt-3 rounded-lg border border-amber-900/50 bg-amber-950/10 p-2.5"
                    aria-label="Prerequisite edge evidence"
                  >
                    <h3 className="text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                      Prerequisite evidence
                    </h3>
                    <ul className="mt-2 space-y-2">
                      {selectedPrerequisiteEdges.map((edge) => {
                        const prerequisite = snapshot?.nodes.find(
                          (node) => node.id === edge.source,
                        );
                        return (
                          <li
                            key={edge.id}
                            className="text-[10px] text-slate-400"
                          >
                            <p className="text-slate-300">
                              {prerequisite?.title ?? "Prerequisite"} ·{" "}
                              {Math.round(edge.confidence * 100)}% confidence ·{" "}
                              {edge.support} supporting pass
                              {edge.support === 1 ? "" : "es"}
                            </p>
                            {edge.rationale && (
                              <p className="mt-0.5 text-slate-500">
                                {edge.rationale}
                              </p>
                            )}
                            {edge.sources.slice(0, 1).map((source) => (
                              <p
                                key={source.chunk_id}
                                className="mt-0.5 leading-relaxed text-slate-500"
                              >
                                {sourceName(source.document_id)} · page{" "}
                                {source.page_start + 1}: “{source.excerpt}”
                              </p>
                            ))}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                <div className="mt-4">
                  {/* Keyed on the node so switching selection resets the drill
                      rather than showing the previous skill's question. */}
                  <DrillPanel
                    key={selected.id}
                    node={selected}
                    documents={course?.documents ?? []}
                    onGraded={refresh}
                    autoStart={lessonFor === selected.id}
                  />
                </div>
              </>
            ) : (
              <p className="text-xs text-slate-400">
                Select a skill to see its details, prerequisites, and progress.
              </p>
            )}
          </div>

          <GuidedPath
            courseId={courseId}
            refreshKey={pathVersion}
            onPathLoaded={setCampaignPath}
          />
          <ProgressPanel
            courseId={courseId}
            refreshKey={pathVersion}
            onProgressLoaded={setCampaignProgress}
          />
        </aside>
      </div>

      <div
        className={`pointer-events-none fixed inset-0 z-50 bg-black transition-opacity duration-[420ms] ${
          realmFade === "to-black" ? "opacity-100" : "opacity-0"
        }`}
        aria-hidden="true"
      />

      <CourseDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        courseId={courseId}
        course={course}
        campaignGoal={campaignGoal}
        campaignPath={campaignPath}
        campaignProgress={campaignProgress}
        refreshKey={pathVersion}
        onRefresh={refresh}
      />
    </main>
  );
}

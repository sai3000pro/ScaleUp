"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type {
  DocumentSummary,
  Drill,
  GradeResult,
  GraphNode,
  KnownVerdict,
  QuestionType,
  Verdict,
} from "@/lib/types";
import { sourceLabel } from "@/lib/source";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT } from "@/lib/ui";
import { useAuthStore } from "@/stores/useAuthStore";
import { useGraphStore } from "@/stores/useGraphStore";

const VERDICT_STYLE: Record<KnownVerdict, string> = {
  correct: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  partial: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  incorrect: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

// A verdict this build has not seen still has to render a readable box rather
// than splice the literal string "undefined" into the className.
const VERDICT_FALLBACK = "border-slate-700 bg-slate-800/60 text-slate-200";

function verdictStyle(verdict: Verdict): string {
  return VERDICT_STYLE[verdict as KnownVerdict] ?? VERDICT_FALLBACK;
}

/**
 * "Unlocked Weak duality and 2 more." rather than "Unlocked 3 new skills."
 *
 * The unlock cascade is the single most motivating moment in the loop, and it
 * was rendered as a bare `.length`. That also hid a real backend improvement:
 * the extractor was changed so `unlocked_node_ids` names the skill you actually
 * revealed rather than the chapter heading above it, and with only a count on
 * screen there was no way to tell the difference.
 *
 * Falls back to the count when a title cannot be resolved, which happens when
 * the graph refresh that follows a grade fails -- the snapshot is then the one
 * from before the answer and may not contain the new ids.
 */
function unlockMessage(ids: string[], titleOf: (id: string) => string | undefined): string {
  const titles = ids.map(titleOf).filter((title): title is string => Boolean(title));
  if (titles.length === 0) {
    return `Unlocked ${ids.length} new skill${ids.length === 1 ? "" : "s"}.`;
  }
  if (titles.length === 1) return `Unlocked ${titles[0]}.`;
  if (titles.length === 2) return `Unlocked ${titles[0]} and ${titles[1]}.`;
  return `Unlocked ${titles[0]} and ${titles.length - 1} more.`;
}

export function DrillPanel({
  node,
  onGraded,
  documents,
  autoStart = false,
}: {
  node: GraphNode;
  onGraded: () => void;
  documents: DocumentSummary[];
  /**
   * Begin the lesson on mount, because the learner asked for it from the tree
   * rather than by opening this panel and pressing start.
   *
   * Fires at most once per mount, and never over work already in progress: the
   * panel is keyed on the node, so a learner who double-clicks the skill they
   * are already answering keeps their answer.
   */
  autoStart?: boolean;
}) {
  const refreshUser = useAuthStore((state) => state.refreshUser);
  // Read straight from the store rather than taking a prop: the snapshot is
  // already there, and the alternative is threading the whole graph through the
  // course page purely so this panel can turn four ids into four names.
  const snapshot = useGraphStore((state) => state.snapshot);

  const [drill, setDrill] = useState<Drill | null>(null);
  const [questionType, setQuestionType] = useState<QuestionType>("short_answer");
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<GradeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const autoStarted = useRef(false);

  async function start() {
    setBusy(true);
    setError(null);
    setResult(null);
    setAnswer("");
    try {
      // A fresh key per drill: retries of THIS request are free, but asking for
      // a new question later legitimately costs a new generation.
      setDrill(await api.startDrill(node.id, crypto.randomUUID(), questionType));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // @spec PROG-DRILL-001, PROG-DRILL-005
  useEffect(() => {
    if (!autoStart || autoStarted.current || drill !== null || busy) return;
    autoStarted.current = true;
    void start();
    // `start` is stable for this mount and the panel is keyed on the node, so
    // re-running on its identity would only risk a second question.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!drill || !answer.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const graded = await api.gradeAttempt(drill.attempt_id, answer);
      setResult(graded);
      // `level_before`/`level_after` are this NODE's level (0..5), not the
      // account level -- feeding them to the HUD made mastering one skill read
      // as an account level-up. Re-read the account instead.
      void refreshUser();
      onGraded();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!drill) {
    // A structural node carries the tree's shape and has no skill of its own,
    // so the button was already disabled for it -- but it still read "Drill
    // this skill", which makes a deliberate decision look like a broken one.
    const structural = !node.assessable;
    const locked = node.progress.state === "locked";
    const label = busy
      ? "Writing a question…"
      : structural
        ? "Nothing to drill here"
        : locked
          ? "Locked"
          : "Drill this skill";

    return (
      <div>
        {!structural && !locked && (
          <div className="mb-2 flex gap-1 rounded-lg border border-slate-800 bg-slate-950 p-1" role="group" aria-label="Question format">
            {(["short_answer", "mcq", "cloze", "code"] as QuestionType[]).map((format) => (
              <button
                key={format}
                type="button"
                onClick={() => setQuestionType(format)}
                className={`flex-1 rounded-md px-2 py-1 text-[11px] transition ${
                  questionType === format ? "bg-sky-500 text-slate-950" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {format === "mcq"
                  ? "Multiple choice"
                  : format === "cloze"
                    ? "Fill the blank"
                    : format === "code"
                      ? "Code"
                      : "Short answer"}
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          onClick={start}
          disabled={busy || locked || structural}
          className={`w-full ${BUTTON_PRIMARY}`}
        >
          {label}
        </button>
        {structural && (
          <p className="mt-1.5 text-center text-[11px] text-slate-400">
            A section heading, not a skill — drill the skills underneath it.
          </p>
        )}
        {node.progress.state === "decaying" && (
          <p className="mt-1.5 text-center text-[11px] text-node-decaying">Overdue — rescuing this pays bonus EXP</p>
        )}
        {error && <p role="alert" className="mt-2 text-xs text-rose-400">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-[11px] uppercase tracking-wide text-slate-400">Question</p>
        <p className="mt-1 text-sm leading-relaxed text-slate-200">{drill.question}</p>
        {drill.sources.length > 0 && (
          <p className="mt-1.5 text-[11px] text-slate-400">
            From {drill.sources.map((source) => sourceLabel(source, documents)).join(" · ")}
          </p>
        )}
      </div>

      {!result && (
        <form onSubmit={submit} className="space-y-2">
          {drill.question_type === "mcq" ? (
            <fieldset className="space-y-2">
              <legend className="sr-only">Choose an answer</legend>
              {drill.options.map((option) => (
                <label
                  key={option.id}
                  className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2 text-xs transition ${
                    answer === option.id
                      ? "border-sky-400 bg-sky-500/10 text-slate-100"
                      : "border-slate-800 bg-slate-950 text-slate-300 hover:border-slate-600"
                  }`}
                >
                  <input
                    type="radio"
                    name={`answer-${drill.attempt_id}`}
                    value={option.id}
                    checked={answer === option.id}
                    onChange={(event) => setAnswer(event.target.value)}
                    className="mt-0.5 accent-sky-400"
                  />
                  <span>{option.text}</span>
                </label>
              ))}
            </fieldset>
          ) : drill.question_type === "cloze" ? (
            <input
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              autoFocus
              placeholder="Fill the blank"
              className={`${INPUT} bg-slate-950`}
            />
          ) : (
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              rows={drill.question_type === "code" ? 10 : 5}
              autoFocus
              placeholder={
                drill.question_type === "code"
                  ? `Write ${drill.code_language ?? "the requested"} code. It will be checked statically, never executed.`
                  : "Answer in your own words — you're graded on meaning, not wording."
              }
              spellCheck={drill.question_type !== "code"}
              className={`${INPUT} resize-none bg-slate-950 ${drill.question_type === "code" ? "font-mono text-[11px]" : ""}`}
            />
          )}
          <button
            type="submit"
            disabled={busy || !answer.trim()}
            className={`w-full ${BUTTON_PRIMARY}`}
          >
            {busy ? "Grading…" : "Submit answer"}
          </button>
        </form>
      )}

      {result && (
        <div className={`rounded-lg border p-3 ${verdictStyle(result.verdict)}`}>
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-semibold capitalize">{result.verdict}</span>
            <span className="text-sm font-semibold">+{result.exp_awarded} EXP</span>
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-200">{result.feedback}</p>

          {/* The rubric breakdown. The grader has always returned these and
              nothing rendered them, which left a score looking like an opinion.
              "EXP for demonstrated understanding" needs to show the
              demonstration. */}
          {(result.points_hit.length > 0 || result.points_missed.length > 0) && (
            <ul className="mt-2 space-y-0.5">
              {result.points_hit.map((point) => (
                <li key={`hit-${point}`} className="flex items-baseline gap-1.5 text-[11px] text-slate-300">
                  <span aria-hidden className="text-node-available">
                    ✓
                  </span>
                  <span className="sr-only">Covered:</span>
                  {point}
                </li>
              ))}
              {result.points_missed.map((point) => (
                <li key={`miss-${point}`} className="flex items-baseline gap-1.5 text-[11px] text-slate-400">
                  <span aria-hidden className="text-node-decaying">
                    ×
                  </span>
                  <span className="sr-only">Missed:</span>
                  {point}
                </li>
              ))}
            </ul>
          )}

          {result.rescue_bonus_applied && (
            <p className="mt-1.5 text-[11px] text-node-decaying">Rescue bonus applied — you brought this back.</p>
          )}
          {result.level_up && (
            <p className="mt-1.5 text-[11px] font-semibold text-node-mastered">
              Skill level up! {result.level_before} → {result.level_after}
            </p>
          )}
          {result.account_level_up && (
            <p className="mt-1.5 text-xs font-semibold text-violet-300">
              Character level up! {result.account_level_before} → {result.account_level_after}. Visit your character sheet to spend your perk point.
            </p>
          )}
          {result.unlocked_node_ids.length > 0 && (
            <p className="mt-1.5 text-[11px] text-node-available">
              {unlockMessage(
                result.unlocked_node_ids,
                (id) => snapshot?.nodes.find((candidate) => candidate.id === id)?.title,
              )}
            </p>
          )}

          <button
            type="button"
            onClick={start}
            className={`mt-3 w-full ${BUTTON_SECONDARY} py-1.5 text-xs`}
          >
            Another question
          </button>
        </div>
      )}

      {error && <p role="alert" className="text-xs text-rose-400">{error}</p>}
    </div>
  );
}

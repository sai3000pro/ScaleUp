"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { difficultyLabel, stateStyle } from "@/lib/nodeState";
import type {
  CampaignBriefing as CampaignBriefingData,
  CampaignOutcomeEvaluation,
  CampaignSideQuest,
  CoursePath,
  ProgressAnalytics,
} from "@/lib/types";
import { BUTTON_PRIMARY, CARD, FOCUS_RING } from "@/lib/ui";
import { useGraphStore } from "@/stores/useGraphStore";

interface Props {
  courseId: string;
  refreshKey: number;
  path: CoursePath | null;
  progress: ProgressAnalytics | null;
  isBuilding: boolean;
}

/**
 * The campaign's quest-giver panel.
 *
 * Path and progress are shared from their existing panels. Tree shape and
 * victory-condition coverage come from the owner-scoped backend briefing so
 * the RPG summary is authoritative rather than a client-only guess.
 */
export function CampaignBriefing({ courseId, refreshKey, path, progress, isBuilding }: Props) {
  const focusNode = useGraphStore((state) => state.focusNode);
  const [briefing, setBriefing] = useState<CampaignBriefingData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .getCampaignBriefing(courseId)
      .then((found) => {
        if (live) {
          setBriefing(found);
          setError(null);
        }
      })
      .catch(() => {
        if (live) setError("Campaign briefing is unavailable right now.");
      });
    return () => {
      live = false;
    };
  }, [courseId, refreshKey]);

  if (error) return <p className={`${CARD} text-xs text-rose-400`}>{error}</p>;
  if (!briefing || briefing.tree_shape.playable_skills === 0 || !path || path.total === 0) {
    if (!isBuilding) return null;
    return (
      <section className={`${CARD} border-sky-900/60 bg-sky-950/10`} aria-labelledby="campaign-briefing-heading">
        <h2 id="campaign-briefing-heading" className="font-display text-sm font-semibold text-sky-100">
          Campaign briefing
        </h2>
        <p className="mt-2 text-xs leading-relaxed text-slate-300">
          Your sources are being mapped into skills and prerequisite links. The first quest will appear here when the skill tree is ready.
        </p>
      </section>
    );
  }

  const quest = path.steps.find((step) => step.node_id === path.next_node_id) ?? null;
  if (!quest) {
    return (
      <section className={`${CARD} border-emerald-900/60 bg-emerald-950/10`} aria-labelledby="campaign-briefing-heading">
        <div className="flex items-baseline justify-between gap-2">
          <h2 id="campaign-briefing-heading" className="font-display text-sm font-semibold text-emerald-100">
            Campaign cleared
          </h2>
          <span className="text-[11px] text-slate-400">{path.completed} / {path.total}</span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-slate-300">
          Every skill on the main path is above the mastery threshold. Keep your party sharp by checking Daily Quests for fading skills.
        </p>
        {briefing.target_outcome && <p className="mt-2 text-[11px] font-semibold text-emerald-300">Victory condition: {briefing.target_outcome}</p>}
        <TreeShape shape={briefing.tree_shape} />
        <OutcomeCoverage courseId={courseId} coverage={briefing.outcome_coverage} />
        <SourceCoverage progress={progress} />
        <Link href="/quests" className={`mt-3 inline-block text-xs text-emerald-300 hover:text-emerald-200 ${FOCUS_RING}`}>
          Visit Daily Quests →
        </Link>
      </section>
    );
  }

  const upcoming = path.steps.find((step) => !step.done && step.order > quest.order) ?? null;
  const questStyle = stateStyle(quest.state);
  const heading = path.completed === 0 ? "Begin your adventure" : "Continue your adventure";

  return (
    <section className={`${CARD} border-sky-900/60 bg-sky-950/10`} aria-labelledby="campaign-briefing-heading">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="campaign-briefing-heading" className="font-display text-sm font-semibold text-sky-100">
          {heading}
        </h2>
        <span className="text-[11px] text-slate-400">{path.completed} / {path.total} skills</span>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">Your next quest is chosen from the prerequisite order.</p>
      {briefing.target_outcome && <p className="mt-2 text-[11px] font-semibold text-violet-300">Victory condition: {briefing.target_outcome}</p>}

      <div className="mt-3 rounded-lg border border-sky-900/60 bg-slate-950/50 p-3">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-sky-300">Current quest</p>
        <h3 className="mt-1 font-display text-sm font-semibold text-slate-100">Drill {quest.title}</h3>
        <p className="mt-1 text-[11px] text-slate-400">{quest.summary}</p>
        <p className="mt-2 text-[10px] text-slate-500">
          {questStyle.label} · {difficultyLabel(quest.difficulty)} · step {quest.order + 1}
        </p>
        <button
          type="button"
          onClick={() => focusNode(quest.node_id)}
          className={`mt-3 w-full ${BUTTON_PRIMARY} text-xs`}
        >
          Open skill and drill
        </button>
      </div>

      {upcoming && (
        <p className="mt-3 text-[11px] text-slate-400">
          Next unlock on your path: <span className="font-semibold text-slate-300">{upcoming.title}</span>. Master this skill to advance.
        </p>
      )}
      <TreeShape shape={briefing.tree_shape} />
      <OutcomeCoverage courseId={courseId} coverage={briefing.outcome_coverage} />
      <SourceCoverage progress={progress} />
      <Link href="/quests" className={`mt-2 inline-block text-[11px] text-slate-400 hover:text-slate-200 ${FOCUS_RING}`}>
        See all Daily Quests →
      </Link>
    </section>
  );
}

function TreeShape({ shape }: { shape: CampaignBriefingData["tree_shape"] }) {
  const depths = Object.entries(shape.depth_counts);
  const largestDepth = Math.max(...depths.map(([, count]) => count), 1);
  return (
    <div className="mt-3 rounded-lg border border-sky-900/60 bg-sky-950/30 p-2.5" aria-label="Generated skill tree shape">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-sky-300">Actual skill-tree shape</p>
        <span className="text-[10px] text-slate-500">{shape.depth} level{shape.depth === 1 ? "" : "s"} deep</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-[10px]">
        <div><span className="block text-slate-500">Playable skills</span><span className="font-semibold text-slate-200">{shape.playable_skills}</span></div>
        <div><span className="block text-slate-500">Branches</span><span className="font-semibold text-slate-200">{shape.branches}</span></div>
        <div><span className="block text-slate-500">Prerequisite links</span><span className="font-semibold text-slate-200">{shape.prerequisite_links}</span></div>
      </div>
      <p className="mt-2 text-[10px] text-slate-500">
        Starts with: {shape.starting_skills.slice(0, 3).map((skill) => skill.title).join(", ") || "the first available skills"}
        {shape.starting_skills.length > 3 ? `, and ${shape.starting_skills.length - 3} more` : ""}.
      </p>
      <div className="mt-2 flex items-end gap-1" aria-label="Skills by tree depth">
        {depths.map(([depth, count]) => (
          <div key={depth} className="flex min-w-0 flex-1 flex-col items-center gap-1">
            <div className="w-full rounded-t-sm bg-sky-400/70" style={{ height: `${Math.max(6, (count / largestDepth) * 36)}px` }} title={`Depth ${depth}: ${count} skills`} />
            <span className="text-[9px] text-slate-500">D{depth}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OutcomeCoverage({
  courseId,
  coverage,
}: {
  courseId: string;
  coverage: CampaignBriefingData["outcome_coverage"];
}) {
  const [evaluation, setEvaluation] = useState<CampaignOutcomeEvaluation | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluationError, setEvaluationError] = useState<string | null>(null);
  const [copiedCapability, setCopiedCapability] = useState<string | null>(null);

  if (!coverage.outcome || coverage.terms.length === 0) return null;

  const evaluate = async () => {
    setEvaluating(true);
    setEvaluationError(null);
    setCopiedCapability(null);
    try {
      const result = await api.evaluateCampaignOutcome(courseId);
      setEvaluation(result);
    } catch {
      setEvaluationError("The campaign evaluator could not review the tree right now.");
    } finally {
      setEvaluating(false);
    }
  };

  const copySourceQuery = async (quest: CampaignSideQuest) => {
    try {
      await navigator.clipboard.writeText(quest.source_query);
      setCopiedCapability(quest.capability);
    } catch {
      setEvaluationError("Could not copy the source-search prompt. Select it manually instead.");
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-violet-900/60 bg-violet-950/10 p-2.5" aria-label="Victory condition coverage">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-violet-300">Victory-condition signal</p>
        <span className="text-[10px] text-slate-500">{Math.round(coverage.coverage * 100)}% visible</span>
      </div>
      <p className="mt-1 text-[10px] leading-relaxed text-slate-400">{coverage.signal} This is a lexical check, not a semantic quality judgement.</p>
      {coverage.matched_terms.length > 0 && <p className="mt-2 text-[10px] text-emerald-300">Visible: {coverage.matched_terms.join(", ")}</p>}
      {coverage.missing_terms.length > 0 && <p className="mt-1 text-[10px] text-amber-300">Not obvious yet: {coverage.missing_terms.join(", ")}</p>}
      <button
        type="button"
        onClick={() => void evaluate()}
        disabled={evaluating}
        className={`mt-2 text-[10px] text-violet-300 underline underline-offset-2 hover:text-violet-200 disabled:cursor-wait disabled:opacity-60 ${FOCUS_RING}`}
      >
        {evaluating ? "Evaluating the campaign…" : "Evaluate outcome against the skill tree"}
      </button>
      {evaluationError && <p role="alert" className="mt-1 text-[10px] text-rose-300">{evaluationError}</p>}
      {evaluation && (
        <div className="mt-2 rounded border border-violet-900/50 bg-slate-950/40 p-2">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-violet-200">Outcome readiness</p>
            <span className="text-[10px] text-violet-300">{Math.round(evaluation.readiness * 100)}%</span>
          </div>
          <p className="mt-1 text-[10px] leading-relaxed text-slate-300">{evaluation.rationale}</p>
          <p className="mt-1 text-[10px] text-slate-500">{evaluation.mode} · {evaluation.provider} · {evaluation.evaluated_skill_count} skills reviewed</p>
          {evaluation.matched_skills.length > 0 && (
            <p className="mt-1 text-[10px] text-emerald-300">Supporting skills: {evaluation.matched_skills.map((skill) => skill.title).join(", ")}</p>
          )}
          {evaluation.missing_capabilities.length > 0 && (
            <p className="mt-1 text-[10px] text-amber-300">Gaps to investigate: {evaluation.missing_capabilities.join(", ")}</p>
          )}
          {evaluation.side_quests.length > 0 && (
            <div className="mt-3 rounded border border-amber-900/50 bg-amber-950/10 p-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-200">Side quests: expand the campaign</p>
              <p className="mt-1 text-[10px] leading-relaxed text-slate-400">
                These are source-addition tasks, not generated skills. Complete one by finding evidence, approving it in the planner, and ingesting it.
              </p>
              <ul className="mt-2 space-y-2">
                {evaluation.side_quests.map((quest) => (
                  <li key={quest.capability} className="rounded border border-amber-900/40 bg-slate-950/40 p-2">
                    <p className="text-[10px] font-semibold text-amber-100">{quest.title}</p>
                    <p className="mt-1 text-[10px] text-slate-400">{quest.reason}</p>
                    <p className="mt-1 text-[10px] text-slate-500">{quest.action}</p>
                    <p className="mt-2 break-words rounded bg-slate-950/70 p-1.5 text-[10px] text-slate-300">{quest.source_query}</p>
                    <button
                      type="button"
                      onClick={() => void copySourceQuery(quest)}
                      className={`mt-1 text-[10px] text-amber-200 underline underline-offset-2 hover:text-amber-100 ${FOCUS_RING}`}
                    >
                      {copiedCapability === quest.capability ? "Copied source-search prompt" : "Copy source-search prompt"}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SourceCoverage({ progress }: { progress: ProgressAnalytics | null }) {
  if (!progress || progress.source_coverage.length === 0) return null;
  const shown = progress.source_coverage.slice(0, 4);
  const remaining = progress.source_coverage.length - shown.length;
  return (
    <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 p-2.5" aria-label="Campaign source coverage">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Source → skill coverage</p>
        <span className="text-[10px] text-slate-500">{progress.started_skills} / {progress.total_skills} skills practiced</span>
      </div>
      <ul className="mt-2 space-y-1.5">
        {shown.map((source) => (
          <li key={source.document_id} className="flex items-baseline justify-between gap-2 text-[10px]">
            <span className="min-w-0 truncate text-slate-300">{source.filename}</span>
            <span className="shrink-0 text-slate-500">{source.skills_started}/{source.skills_total} skills · {source.attempts} attempts</span>
          </li>
        ))}
      </ul>
      {remaining > 0 && <p className="mt-1 text-[10px] text-slate-500">+ {remaining} more source{remaining === 1 ? "" : "s"} in Progress.</p>}
    </div>
  );
}

"use client";

import { useCallback, useState } from "react";

import { api } from "@/lib/api";
import type { CourseCost } from "@/lib/types";
import { CARD, FOCUS_RING } from "@/lib/ui";

/**
 * What this course cost to build.
 *
 * `GET /courses/{id}/cost` and its types were fully wired and called from
 * nowhere, so the `llm_calls` ledger -- the entire reason prompts are versioned
 * and hashed -- had no reader outside a test. Ingesting a real textbook is the
 * one action in the product that spends money, and it spent it invisibly.
 *
 * Grouped by (role, model, prompt_version) exactly as the ledger returns it,
 * which is what makes "did the v2 rubric get more expensive?" answerable at all.
 *
 * Collapsed and lazily fetched: this is a diagnostic, and it should not cost a
 * request on every course page load for the ~zero-dollar `LLM_PROVIDER=fake`
 * runs that are the default.
 */
export function CostPanel({ courseId }: { courseId: string }) {
  const [cost, setCost] = useState<CourseCost | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCost(await api.getCourseCost(courseId));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  return (
    <details
      className={CARD}
      onToggle={(event) => {
        if (event.currentTarget.open) void load();
      }}
    >
      <summary className={`cursor-pointer font-display text-sm font-semibold ${FOCUS_RING}`}>
        What this cost
      </summary>

      {loading && <p className="mt-2 text-xs text-slate-400">Reading the ledger…</p>}
      {error && (
        <p role="alert" className="mt-2 text-xs text-rose-400">
          {error}
        </p>
      )}

      {cost && !loading && (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <dt className="text-slate-400">Spend</dt>
              <dd className="text-slate-200">${cost.total_cost_usd.toFixed(4)}</dd>
            </div>
            <div>
              <dt className="text-slate-400">Budget</dt>
              <dd className={cost.budget_exceeded ? "text-node-decaying" : "text-slate-200"}>
                ${cost.budget_remaining_usd.toFixed(4)} left
              </dd>
            </div>
            <div>
              <dt className="text-slate-400">Calls</dt>
              <dd className="text-slate-200">
                {cost.total_calls}
                {cost.failed_calls > 0 && (
                  <span className="text-node-decaying"> · {cost.failed_calls} failed</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400">Tokens in</dt>
              <dd className="text-slate-200">{cost.total_input_tokens.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-slate-400">Tokens out</dt>
              <dd className="text-slate-200">{cost.total_output_tokens.toLocaleString()}</dd>
            </div>
          </dl>

          {cost.budget_exceeded && (
            <p role="alert" className="mt-3 text-[11px] text-node-decaying">
              Budget reached. New billable model and embedding calls are blocked; increase
              COURSE_LLM_BUDGET_USD before continuing this campaign.
            </p>
          )}

          {cost.by_role.length === 0 ? (
            <p className="mt-3 text-[11px] text-slate-400">
              No model calls recorded — this course was built with the fake provider.
            </p>
          ) : (
            <ul className="mt-3 space-y-1.5">
              {cost.by_role.map((row) => (
                <li key={`${row.role}-${row.model}-${row.prompt_version}`} className="text-[11px]">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-slate-300">{row.role}</span>
                    <span className="shrink-0 text-slate-200">${row.cost_usd.toFixed(4)}</span>
                  </div>
                  <p className="text-slate-400">
                    {row.model} · prompt {row.prompt_version} · {row.calls} call
                    {row.calls === 1 ? "" : "s"}
                    {row.failed > 0 && <span className="text-node-decaying"> · {row.failed} failed</span>}
                    {row.avg_latency_ms !== null && ` · ${Math.round(row.avg_latency_ms)}ms avg`}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </details>
  );
}

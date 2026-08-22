"use client";

import { useCallback, useState } from "react";

import { api, pollJob } from "@/lib/api";
import type { IngestJob, ProjectionStatus, ReindexScope, RejectionsPage } from "@/lib/types";
import { CARD, BUTTON_SECONDARY, FOCUS_RING } from "@/lib/ui";

const SCOPES: { scope: ReindexScope; label: string; hint: string }[] = [
  { scope: "graph", label: "Rebuild graph", hint: "Neo4j projection only" },
  { scope: "vectors", label: "Rebuild vectors", hint: "Chroma embeddings only" },
  { scope: "all", label: "Rebuild everything", hint: "Graph and vectors" },
];

function healthLabel(status: ProjectionStatus): { label: string; className: string } {
  if (!status.neo4j_reachable || !status.chroma_reachable) {
    return { label: "Unavailable", className: "text-rose-300" };
  }
  if (status.stale) {
    return { label: "Stale", className: "text-amber-300" };
  }
  return { label: "Healthy", className: "text-emerald-300" };
}

function rejectionLabel(reason: string): string {
  return reason.replaceAll("_", " ");
}

export function DiagnosticsPanel({ courseId }: { courseId: string }) {
  const [projection, setProjection] = useState<ProjectionStatus | null>(null);
  const [rejections, setRejections] = useState<RejectionsPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyScope, setBusyScope] = useState<ReindexScope | null>(null);
  const [job, setJob] = useState<IngestJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [health, rejected] = await Promise.all([
        api.getProjection(courseId),
        api.getRejections(courseId, 20),
      ]);
      setProjection(health);
      setRejections(rejected);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  async function rebuild(scope: ReindexScope) {
    setBusyScope(scope);
    setError(null);
    setJob(null);
    try {
      const accepted = await api.reindexCourse(courseId, scope);
      const finished = await pollJob(accepted.job_id, setJob);
      if (finished.state === "failed") {
        setError(finished.error ?? "The rebuild failed.");
      } else if (finished.state === "cancelled") {
        setError("The rebuild was cancelled.");
      } else {
        await load();
      }
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusyScope(null);
    }
  }

  return (
    <details
      className={CARD}
      onToggle={(event) => {
        if (event.currentTarget.open && !projection && !loading) void load();
      }}
    >
      <summary className={`cursor-pointer font-display text-sm font-semibold ${FOCUS_RING}`}>
        Diagnostics
      </summary>

      {loading && <p className="mt-2 text-xs text-slate-400">Checking derived stores…</p>}
      {error && (
        <div className="mt-2 flex items-center justify-between gap-2">
          <p role="alert" className="text-xs text-rose-400">{error}</p>
          {!busyScope && (
            <button
              type="button"
              onClick={() => void load()}
              className={`shrink-0 text-[11px] text-slate-400 underline underline-offset-2 hover:text-slate-200 ${FOCUS_RING}`}
            >
              Retry
            </button>
          )}
        </div>
      )}

      {projection && !loading && (
        <>
          <div className="mt-3 flex items-baseline justify-between gap-2">
            <span className={`text-sm font-semibold ${healthLabel(projection).className}`}>
              {healthLabel(projection).label}
            </span>
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading || busyScope !== null}
              className={`text-[11px] text-slate-400 underline underline-offset-2 hover:text-slate-200 disabled:opacity-50 ${FOCUS_RING}`}
            >
              Refresh
            </button>
          </div>

          <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <dt className="text-slate-400">Postgres graph</dt>
              <dd className="text-slate-200">v{projection.graph_version} · {projection.node_count} nodes</dd>
            </div>
            <div>
              <dt className="text-slate-400">Neo4j projection</dt>
              <dd className="text-slate-200">
                {projection.neo4j_reachable ? `v${projection.projected_version ?? "—"}` : "unreachable"}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400">Chunks</dt>
              <dd className="text-slate-200">{projection.chunk_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-slate-400">Chroma vectors</dt>
              <dd className="text-slate-200">
                {projection.chroma_reachable ? (projection.vector_count ?? 0).toLocaleString() : "unreachable"}
              </dd>
            </div>
          </dl>

          {projection.stale && (
            <p className="mt-3 text-[11px] text-amber-300">
              The derived graph does not match Postgres. Rebuild the graph projection below.
            </p>
          )}
          {projection.detail && <p className="mt-2 break-words text-[11px] text-slate-500">{projection.detail}</p>}

          <div className="mt-4">
            <p className="text-[11px] text-slate-400">Safe rebuilds</p>
            <p className="mt-1 text-[11px] text-slate-500">
              These rebuild derived stores only; they do not re-extract content or reset learner progress.
            </p>
            <div className="mt-2 space-y-1.5">
              {SCOPES.map(({ scope, label, hint }) => (
                <button
                  key={scope}
                  type="button"
                  onClick={() => void rebuild(scope)}
                  disabled={busyScope !== null}
                  className={`flex w-full items-baseline justify-between gap-2 ${BUTTON_SECONDARY} py-1.5 text-xs`}
                >
                  <span>{busyScope === scope ? "Rebuilding…" : label}</span>
                  <span className="text-[10px] font-normal text-slate-400">{hint}</span>
                </button>
              ))}
            </div>
            {job && busyScope !== null && (
              <p className="mt-2 text-[11px] text-slate-400">
                {job.state} · {job.percent}%
              </p>
            )}
          </div>

          {rejections && (
            <div className="mt-4">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-[11px] text-slate-400">Rejected edges</p>
                <span className="text-[11px] text-slate-300">{rejections.total.toLocaleString()} total</span>
              </div>
              {Object.keys(rejections.by_reason).length === 0 ? (
                <p className="mt-2 text-[11px] text-emerald-300">No rejected prerequisite edges.</p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {Object.entries(rejections.by_reason).map(([reason, count]) => (
                    <span key={reason} className="rounded-full border border-slate-700 px-2 py-1 text-[10px] text-slate-300">
                      {rejectionLabel(reason)} · {count}
                    </span>
                  ))}
                </div>
              )}
              {rejections.rows.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {rejections.rows.slice(0, 5).map((row) => (
                    <li key={row.id} className="border-l border-slate-700 pl-2 text-[11px]">
                      <p className="text-slate-300">
                        {row.prereq_slug} → {row.target_slug}
                      </p>
                      <p className="text-slate-500">
                        {rejectionLabel(row.reason)}
                        {row.confidence !== null && ` · ${Math.round(row.confidence * 100)}% confidence`}
                      </p>
                      {row.cycle_path.length > 0 && <p className="break-words text-slate-500">Cycle: {row.cycle_path.join(" → ")}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
    </details>
  );
}

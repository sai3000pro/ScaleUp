"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { dueLabel } from "@/lib/time";
import type { QuestBoard } from "@/lib/types";
import { FOCUS_RING } from "@/lib/ui";

export default function QuestsPage() {
  const [board, setBoard] = useState<QuestBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setBoard(await api.getQuests());
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

  // Partitioned, not filtered twice. Two `=== ` filters meant a quest whose
  // `reason` this build has never seen -- the field is a bare `str` on the wire
  // -- appeared in neither list, so the board silently dropped rows and still
  // counted their EXP in the header. Everything that is not a rescue is new
  // ground, which is true of any future reason as well.
  const overdue = board?.quests.filter((q) => q.reason === "overdue") ?? [];
  const frontier = board?.quests.filter((q) => q.reason !== "overdue") ?? [];

  return (
    <main id="main-content" tabIndex={-1} className="mx-auto max-w-3xl px-4 py-8 outline-none">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-xl font-semibold tracking-tight">Daily Quests</h1>
          <p className="mt-1 text-sm text-slate-400">
            Skills fade over time. Rescuing a decayed one pays up to 1.5× EXP.
          </p>
        </div>
        {board && (
          <div className="text-right">
            {board.streak_days > 0 && (
              <p className="text-sm font-semibold text-amber-300">{board.streak_days}-day streak</p>
            )}
            <p className="text-[11px] text-slate-400">{board.total_reward_exp} EXP on the board</p>
          </div>
        )}
      </div>

      {error && <p role="alert" className="mt-4 text-sm text-rose-400">{error}</p>}
      {loading && <p className="mt-8 text-sm text-slate-400">Loading…</p>}

      {board && board.quests.length === 0 && (
        <div className="mt-8 rounded-xl border border-dashed border-slate-800 p-10 text-center">
          <p className="text-sm text-slate-400">Nothing due.</p>
          <p className="mt-1 text-xs text-slate-400">
            Practise a few skills — they will start showing up here as they fade.
          </p>
        </div>
      )}

      {overdue.length > 0 && (
        <section className="mt-6">
          <h2 className="font-display text-xs font-semibold uppercase tracking-wide text-node-decaying">Fading</h2>
          <ul className="mt-2 space-y-2">
            {overdue.map((quest) => (
              <li key={quest.node_id}>
                <Link
                  href={`/courses/${quest.course_id}?node=${quest.node_id}`}
                  className={`flex items-center gap-3 rounded-xl border border-node-decaying/30 bg-node-decaying/5 p-3 transition hover:border-node-decaying/60 ${FOCUS_RING}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-display text-sm font-semibold text-slate-100">{quest.node_title}</p>
                    <p className="text-[11px] text-slate-400">
                      {quest.course_title} · {Math.floor(quest.overdue_days)}d overdue ·{" "}
                      {Math.round(quest.proficiency * 100)}% retained
                    </p>
                  </div>
                  <span className="shrink-0 rounded-md bg-node-decaying/15 px-2 py-1 text-xs font-semibold text-node-decaying">
                    +{quest.reward_exp} EXP
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {frontier.length > 0 && (
        <section className="mt-6">
          {/* Matches `available` in the tree -- a frontier quest IS a ready node. */}
          <h2 className="font-display text-xs font-semibold uppercase tracking-wide text-node-available">New ground</h2>
          <ul className="mt-2 space-y-2">
            {frontier.map((quest) => (
              <li key={quest.node_id}>
                <Link
                  href={`/courses/${quest.course_id}?node=${quest.node_id}`}
                  className={`flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/50 p-3 transition hover:border-slate-700 ${FOCUS_RING}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-slate-100">{quest.node_title}</p>
                    <p className="text-[11px] text-slate-400">
                      {quest.course_title} · {dueLabel(quest.due_at) ?? "never drilled"}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-md bg-node-available/15 px-2 py-1 text-xs font-semibold text-node-available">
                    +{quest.reward_exp} EXP
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

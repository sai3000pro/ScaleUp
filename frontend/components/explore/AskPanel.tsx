"use client";

import { useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { AskAnswer, DocumentSummary } from "@/lib/types";
import { sourceLabel } from "@/lib/source";
import { BUTTON_PRIMARY, CARD, FOCUS_RING, INPUT } from "@/lib/ui";
import { useGraphStore } from "@/stores/useGraphStore";

/**
 * Ask the course a question.
 *
 * The inverse of the drill loop, which only ever asks questions *at* the
 * learner. The answer is worth having only because of the citations, so they
 * are not a footnote here: each one is a button that selects and pans to the
 * node the claim came from, which is what turns "here is an answer" into "here
 * is where to go and learn it".
 */
export function AskPanel({
  courseId,
  documents,
}: {
  courseId: string;
  documents: DocumentSummary[];
}) {
  const focusNode = useGraphStore((state) => state.focusNode);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const wanted = question.trim();
    if (wanted.length < 3 || busy) return;

    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setBusy(true);
    setError(null);
    try {
      setAnswer(await api.askCourse(courseId, wanted, controller.signal));
    } catch (caught: unknown) {
      if (!controller.signal.aborted) {
        setError(caught instanceof ApiError ? caught.message : "Could not answer that.");
        setAnswer(null);
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  return (
    <div className={CARD}>
      <h2 className="font-display text-sm font-semibold">Ask this course</h2>
      <p className="mt-0.5 text-[11px] text-slate-400">
        Answered from your own uploaded material, with the nodes it came from.
      </p>

      <form onSubmit={submit} className="mt-3 space-y-2">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={2}
          maxLength={1000}
          placeholder="What should I practise before open chords?"
          aria-label="Your question"
          className={`${INPUT} resize-y`}
        />
        <button type="submit" disabled={busy || question.trim().length < 3} className={`${BUTTON_PRIMARY} w-full`}>
          {busy ? "Reading the material…" : "Ask"}
        </button>
      </form>

      {error && (
        <p role="alert" className="mt-3 text-xs text-rose-400">
          {error}
        </p>
      )}

      {answer && (
        <div className="mt-3 border-t border-slate-800 pt-3">
          <p className="whitespace-pre-line text-xs leading-relaxed text-slate-300">{answer.answer}</p>

          {answer.citations.length > 0 ? (
            <>
              <h3 className="mt-3 text-[11px] font-semibold text-slate-400">From these skills</h3>
              <ul className="mt-1 space-y-1.5">
                {answer.citations.map((citation) => (
                  <li key={`${citation.node_id}:${citation.chunk_id}`}>
                    <button
                      type="button"
                      onClick={() => focusNode(citation.node_id)}
                      className={`block w-full rounded-lg border border-slate-800 bg-slate-900/60 px-2.5 py-2 text-left transition hover:border-slate-700 hover:bg-slate-800/60 ${FOCUS_RING}`}
                    >
                      <span className="block text-[11px] font-semibold text-sky-300">{citation.node_title}</span>
                      <span className="mt-0.5 block text-[11px] italic leading-snug text-slate-400">
                        “{citation.quote}”
                      </span>
                      <span className="mt-0.5 block text-[10px] text-slate-500">
                        {sourceLabel(citation.source, documents)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            /* No citations is a real answer, and the two reasons for it are
               different problems: nothing was retrieved at all, or the model
               would not claim anything from what it was given. */
            <p className="mt-2 text-[11px] text-slate-500">
              {answer.retrieved === 0
                ? "Nothing was retrieved for this question — the course may not be indexed yet."
                : `No claim in this answer could be traced to the ${answer.retrieved} passages retrieved.`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

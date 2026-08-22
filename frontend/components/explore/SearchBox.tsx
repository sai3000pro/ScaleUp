"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { sourceLabel } from "@/lib/source";
import type { DocumentSummary, SearchHit } from "@/lib/types";
import { FOCUS_RING, INPUT } from "@/lib/ui";
import { useGraphStore } from "@/stores/useGraphStore";

/**
 * Search over the canvas.
 *
 * Two things happen on every result set, and they are different: the matched
 * orbs are lit and everything else recedes (`onMatches`), and the canvas pans
 * to the best hit. Highlighting without panning leaves the answer off screen on
 * a tree that does not fit in a viewport; panning without highlighting shows one
 * orb and no sense of how much else matched.
 *
 * Panning happens on an explicit choice -- Enter, or a click on a result -- not
 * on every keystroke. A canvas that flies somewhere new on each character is
 * unusable, and it fights the user while they are still typing.
 */
const DEBOUNCE_MS = 250;

interface Props {
  courseId: string;
  documents: DocumentSummary[];
  /** Node ids that matched, or `null` when no search is running. */
  onMatches: (nodeIds: Set<string> | null) => void;
}

export function SearchBox({ courseId, documents, onMatches }: Props) {
  const focusNode = useGraphStore((state) => state.focusNode);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [semantic, setSemantic] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  // One in flight at a time. Without this a slow request for "du" can land
  // after a fast one for "duality" and replace the better results with worse.
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const wanted = query.trim();
    if (!wanted) {
      inFlight.current?.abort();
      setHits(null);
      setError(null);
      onMatches(null);
      return;
    }

    const timer = setTimeout(() => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      api
        .searchCourse(courseId, wanted, controller.signal)
        .then((results) => {
          setHits(results.results);
          setSemantic(results.semantic);
          setError(null);
          setOpen(true);
          onMatches(new Set(results.results.map((hit) => hit.node_id)));
        })
        .catch((caught: unknown) => {
          // An abort is this component superseding itself, not a failure.
          if (controller.signal.aborted) return;
          setError(caught instanceof ApiError ? caught.message : "Search failed.");
          setHits([]);
          onMatches(new Set());
        });
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [query, courseId, onMatches]);

  const reveal = useCallback(
    (hit: SearchHit) => {
      focusNode(hit.node_id);
      setOpen(false);
    },
    [focusNode],
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setQuery("");
      setOpen(false);
    } else if (event.key === "Enter" && hits && hits.length > 0) {
      event.preventDefault();
      reveal(hits[0]);
    }
  };

  return (
    <div className="w-72 max-w-[calc(100vw-3rem)]">
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => setOpen(true)}
        placeholder="Search this course…"
        aria-label="Search this course"
        className={`${INPUT} bg-slate-900/95 shadow-lg shadow-slate-950/50 backdrop-blur`}
      />

      {open && hits !== null && (
        <div className="mt-1 max-h-[46vh] overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/95 shadow-xl shadow-slate-950/60 backdrop-blur">
          {error && <p className="px-3 py-2 text-xs text-rose-400">{error}</p>}

          {!error && hits.length === 0 && (
            <p className="px-3 py-2 text-xs text-slate-400">Nothing in this course matches “{query.trim()}”.</p>
          )}

          {/* Reported rather than hidden: title-only results and "the book does
              not mention it" look identical to a reader otherwise. */}
          {!error && !semantic && (
            <p className="border-b border-slate-800 px-3 py-1.5 text-[11px] text-node-decaying">
              Matching names only — the passage index is unavailable.
            </p>
          )}

          <ul>
            {hits.map((hit) => (
              <li key={hit.node_id}>
                <button
                  type="button"
                  onClick={() => reveal(hit)}
                  className={`block w-full px-3 py-2 text-left hover:bg-slate-800/70 ${FOCUS_RING}`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-xs font-semibold text-slate-100">{hit.title}</span>
                    <span className="shrink-0 text-[10px] text-slate-400">
                      {hit.assessable ? MATCH_LABEL[hit.match] ?? "match" : "section"}
                    </span>
                  </span>
                  <span className="mt-0.5 line-clamp-2 block text-[11px] leading-snug text-slate-400">
                    {hit.snippet}
                  </span>
                  {hit.source && (
                    <span className="mt-0.5 block text-[10px] text-slate-500">
                      {sourceLabel(hit.source, documents)}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * What each matcher means, in the user's terms. Looked up with a fallback
 * rather than indexed: `match` arrives as a bare string, and an unknown value
 * must degrade to a word rather than render "undefined".
 */
const MATCH_LABEL: Record<string, string> = {
  title: "name",
  content: "in the text",
  both: "name + text",
};

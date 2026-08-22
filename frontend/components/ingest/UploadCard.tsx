"use client";

import { useEffect, useRef, useState } from "react";

import { api, pollJob } from "@/lib/api";
import type { IngestJob } from "@/lib/types";
import { BUTTON_PRIMARY, CARD, FOCUS_RING, INPUT } from "@/lib/ui";

type SourceMode = "file" | "url";

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  parsing: "Reading the source",
  chunking: "Splitting into passages",
  embedding: "Indexing for retrieval",
  extracting: "Extracting the skill graph",
  reducing: "Merging concepts",
  finalizing: "Building the tree",
  succeeded: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function UploadCard({ courseId, onComplete }: { courseId: string; onComplete: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<SourceMode>("file");
  const [url, setUrl] = useState("");
  const [job, setJob] = useState<IngestJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // `pollJob` loops until the job reaches a terminal state. Without a stop
  // signal, navigating away mid-ingest left it hitting /api/jobs/{id} every
  // 1.5s for the life of the tab, calling setState on an unmounted component --
  // and the card's own copy invites you to leave the page.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  async function watch(jobId: string) {
    const finished = await pollJob(
      jobId,
      (next) => {
        if (alive.current) setJob(next);
      },
      () => !alive.current,
    );
    if (!alive.current) return;

    if (finished.state === "failed") {
      setError(finished.error ?? "Ingestion failed.");
    } else if (finished.state === "succeeded") {
      onComplete();
    }
  }

  async function accept(jobId: string, deduplicated: boolean) {
    if (deduplicated) {
      // Not an error: the source is already in. Kept separate so it is not
      // styled or announced as a failure.
      setNotice("That source content was already ingested — showing the original job.");
    }
    await watch(jobId);
  }

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setNotice(null);
    setJob(null);
    try {
      const accepted = await api.uploadDocument(courseId, file);
      await accept(accepted.job_id, accepted.deduplicated);
    } catch (caught) {
      if (alive.current) setError((caught as Error).message);
    } finally {
      if (alive.current) setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function retry() {
    if (!job || job.state !== "failed" || busy) return;

    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const accepted = await api.retryJob(job.id);
      await accept(accepted.job_id, accepted.deduplicated);
    } catch (caught) {
      if (alive.current) setError((caught as Error).message);
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function addUrl(event: React.FormEvent) {
    event.preventDefault();
    const target = url.trim();
    if (!target || busy) return;

    setBusy(true);
    setError(null);
    setNotice(null);
    setJob(null);
    try {
      // The API validates SSRF protections and fetches the page before it
      // returns 202. Once accepted, the rest is the same background pipeline as
      // a local file.
      const accepted = await api.ingestDocumentUrl(courseId, target);
      setUrl("");
      await accept(accepted.job_id, accepted.deduplicated);
    } catch (caught) {
      if (alive.current) setError((caught as Error).message);
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  const pct = job?.percent ?? 0;
  const detail = job?.stage_detail ?? {};

  return (
    <div className={CARD}>
      <h2 className="font-display text-sm font-semibold">Add a document</h2>
      <p id="uploadHelp" className="mt-1 text-xs text-slate-400">
        Add a PDF, HTML page, or a public web URL. The source is processed in the background after it is accepted.
      </p>

      <div className="mt-3 flex gap-1 rounded-lg bg-slate-950 p-1" role="tablist" aria-label="Source type">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "file"}
          onClick={() => setMode("file")}
          disabled={busy}
          className={`flex-1 rounded-md px-2 py-1.5 text-[11px] transition ${
            mode === "file" ? "bg-slate-800 text-slate-100" : "text-slate-400 hover:text-slate-200"
          } ${FOCUS_RING}`}
        >
          File
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "url"}
          onClick={() => setMode("url")}
          disabled={busy}
          className={`flex-1 rounded-md px-2 py-1.5 text-[11px] transition ${
            mode === "url" ? "bg-slate-800 text-slate-100" : "text-slate-400 hover:text-slate-200"
          } ${FOCUS_RING}`}
        >
          Web URL
        </button>
      </div>

      {mode === "file" ? (
        <>
          <label htmlFor="documentUpload" className="sr-only">
            Choose a PDF or HTML document to add to this course
          </label>
          <input
            id="documentUpload"
            aria-describedby="uploadHelp"
            ref={inputRef}
            type="file"
            accept=".pdf,.html,application/pdf,text/html"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
            className={`mt-3 block w-full rounded-md text-xs text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-sky-500 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-slate-950 hover:file:bg-sky-400 disabled:opacity-50 ${FOCUS_RING}`}
          />
        </>
      ) : (
        <form onSubmit={addUrl} className="mt-3 flex gap-2">
          <label htmlFor="documentUrl" className="sr-only">
            Public web page URL
          </label>
          <input
            id="documentUrl"
            type="url"
            required
            maxLength={2048}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://example.com/article"
            disabled={busy}
            className={`${INPUT} min-w-0 flex-1`}
          />
          <button type="submit" disabled={busy || !url.trim()} className={`${BUTTON_PRIMARY} shrink-0 px-3`}>
            {busy ? "Fetching…" : "Add"}
          </button>
        </form>
      )}

      {job && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>{STAGE_LABELS[job.state] ?? job.state}</span>
            <span>{pct}%</span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-sky-500 transition-[width] duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          {Object.keys(detail).length > 0 && (
            <p className="mt-2 text-[11px] text-slate-400">
              {[
                detail.pages && `${detail.pages} pages`,
                detail.chunks && `${detail.chunks} passages`,
                detail.concepts_merged && `${detail.concepts_merged} skills`,
                detail.edges_rejected ? `${detail.edges_rejected} edges rejected` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </div>
      )}

      {notice && <p className="mt-3 text-xs text-slate-300">{notice}</p>}
      {error && (
        <div role="alert" className="mt-3 flex items-start justify-between gap-3 text-xs text-rose-400">
          <p>{error}</p>
          {job?.state === "failed" && (
            <button
              type="button"
              onClick={() => void retry()}
              disabled={busy}
              className={`${BUTTON_PRIMARY} shrink-0 px-2.5 py-1 text-[11px]`}
            >
              {busy ? "Retrying…" : "Retry ingest"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

"use client";

import type { DocumentSummary } from "@/lib/types";
import { CARD } from "@/lib/ui";

function safeSourceUrl(sourceUri: string | null): string | null {
  if (!sourceUri) return null;
  try {
    const parsed = new URL(sourceUri);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function SourceList({ documents }: { documents: DocumentSummary[] }) {
  if (documents.length === 0) return null;

  return (
    <section className={CARD} aria-labelledby="course-sources-heading">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="course-sources-heading" className="font-display text-sm font-semibold">
          Sources
        </h2>
        <span className="text-[11px] text-slate-400">
          {documents.length} {documents.length === 1 ? "document" : "documents"}
        </span>
      </div>
      <ul className="mt-2 space-y-2">
        {documents.map((document) => {
          const sourceUrl = safeSourceUrl(document.source_uri);
          return (
            <li key={document.id} className="rounded-lg border border-slate-800 bg-slate-950/60 px-2.5 py-2">
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 truncate text-xs font-medium text-slate-200" title={document.filename}>
                  {document.filename}
                </p>
                <span className="shrink-0 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
                  {document.source_type}
                </span>
              </div>
              <p className="mt-1 text-[10px] text-slate-500">
                {document.source_type === "html"
                  ? "Web page"
                  : document.page_count === null
                    ? "Document"
                    : `${document.page_count} pages`}{" "}· {document.chunk_count}{" "}
                {document.chunk_count === 1 ? "passage" : "passages"}
              </p>
              {sourceUrl && (
                <a
                  href={sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-block text-[10px] text-sky-300 underline underline-offset-2 hover:text-sky-200"
                >
                  Open source ↗
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

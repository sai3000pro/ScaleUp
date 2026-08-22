import type { DocumentSummary, SourceRef } from "@/lib/types";

/** Resolve a chunk's document id to the filename the learner knows. */
export function documentName(documentId: string, documents: DocumentSummary[]): string {
  return documents.find((document) => document.id === documentId)?.filename ?? "Unknown source";
}

/** Keep page and section context compact enough for a citation row. */
export function sourceLabel(source: SourceRef, documents: DocumentSummary[]): string {
  const location = source.section_path ?? `p. ${source.page_start + 1}`;
  return `${documentName(source.document_id, documents)} · ${location} · p. ${source.page_start + 1}`;
}

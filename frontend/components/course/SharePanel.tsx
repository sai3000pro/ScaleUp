"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, CARD, FOCUS_RING } from "@/lib/ui";
import type { ShareStatus } from "@/lib/types";

/**
 * Share / revoke the course's copy-to-account link.
 *
 * The raw link is shown exactly once, at creation -- the backend stores only
 * its hash, so this panel never re-fetches an old link. "Regenerate" is
 * therefore how you recover a lost link, and it silently invalidates the old
 * one, exactly like rotating a password.
 */
export function SharePanel({ courseId, shareable }: { courseId: string; shareable: boolean }) {
  const [status, setStatus] = useState<ShareStatus | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getShareStatus(courseId)
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch(() => {
        // A failed status read must not take the panel down; it just shows
        // nothing until the learner acts.
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const createLink = useCallback(async () => {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const created = await api.shareCourse(courseId);
      setLink(created.url);
      setStatus({ course_id: created.course_id, shared: true, created_at: created.created_at });
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }, [courseId]);

  const revoke = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.revokeShare(courseId);
      setLink(null);
      setStatus({ course_id: courseId, shared: false, created_at: null });
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }, [courseId]);

  return (
    <div className={CARD}>
      <h2 className="font-display text-sm font-semibold">Share this course</h2>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
        Anyone with the link can preview the skill tree and copy it to their own
        account. Your progress never travels with a copy.
      </p>

      {!shareable && (
        <p className="mt-3 rounded-lg border border-amber-900/50 bg-amber-950/10 p-2.5 text-[11px] text-amber-200">
          Sharing unlocks once the course is ready.
        </p>
      )}

      {shareable && !link && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void createLink()}
          className={`mt-3 w-full ${BUTTON_PRIMARY}`}
        >
          {busy ? "Working…" : status?.shared ? "Regenerate link" : "Create share link"}
        </button>
      )}

      {shareable && link && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-2">
            <input
              readOnly
              value={link}
              onFocus={(event) => event.target.select()}
              aria-label="Share link"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-300"
            />
            <button
              type="button"
              className={`shrink-0 rounded-md px-2.5 py-1.5 text-[11px] font-semibold ${BUTTON_SECONDARY}`}
              onClick={() => {
                void navigator.clipboard.writeText(link).then(() => {
                  setCopied(true);
                });
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void revoke()}
              className={`text-[11px] text-rose-300 hover:text-rose-200 ${FOCUS_RING}`}
            >
              Revoke link
            </button>
            <span className="text-[10px] text-slate-500">
              {copied ? "Link copied — send it to anyone." : "Shown once; regenerate to get a new one."}
            </span>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-[11px] text-rose-400">
          {error}
        </p>
      )}
    </div>
  );
}

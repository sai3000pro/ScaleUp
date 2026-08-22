"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { BUTTON_PRIMARY, CARD, FOCUS_RING } from "@/lib/ui";
import type { Course, SharePreview } from "@/lib/types";
import { useAuthStore } from "@/stores/useAuthStore";

/**
 * The public face of a share link.
 *
 * No auth required to look: the token IS the credential, and the visitor may
 * not have an account yet. Copying requires one -- the copy lands in the
 * copier's account, and a 401 is turned into a sign-in prompt that returns
 * here via /login?next=/share/{token}.
 */
export default function SharePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const user = useAuthStore((state) => state.user);

  const [preview, setPreview] = useState<SharePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copiedCourse, setCopiedCourse] = useState<Course | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSharePreview(token)
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch((caught) => {
        if (!cancelled) setError((caught as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const copy = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const course = await api.copySharedCourse(token);
      setCopiedCourse(course);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        window.location.href = `/login?next=/share/${encodeURIComponent(token)}`;
        return;
      }
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }, [token]);

  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-4 py-10 outline-none"
    >
      <Link href="/" className={`text-xs text-slate-400 hover:text-slate-200 ${FOCUS_RING}`}>
        ← Learn-Any-Instrument
      </Link>

      {error && (
        <div className={`mt-6 ${CARD}`}>
          <h1 className="font-display text-lg font-semibold">This share link is no longer valid</h1>
          <p className="mt-2 text-sm text-slate-400">
            {error} The course owner may have revoked it, or the link may be mistyped.
          </p>
        </div>
      )}

      {preview && (
        <div className={`mt-6 ${CARD}`}>
          <h1 className="font-display text-xl font-semibold tracking-tight">{preview.title}</h1>
          {preview.description && <p className="mt-2 text-sm leading-relaxed text-slate-400">{preview.description}</p>}
          <p className="mt-2 text-xs text-slate-500">
            Shared by {preview.shared_by} · {preview.node_count} skills · {preview.edge_count} prerequisite links
          </p>

          <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-400">
            Copying takes the whole course into your account — the skill tree,
            the source material, and the question bank. Progress is never
            copied: you start this tree fresh and earn it yourself.
          </div>

          {copiedCourse ? (
            <div className="mt-4">
              <p className="text-sm text-emerald-300">Copied to your account.</p>
              <Link
                href={`/courses/${copiedCourse.id}`}
                className={`mt-2 inline-block w-full text-center ${BUTTON_PRIMARY}`}
              >
                Open your copy
              </Link>
            </div>
          ) : (
            <button type="button" disabled={busy} onClick={() => void copy()} className={`mt-4 w-full ${BUTTON_PRIMARY}`}>
              {busy ? "Copying…" : user ? "Copy to my account" : "Sign in and copy to my account"}
            </button>
          )}
        </div>
      )}

      {!preview && !error && (
        <div className={`mt-6 ${CARD}`}>
          <p className="text-sm text-slate-400">Loading the course…</p>
        </div>
      )}
    </main>
  );
}

"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { api } from "@/lib/api";
import { BUTTON_PRIMARY, INPUT, NAV_LINK } from "@/lib/ui";
import { useAuthStore } from "@/stores/useAuthStore";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center px-4 text-sm text-slate-400">Loading…</main>}>
      <ResetPasswordView />
    </Suspense>
  );
}

function ResetPasswordView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(token ? null : "This reset link is missing its token.");
  const [busy, setBusy] = useState(false);
  const acceptToken = useAuthStore((state) => state.acceptToken);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.consumePasswordReset(token, password);
      // The API returns a fresh JWT, so the learner is signed in immediately.
      acceptToken(result);
      router.replace("/courses");
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main-content" tabIndex={-1} className="flex min-h-screen items-center justify-center px-4 outline-none">
      <div className="w-full max-w-sm">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Choose a new password</h1>
        <p className="mt-2 text-sm text-slate-400">This link can be used once and expires shortly.</p>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <label htmlFor="password" className="sr-only">New password</label>
          <input
            id="password"
            className={INPUT}
            type="password"
            autoComplete="new-password"
            placeholder="New password (8+ characters)"
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <label htmlFor="confirmation" className="sr-only">Confirm new password</label>
          <input
            id="confirmation"
            className={INPUT}
            type="password"
            autoComplete="new-password"
            placeholder="Confirm new password"
            minLength={8}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            required
          />
          {error && <p role="alert" className="text-xs text-rose-400">{error}</p>}
          <button type="submit" disabled={busy || !token} className={`w-full ${BUTTON_PRIMARY}`}>
            {busy ? "Updating…" : "Set new password"}
          </button>
        </form>
        <Link href="/login" className={`mt-4 inline-block text-xs ${NAV_LINK}`}>
          Back to sign in
        </Link>
      </div>
    </main>
  );
}

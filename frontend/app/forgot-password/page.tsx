"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api";
import { BUTTON_PRIMARY, INPUT, NAV_LINK } from "@/lib/ui";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.requestPasswordReset(email);
      setMessage(result.message);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main-content" tabIndex={-1} className="flex min-h-screen items-center justify-center px-4 outline-none">
      <div className="w-full max-w-sm">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Recover your account</h1>
        <p className="mt-2 text-sm text-slate-400">
          Enter your email and we&apos;ll send a one-time password reset link if an account exists.
        </p>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <label htmlFor="email" className="sr-only">Email address</label>
          <input
            id="email"
            className={INPUT}
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          {message && <p role="status" className="text-xs text-emerald-400">{message}</p>}
          {error && <p role="alert" className="text-xs text-rose-400">{error}</p>}
          <button type="submit" disabled={busy} className={`w-full ${BUTTON_PRIMARY}`}>
            {busy ? "Sending…" : "Send reset link"}
          </button>
        </form>
        <Link href="/login" className={`mt-4 inline-block text-xs ${NAV_LINK}`}>
          Back to sign in
        </Link>
      </div>
    </main>
  );
}

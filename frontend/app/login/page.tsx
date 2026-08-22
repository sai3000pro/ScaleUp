"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { BUTTON_PRIMARY, INPUT, NAV_LINK } from "@/lib/ui";
import { useAuthStore } from "@/stores/useAuthStore";

// @spec ACCESS-OAUTH-002
export default function LoginPage() {
  const router = useRouter();
  const { user, error, login, register, devLogin } = useAuthStore();
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [redirectTo, setRedirectTo] = useState<string | null>(null);

  // A share page sends the learner here to sign in before copying; bring them
  // back to where they were instead of dumping them on /courses. Same-origin
  // paths only -- client-side router.replace, so this is a convenience, not a
  // security boundary.
  useEffect(() => {
    const next = new URLSearchParams(window.location.search).get("next");
    if (next && next.startsWith("/") && !next.startsWith("//")) {
      setRedirectTo(next);
    }
  }, []);

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("dev@example.com");
  const [password, setPassword] = useState("devpassword123");
  const [displayName, setDisplayName] = useState("Learner");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) router.replace(redirectTo ?? "/courses");
  }, [user, router, redirectTo]);

  useEffect(() => {
    const errorCode = new URLSearchParams(window.location.search).get("error");
    if (errorCode === "google_sign_in_failed") {
      setOauthError("Google sign-in could not be completed. Please try again.");
    }
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password, displayName);
      }
      router.replace(redirectTo ?? (mode === "register" ? "/character" : "/courses"));
    } catch {
      // The store already holds the message; keep the form mounted.
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    // Clearing the seeded dev credentials matters: leaving them in place means
    // "Create account" immediately fails with "email already registered".
    const next = mode === "login" ? "register" : "login";
    setMode(next);
    setEmail(next === "register" ? "" : "dev@example.com");
    setPassword(next === "register" ? "" : "devpassword123");
  }

  async function useDevAccount() {
    setBusy(true);
    try {
      await devLogin();
      router.replace(redirectTo ?? "/courses");
    } catch {
      // Store holds the explanation.
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main-content" tabIndex={-1} className="flex min-h-screen items-center justify-center px-4 outline-none">
      <div className="w-full max-w-sm">
        <h1 className="font-display text-2xl font-semibold tracking-tight">
          Learn Any<span className="text-sky-400">Instrument</span>
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Pick a skill, play it, and get coached on what you actually played.
        </p>

        <button
          type="button"
          className="mt-6 w-full rounded-lg border border-slate-700 bg-white px-4 py-2.5 text-sm font-semibold text-slate-100 transition hover:bg-slate-800 disabled:opacity-50"
          onClick={() => {
            window.location.href = api.googleStartUrl();
          }}
          disabled={busy}
        >
          Continue with Google
        </button>

        <div className="my-4 flex items-center gap-3 text-[11px] uppercase tracking-[0.18em] text-slate-600">
          <span className="h-px flex-1 bg-slate-800" />
          <span>or</span>
          <span className="h-px flex-1 bg-slate-800" />
        </div>

        <form onSubmit={submit} className="space-y-3">
          {mode === "register" && (
            <div>
              <label htmlFor="displayName" className="sr-only">
                Display name
              </label>
              <input
                id="displayName"
                className={INPUT}
                placeholder="Display name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
            </div>
          )}
          <div>
            <label htmlFor="email" className="sr-only">
              Email address
            </label>
            <input
              id="email"
              className={INPUT}
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="sr-only">
              Password
            </label>
            <input
              id="password"
              className={INPUT}
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder="Password (8+ characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>

          {(error || oauthError) && (
            <p role="alert" className="text-xs text-rose-400">
              {error || oauthError}
            </p>
          )}

          <button type="submit" disabled={busy} className={`w-full ${BUTTON_PRIMARY}`}>
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
          <button type="button" className={NAV_LINK} onClick={switchMode}>
            {mode === "login" ? "Need an account?" : "Already have one?"}
          </button>
          <div className="flex items-center gap-3">
            {mode === "login" && (
              <a className={NAV_LINK} href="/forgot-password">
                Forgot password?
              </a>
            )}
            <button type="button" className={NAV_LINK} onClick={useDevAccount} disabled={busy}>
              Use the seeded dev account
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

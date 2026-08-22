"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { NAV_LINK } from "@/lib/ui";
import { useAuthStore } from "@/stores/useAuthStore";

export default function AuthCallbackPage() {
  const router = useRouter();
  const exchangeGoogleCode = useAuthStore((state) => state.exchangeGoogleCode);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("code");
    if (!code) {
      setError("The Google sign-in response did not include a code.");
      return;
    }

    let active = true;
    void exchangeGoogleCode(code)
      .then(() => {
        if (active) router.replace("/courses");
      })
      .catch(() => {
        if (active) setError("Google sign-in could not be completed. Please try again.");
      });

    return () => {
      active = false;
    };
  }, [exchangeGoogleCode, router]);

  return (
    <main id="main-content" tabIndex={-1} className="flex min-h-screen items-center justify-center px-4 outline-none">
      <div className="w-full max-w-sm text-center">
        {error ? (
          <>
            <h1 className="font-display text-2xl font-semibold tracking-tight">Sign-in failed</h1>
            <p role="alert" className="mt-2 text-sm text-rose-400">{error}</p>
            <Link href="/login" className={`mt-5 inline-block text-xs ${NAV_LINK}`}>
              Back to sign in
            </Link>
          </>
        ) : (
          <p className="text-sm text-slate-400">Completing Google sign-in…</p>
        )}
      </div>
    </main>
  );
}

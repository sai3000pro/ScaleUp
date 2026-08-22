"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthStore } from "@/stores/useAuthStore";

// The landing page is the public argument for the product, so it must resolve
// for someone with no account -- and must not be exchanged for another
// destination once they have one (`LAND-ROUTE-001`, `LAND-ROUTE-002`).
const PUBLIC_PATHS = new Set(["/", "/login", "/forgot-password", "/reset-password", "/auth/callback"]);
// Share links must resolve for someone without an account -- that is the whole
// funnel -- so every /share/{token} page is public too.
const PUBLIC_PREFIXES = ["/share/"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname) || PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

/**
 * Hydrates the session once, then keeps unauthenticated users on /login.
 *
 * Client-side only, deliberately: the API is the real authority and every
 * endpoint checks the bearer token itself. This is a navigation convenience,
 * not a security boundary.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((state) => state.status);
  const hydrated = useAuthStore((state) => state.hydrated);
  const user = useAuthStore((state) => state.user);
  const hydrate = useAuthStore((state) => state.hydrate);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "idle") void hydrate();
  }, [status, hydrate]);

  useEffect(() => {
    if (hydrated && !user && !isPublicPath(pathname)) {
      router.replace("/login");
    }
  }, [hydrated, user, pathname, router]);

  // Gate on the FIRST session check only. Gating on `status` would blank the
  // screen during a login and unmount the form that is submitting it.
  //
  // A public page is never gated at all. The landing page is a document about
  // the product addressed to someone who has no session, so making it wait on a
  // session check spends a round-trip to learn something it does not use -- and
  // leaves a stranger looking at "Loading..." for as long as the API takes, or
  // forever if the API is down (`LAND-ROUTE-001`). Hydration still runs; the
  // page just does not wait for it.
  if (!hydrated && !isPublicPath(pathname)) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}

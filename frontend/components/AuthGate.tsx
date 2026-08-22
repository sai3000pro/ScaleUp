"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthStore } from "@/stores/useAuthStore";

const PUBLIC_PATHS = new Set(["/login", "/forgot-password", "/reset-password", "/auth/callback"]);
// Share links must resolve for someone without an account -- that is the whole
// funnel -- so every /share/{token} page is public too.
const PUBLIC_PREFIXES = ["/share/"];

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
    const isPublic = PUBLIC_PATHS.has(pathname) || PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix));
    if (hydrated && !user && !isPublic) {
      router.replace("/login");
    }
  }, [hydrated, user, pathname, router]);

  // Gate on the FIRST session check only. Gating on `status` would blank the
  // screen during a login and unmount the form that is submitting it.
  if (!hydrated) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}

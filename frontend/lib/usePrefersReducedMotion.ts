"use client";

/**
 * Whether the viewer has asked the system for less motion.
 *
 * Shared rather than private to a canvas: every animated surface owes the same
 * answer, and a component that reimplements the query is one that will forget to
 * listen for the setting changing mid-session.
 *
 * Starts `false` and corrects on mount. Server-rendered HTML cannot know the
 * preference, so the alternative is a hydration mismatch on every page that
 * animates anything.
 *
 * @spec UI-A11Y-004
 */

import { useEffect, useState } from "react";

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

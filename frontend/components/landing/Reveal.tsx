"use client";

/**
 * Moves an element from a displaced state to the state the markup already has.
 *
 * The direction matters and is the segment's motion contract: the final state
 * is what the markup declares, and script animates *from* somewhere else. So a
 * reader with no JavaScript gets the finished page, a reader who has asked for
 * reduced motion gets the finished page, and a reader with neither restriction
 * gets the finished page a beat later. Animating *to* a state only script knows
 * would make the first two readers see a blank column.
 *
 * `IntersectionObserver` rather than a scroll library: this page has no pinning,
 * no scrub and no horizontal travel, so a scroll-timeline dependency would buy
 * nothing and cost the reader a bundle.
 *
 * @spec LAND-MOTION-001, LAND-MOTION-002, LAND-MOTION-003, LAND-MOTION-004
 */
import { useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

export interface RevealProps {
  children: React.ReactNode;
  /** Staggers a group. Milliseconds. */
  delay?: number;
  className?: string;
  as?: "div" | "li" | "section" | "p";
}

export function Reveal({ children, delay = 0, className = "", as = "div" }: RevealProps) {
  const reduced = usePrefersReducedMotion();
  const ref = useRef<HTMLElement | null>(null);
  /**
   * Starts revealed, and is only ever un-revealed by the client once it knows
   * both that motion is allowed and that the element is still below the fold.
   * That ordering is what keeps the no-JS render complete.
   */
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (reduced || !node || typeof IntersectionObserver === "undefined") return;

    // Already on screen at mount: revealing it would be a flash, not an entrance.
    const box = node.getBoundingClientRect();
    if (box.top < window.innerHeight * 0.85) return;

    setHidden(true);
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setHidden(false);
            // Once revealed, stay revealed: an element that re-animates every
            // time it is scrolled past reads as a page that will not settle.
            observer.disconnect();
          }
        }
      },
      { rootMargin: "0px 0px -12% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [reduced]);

  const Tag = as;
  return (
    <Tag
      ref={ref as React.Ref<never>}
      className={`reveal ${className}`}
      data-hidden={hidden ? "" : undefined}
      style={delay ? ({ "--reveal-delay": `${delay}ms` } as React.CSSProperties) : undefined}
    >
      {children}
    </Tag>
  );
}

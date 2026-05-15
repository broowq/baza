"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/**
 * Page-transition overlay — mint band sweeps across the screen when the
 * route changes, then dissolves. Same flavour Dogstudio uses between
 * portfolio pages.
 *
 * Implementation:
 *   We watch usePathname. On every change:
 *   1. Mount the overlay with .swiping class → triggers an enter keyframe
 *      that scales the band from left:-110% to left:0 in 0.55s.
 *   2. Wait one frame, then add .leaving → reverse keyframe slides it out
 *      to the right at left:110%.
 *   3. Unmount on animationend so we don't leak listeners.
 *
 * Note: this is page-transition for client-side navigations. The first
 * full page load already has its own SmoothScroll + Reveal sequence, so
 * we deliberately do NOT play the sweep on initial mount (the `mounted`
 * gate handles that).
 */
export function PageTransition() {
  const pathname = usePathname();
  const [phase, setPhase] = useState<"idle" | "enter" | "leave">("idle");
  const mountedRef = useRef(false);

  useEffect(() => {
    // Skip the very first render — we don't want the sweep on hard reload.
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    if (typeof window === "undefined") return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;

    setPhase("enter");
    // Sweep in for 550ms, then start the leave animation.
    const t1 = window.setTimeout(() => setPhase("leave"), 580);
    const t2 = window.setTimeout(() => setPhase("idle"), 580 + 600);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [pathname]);

  if (phase === "idle") return null;

  return (
    <div
      className={`page-transition ${phase === "enter" ? "swiping" : "leaving"}`}
      aria-hidden
    />
  );
}

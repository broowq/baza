"use client";

import { useEffect } from "react";
import Lenis from "lenis";

/**
 * Page-wide buttery-smooth scroll, plus a scroll-progress signal exposed
 * via `--scroll-progress` on the root element. Mirrors the feel of
 * the-goonies / dogstudio / wearemotto without dragging GSAP into the bundle.
 *
 * Why not just `scroll-behavior: smooth`?
 *   - CSS smooth scroll only kicks in for anchor jumps, not actual wheel/track
 *     events. Lenis intercepts wheel + touch + keyboard and tweens the
 *     viewport itself, giving the same "magazine" lag the references rely on.
 *
 * Why not react-lenis?
 *   - It re-renders on every scroll tick. Vanilla Lenis with a raf loop is
 *     ~2KB and zero React churn. We expose progress via a CSS variable so
 *     components animate via `animation-timeline` / pure CSS, no rerenders.
 *
 * Disabled when the user has `prefers-reduced-motion: reduce` set —
 * smooth scroll can trigger motion sickness for some users.
 */
export function SmoothScrollProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;

    // Lenis defaults tuned to match the cadence of the reference sites —
    // duration 1.2s with a heavy ease-out so flicks feel weighty but stop
    // predictably; smoothness=1 keeps direct touch tracking intact.
    const lenis = new Lenis({
      duration: 1.15,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), // exp-out
      orientation: "vertical",
      smoothWheel: true,
      syncTouch: false, // native momentum on iOS feels better than virt
      wheelMultiplier: 1.0,
      touchMultiplier: 1.4,
    });

    let rafId = 0;
    const raf = (time: number) => {
      lenis.raf(time);
      rafId = requestAnimationFrame(raf);
    };
    rafId = requestAnimationFrame(raf);

    // Surface scroll progress as a CSS custom property — lets us drive
    // any number of scroll-bound animations (scroll-progress bar, parallax,
    // hero scale-down) from pure CSS without each component subscribing.
    const root = document.documentElement;
    const onScroll = ({
      scroll,
      limit,
    }: {
      scroll: number;
      limit: number;
    }) => {
      const progress = limit > 0 ? scroll / limit : 0;
      root.style.setProperty("--scroll-progress", progress.toFixed(4));
      // Velocity-driven flash effect — components can hook on this if needed.
      root.style.setProperty("--scroll-velocity", lenis.velocity.toFixed(2));
    };
    lenis.on("scroll", onScroll);

    return () => {
      lenis.off("scroll", onScroll);
      cancelAnimationFrame(rafId);
      lenis.destroy();
    };
  }, []);

  return <>{children}</>;
}

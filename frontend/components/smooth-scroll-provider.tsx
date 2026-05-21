"use client";

import { useEffect } from "react";

/**
 * Scroll-progress signal only — native scrolling, NO smoothing.
 *
 * We previously ran Lenis here for "magazine" smooth scroll, but it was
 * removed by request: the momentum/lag felt off. Scrolling is now the
 * browser's native behaviour.
 *
 * What stays: we still publish `--scroll-progress` (0..1) on <html> from a
 * passive native-scroll listener, so the top hairline progress bar and any
 * scroll-bound CSS keep working without re-introducing the smoothing.
 */
export function SmoothScrollProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    if (typeof window === "undefined") return;

    const root = document.documentElement;
    let ticking = false;

    const update = () => {
      const scroll = window.scrollY || root.scrollTop || 0;
      const limit = (root.scrollHeight - window.innerHeight) || 0;
      const progress = limit > 0 ? scroll / limit : 0;
      root.style.setProperty("--scroll-progress", progress.toFixed(4));
      ticking = false;
    };

    const onScroll = () => {
      // rAF-throttle so we touch the DOM at most once per frame.
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    };

    update(); // initial value
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });

    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  return <>{children}</>;
}

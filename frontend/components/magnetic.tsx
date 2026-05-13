"use client";

import { useEffect, useRef } from "react";

/**
 * Wraps a button (or any element) so it gently tracks the cursor when the
 * pointer enters its bounding box. Bounded magnet — translation maxes out
 * at `strength` px regardless of cursor distance, so the element doesn't
 * fly off-screen on edge swipes.
 *
 * Used on hero CTAs to mirror the references — gives weight to clicks
 * without resorting to GSAP. Pure transform, no layout reflow, GPU-friendly.
 *
 * Disabled on touch devices (pointermove on tap creates janky jumps) and
 * when prefers-reduced-motion.
 */
export function Magnetic({
  children,
  strength = 18,
  className = "",
}: {
  children: React.ReactNode;
  strength?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof window === "undefined") return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const touch = window.matchMedia("(pointer: coarse)").matches;
    if (reduce || touch) return;

    let frame = 0;
    let targetX = 0;
    let targetY = 0;
    let currentX = 0;
    let currentY = 0;

    const lerp = (a: number, b: number, n: number) => a + (b - a) * n;

    const animate = () => {
      currentX = lerp(currentX, targetX, 0.18);
      currentY = lerp(currentY, targetY, 0.18);
      el.style.transform = `translate3d(${currentX.toFixed(2)}px, ${currentY.toFixed(2)}px, 0)`;
      if (Math.abs(currentX - targetX) > 0.05 || Math.abs(currentY - targetY) > 0.05) {
        frame = requestAnimationFrame(animate);
      }
    };

    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      // Normalise to [-1..1] relative to center, then clamp to ±strength px.
      const dx = (e.clientX - cx) / (rect.width / 2);
      const dy = (e.clientY - cy) / (rect.height / 2);
      targetX = Math.max(-1, Math.min(1, dx)) * strength;
      targetY = Math.max(-1, Math.min(1, dy)) * strength;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(animate);
    };

    const onLeave = () => {
      targetX = 0;
      targetY = 0;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(animate);
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      cancelAnimationFrame(frame);
    };
  }, [strength]);

  return (
    <div ref={ref} className={`magnetic ${className}`} style={{ willChange: "transform" }}>
      {children}
    </div>
  );
}

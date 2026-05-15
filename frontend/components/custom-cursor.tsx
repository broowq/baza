"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Custom cursor in the style of dogstudio.co / the-goonies.webflow.io.
 *
 * Two layers:
 *   • CORE — a small mint-glow dot that tracks the mouse 1:1 (no lag).
 *   • TRAILER — a larger soft circle that lerps toward the mouse with
 *               a small lag, so the cursor feels weighted.
 *
 * Interactions:
 *   • Hover on <a>, <button>, [role=button], [data-cursor=focus] →
 *     trailer scales up 2.4× and shows the underlying element through it.
 *   • [data-cursor=hide] hides the cursor entirely (useful over text inputs
 *     where the native I-beam should be visible).
 *   • [data-cursor-label="..."] paints a small text label inside the trailer
 *     so we can do "View case / Open / Replay" badges like the references.
 *   • mousedown → trailer scales down 0.85× for a tap feel.
 *
 * Hidden on:
 *   • Touch devices (pointer: coarse) — would just block taps.
 *   • prefers-reduced-motion — native cursor is fine.
 * In both cases we don't even mount, native cursor remains.
 */
export function CustomCursor() {
  const [enabled, setEnabled] = useState(false);
  const [label, setLabel] = useState<string>("");
  const [focused, setFocused] = useState(false);
  const [pressed, setPressed] = useState(false);

  const coreRef = useRef<HTMLDivElement | null>(null);
  const trailerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const touch = window.matchMedia("(pointer: coarse)").matches;
    if (reduce || touch) return;
    setEnabled(true);

    let trailerX = window.innerWidth / 2;
    let trailerY = window.innerHeight / 2;
    let targetX = trailerX;
    let targetY = trailerY;
    let raf = 0;

    const lerp = (a: number, b: number, n: number) => a + (b - a) * n;

    const tick = () => {
      // Trailer lags behind the core with 0.18 dampening — same constant
      // we use for magnetic buttons so the feel is consistent.
      trailerX = lerp(trailerX, targetX, 0.18);
      trailerY = lerp(trailerY, targetY, 0.18);
      if (trailerRef.current) {
        trailerRef.current.style.transform = `translate3d(${trailerX - 22}px, ${trailerY - 22}px, 0)`;
      }
      raf = requestAnimationFrame(tick);
    };

    const onMove = (e: PointerEvent) => {
      targetX = e.clientX;
      targetY = e.clientY;
      // Core dot — direct, no lag.
      if (coreRef.current) {
        coreRef.current.style.transform = `translate3d(${e.clientX - 3}px, ${e.clientY - 3}px, 0)`;
      }
      // Hover detection — read data-* attrs off the element under the
      // cursor. Walks up the tree so children inside a magnet button
      // also trigger focus.
      const target = e.target as HTMLElement | null;
      if (!target) return;
      const focusEl = target.closest("a, button, [role='button'], [data-cursor='focus']");
      const hideEl  = target.closest("input, textarea, [contenteditable='true'], [data-cursor='hide']");
      const labelEl = target.closest("[data-cursor-label]") as HTMLElement | null;
      setFocused(Boolean(focusEl));
      // Toggle a body class so a sibling cursor-hide CSS rule can null the
      // pointer over text inputs without us touching .style.
      document.body.classList.toggle("cursor-hide", Boolean(hideEl));
      const lbl = labelEl?.dataset.cursorLabel ?? "";
      setLabel((cur) => (cur === lbl ? cur : lbl));
    };

    const onDown = () => setPressed(true);
    const onUp = () => setPressed(false);

    raf = requestAnimationFrame(tick);
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerdown", onDown, { passive: true });
    window.addEventListener("pointerup", onUp, { passive: true });

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointerup", onUp);
      document.body.classList.remove("cursor-hide");
    };
  }, []);

  if (!enabled) return null;

  const scale = (pressed ? 0.85 : 1) * (focused ? 2.4 : 1);
  const labelVisible = Boolean(label) && focused;

  return (
    <>
      {/* Core dot — always above everything */}
      <div
        ref={coreRef}
        className="cursor-core"
        aria-hidden
        style={{
          opacity: pressed ? 0 : 1,
        }}
      />
      {/* Trailer — bigger circle, scales on interactive elements */}
      <div
        ref={trailerRef}
        className={`cursor-trailer ${focused ? "is-focused" : ""} ${labelVisible ? "has-label" : ""}`}
        aria-hidden
        style={{
          // CSS-only scale so the 60fps tick doesn't fight React state updates.
          // We read scale from a CSS var on the same element.
          // @ts-expect-error custom property
          "--cursor-scale": scale.toFixed(2),
        }}
      >
        {labelVisible && <span className="cursor-label">{label}</span>}
      </div>
    </>
  );
}

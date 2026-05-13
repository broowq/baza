"use client";

import { useEffect, useRef } from "react";

/**
 * Drop-in wrapper that fades + translates its child into view the FIRST TIME
 * it enters the viewport. Style of reveal mirrors the references — the
 * element starts shifted 24px down with a slight blur, then settles into
 * place with a custom cubic-bezier that has a long tail (feels like film,
 * not a UI snap).
 *
 * Why not Framer Motion?
 *   - Reveals are write-once. Framer adds ~30KB and a render boundary for
 *     a job that's literally three CSS properties + one IntersectionObserver.
 *
 * Variants:
 *   "up"       — translate-y, the default
 *   "scale"    — scale-down to 1 (hero blocks)
 *   "stagger"  — children animate in sequence (rows of feature cards)
 *
 * Usage:
 *   <Reveal>...</Reveal>                    // default fade-up
 *   <Reveal variant="scale">...</Reveal>
 *   <Reveal variant="stagger" delay={80}>   // delay per child in ms
 *     {items.map(...)}
 *   </Reveal>
 */
type Variant = "up" | "scale" | "stagger";

export function Reveal({
  children,
  variant = "up",
  delay = 0,
  threshold = 0.15,
  rootMargin = "0px 0px -10% 0px",
  className = "",
  as: Tag = "div",
}: {
  children: React.ReactNode;
  variant?: Variant;
  delay?: number;
  threshold?: number;
  rootMargin?: string;
  className?: string;
  as?: keyof JSX.IntrinsicElements;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Honour prefers-reduced-motion — show immediately, no animation.
    if (typeof window !== "undefined") {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduce) {
        el.classList.add("srv-shown");
        return;
      }
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const target = entry.target as HTMLElement;

          if (variant === "stagger") {
            // Walk direct children and stamp each with a CSS variable that
            // CSS uses as transition-delay. Avoids JS measuring each item.
            const kids = Array.from(target.children) as HTMLElement[];
            kids.forEach((kid, i) => {
              kid.style.setProperty("--reveal-delay", `${delay + i * 80}ms`);
              kid.classList.add("srv-shown");
            });
          } else {
            target.style.setProperty("--reveal-delay", `${delay}ms`);
            target.classList.add("srv-shown");
          }
          io.unobserve(target);
        }
      },
      { threshold, rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [variant, delay, threshold, rootMargin]);

  // Class map keeps the public Reveal API stable while using the new
  // namespaced CSS (.srv / .srv-scale / .srv-stagger) under the hood.
  const variantClass =
    variant === "stagger" ? "srv-stagger"
    : variant === "scale" ? "srv-scale"
    : "srv";
  const cls = [variantClass, className].filter(Boolean).join(" ");

  // @ts-expect-error JSX tag union
  return <Tag ref={ref} className={cls}>{children}</Tag>;
}

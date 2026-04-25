import { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/**
 * Canonical Cinematic Glass primitive.
 * See /DESIGN.md §4 — Glass Card.
 *
 * Variants:
 *  - default rounded-2xl, p-5, blur-xl
 *  - hero    rounded-3xl, p-8, blur-2xl
 *  - warning rose-tinted glass for warnings/errors
 */

type Props = HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "hero" | "warning";
  hover?: boolean;
  /** Subtle 3D tilt for the "floating" hero feel from rondesignlab refs */
  floating?: boolean;
};

const variantClasses: Record<NonNullable<Props["variant"]>, string> = {
  default:
    "rounded-2xl border border-white/10 bg-white/[0.04] p-5 backdrop-blur-xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]",
  hero:
    "rounded-3xl border border-white/10 bg-white/[0.05] p-8 backdrop-blur-2xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]",
  warning:
    "rounded-2xl border border-status-offline/[0.18] bg-[rgba(40,28,28,0.65)] p-5 backdrop-blur-xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]",
};

export function GlassCard({
  className,
  variant = "default",
  hover = false,
  floating = false,
  children,
  ...props
}: Props) {
  return (
    <div
      className={cn(
        "text-white",
        variantClasses[variant],
        hover &&
          "transition-colors duration-200 hover:bg-white/[0.07] hover:border-white/[0.14]",
        floating && "[transform:rotateX(-2deg)] shadow-[0_30px_80px_-30px_rgba(0,0,0,0.6)]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function GlassCardEyebrow({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "text-[11px] font-medium uppercase tracking-wider text-white/[0.48]",
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

export function GlassCardTitle({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn(
        "text-base font-medium tracking-tight text-white",
        className,
      )}
      {...props}
    >
      {children}
    </h3>
  );
}

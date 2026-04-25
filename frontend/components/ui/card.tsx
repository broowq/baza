import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Cinematic Glass Card.
 * See /DESIGN.md §4 — cards.
 *
 * Variants:
 *  - default rounded-2xl glass surface (most cards)
 *  - hero    rounded-3xl, deeper blur, taller padding (KPI strip, landing)
 *  - compact rounded-xl, smaller padding (dense data containers)
 *
 * Sizes:
 *  - default p-6
 *  - sm      p-4
 */

type CardVariant = "default" | "hero" | "compact";
type CardSize = "default" | "sm";

const variantClasses: Record<CardVariant, string> = {
  default:
    "rounded-2xl border border-white/10 bg-white/[0.04] backdrop-blur-xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]",
  hero:
    "rounded-3xl border border-white/10 bg-white/[0.05] backdrop-blur-2xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]",
  compact:
    "rounded-xl border border-white/10 bg-white/[0.04] backdrop-blur-xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]",
};

const sizePadding: Record<CardSize, string> = {
  default: "p-6",
  sm: "p-4",
};

interface CardProps extends React.ComponentProps<"div"> {
  variant?: CardVariant;
  size?: CardSize;
}

function Card({
  className,
  variant = "default",
  size = "default",
  ...props
}: CardProps) {
  return (
    <div
      data-slot="card"
      data-variant={variant}
      data-size={size}
      className={cn(
        "group/card flex flex-col gap-4 text-sm text-white/[0.92] transition-colors duration-200",
        variantClasses[variant],
        sizePadding[size],
        className,
      )}
      {...props}
    />
  );
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "@container/card-header grid auto-rows-min items-start gap-1 has-data-[slot=card-action]:grid-cols-[1fr_auto]",
        className,
      )}
      {...props}
    />
  );
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn(
        "text-base font-medium leading-snug tracking-tight text-white",
        className,
      )}
      {...props}
    />
  );
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-sm text-white/[0.56]", className)}
      {...props}
    />
  );
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className,
      )}
      {...props}
    />
  );
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="card-content" className={cn("", className)} {...props} />
  );
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn(
        "mt-auto flex items-center border-t border-white/[0.06] pt-4",
        className,
      )}
      {...props}
    />
  );
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
};

"use client";

import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Cinematic Glass Button.
 * See /DESIGN.md §4 — buttons.
 *
 * Variants:
 *  - default   pure-white pill on dark canvas (THE primary action)
 *  - secondary glass pill (most actions)
 *  - ghost     text-only (toolbars, table actions)
 *  - brand     white mint-glow pill (the primary call-to-action)
 *  - destructive translucent rose (destructive)
 *  - link      text + underline on hover
 */
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap select-none transition-colors duration-200 outline-none disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "rounded-full bg-[var(--btn-brand-bg)] text-[var(--btn-brand-fg)] hover:opacity-90 active:opacity-80",
        secondary:
          "rounded-full border border-[var(--line-2)] bg-[var(--surface-3)] text-[var(--t-100)] backdrop-blur-xl hover:bg-[var(--surface-active)] hover:border-[var(--line-3)] data-[state=open]:bg-[var(--surface-active)]",
        // Legacy alias: many call-sites still use variant="outline".
        // Treat it as secondary glass — same visual.
        outline:
          "rounded-full border border-[var(--line-2)] bg-[var(--surface-3)] text-[var(--t-100)] backdrop-blur-xl hover:bg-[var(--surface-active)] hover:border-[var(--line-3)] data-[state=open]:bg-[var(--surface-active)]",
        ghost:
          "rounded-lg text-[var(--t-72)] hover:text-[var(--t-100)] hover:bg-[var(--surface-2)] data-[state=open]:bg-[var(--surface-2)] data-[state=open]:text-[var(--t-100)]",
        brand:
          "rounded-full bg-[var(--btn-brand-bg)] text-[var(--btn-brand-fg)] font-medium shadow-[0_8px_28px_-10px_rgba(168,197,192,0.6),inset_0_-1px_0_rgba(0,0,0,0.18)] hover:-translate-y-px hover:opacity-95 active:opacity-90",
        destructive:
          "rounded-full text-status-offline bg-status-offline/10 border border-status-offline/20 hover:bg-status-offline/15 hover:border-status-offline/30",
        link:
          "rounded-none px-0 text-[var(--t-72)] hover:text-[var(--t-100)] underline-offset-4 hover:underline",
      },
      size: {
        default: "h-11 gap-2 px-5 text-sm",
        xs: "h-7 gap-1 px-2.5 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: "h-9 gap-1.5 px-3.5 text-[0.8125rem] [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-12 gap-2 px-6 text-[0.9375rem]",
        icon: "size-11 [&_svg:not([class*='size-'])]:size-[18px]",
        "icon-sm": "size-9 rounded-lg [&_svg:not([class*='size-'])]:size-4",
        "icon-xs": "size-7 rounded-lg [&_svg:not([class*='size-'])]:size-3.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button };

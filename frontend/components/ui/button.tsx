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
 *  - brand     orange pill (the rare "do this NOW" action)
 *  - destructive translucent rose (destructive)
 *  - link      text + underline on hover
 */
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap select-none transition-colors duration-200 outline-none disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "rounded-full bg-white text-black hover:bg-white/90 active:bg-white/80",
        secondary:
          "rounded-full border border-white/[0.12] bg-white/[0.08] text-white backdrop-blur-xl hover:bg-white/[0.12] hover:border-white/[0.16] data-[state=open]:bg-white/[0.12]",
        // Legacy alias: many call-sites still use variant="outline".
        // Treat it as secondary glass — same visual.
        outline:
          "rounded-full border border-white/[0.12] bg-white/[0.08] text-white backdrop-blur-xl hover:bg-white/[0.12] hover:border-white/[0.16] data-[state=open]:bg-white/[0.12]",
        ghost:
          "rounded-lg text-white/[0.72] hover:text-white hover:bg-white/[0.05] data-[state=open]:bg-white/[0.05] data-[state=open]:text-white",
        brand:
          "rounded-full bg-[#FF6A00] text-black hover:bg-[#FF7A1A] active:bg-[#E65E00] shadow-[0_0_24px_rgba(255,106,0,0.25)] hover:shadow-[0_0_32px_rgba(255,106,0,0.4)]",
        destructive:
          "rounded-full text-status-offline bg-status-offline/10 border border-status-offline/20 hover:bg-status-offline/15 hover:border-status-offline/30",
        link:
          "rounded-none px-0 text-white/80 hover:text-white underline-offset-4 hover:underline",
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

export { Button, buttonVariants };

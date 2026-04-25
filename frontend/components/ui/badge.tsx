import { mergeProps } from "@base-ui/react/merge-props";
import { useRender } from "@base-ui/react/use-render";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Cinematic Glass Badge — pill with optional status dot.
 * See /DESIGN.md §4 — badges, §2 — status palette.
 */

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap backdrop-blur-xl transition-colors duration-200 [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "border-white/10 bg-white/[0.05] text-white/[0.72] [a]:hover:bg-white/[0.08]",
        outline: "border-white/[0.14] bg-transparent text-white/[0.72] [a]:hover:bg-white/[0.04]",
        ghost: "border-transparent bg-transparent text-white/[0.56] hover:text-white",
        online:
          "border-status-online/20 bg-status-online/10 text-status-online",
        offline:
          "border-status-offline/20 bg-status-offline/10 text-status-offline",
        warning:
          "border-status-warning/20 bg-status-warning/10 text-status-warning",
        brand:
          "border-brand/30 bg-brand/10 text-brand",
        // Legacy compat (existing components may pass these — map sensibly)
        secondary: "border-white/10 bg-white/[0.05] text-white/[0.72]",
        destructive:
          "border-status-offline/20 bg-status-offline/10 text-status-offline",
        link: "border-transparent text-white/80 underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

interface BadgeProps
  extends useRender.ComponentProps<"span">,
    VariantProps<typeof badgeVariants> {
  /** Render a colored status dot before the label, with matching glow. */
  dot?: "online" | "offline" | "warning";
}

function Badge({
  className,
  variant = "default",
  render,
  dot,
  children,
  ...props
}: BadgeProps) {
  const dotEl = dot ? (
    <span className="status-dot shrink-0" data-state={dot} aria-hidden />
  ) : null;
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      {
        ...props,
        children: (
          <>
            {dotEl}
            {children}
          </>
        ),
      },
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  });
}

export { Badge, badgeVariants };

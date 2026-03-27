import { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

type Props = HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "highlight";
  hover?: boolean;
};

export function GlassCard({ className, variant = "default", hover = false, children, ...props }: Props) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-slate-200/70 bg-white/90 p-6 backdrop-blur-xl dark:border-white/[0.08] dark:bg-white/[0.04]",
        variant === "highlight" && "shadow-glass",
        hover && "transition-all duration-300 hover:bg-slate-50 dark:hover:bg-white/[0.07] hover:border-gray-300 dark:hover:border-white/[0.15]",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

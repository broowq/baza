import * as React from "react";
import { Input as InputPrimitive } from "@base-ui/react/input";

import { cn } from "@/lib/utils";

/**
 * Cinematic Glass Input.
 * See /DESIGN.md §4 — inputs.
 *
 * Sizes:
 *  - default h-11 (premium, breathing room)
 *  - sm      h-9  (table cells, compact toolbars)
 */

interface InputProps extends React.ComponentProps<"input"> {
  inputSize?: "default" | "sm";
}

function Input({ className, type, inputSize = "default", ...props }: InputProps) {
  const sizeClass =
    inputSize === "sm" ? "h-9 px-3 text-sm rounded-xl" : "h-11 px-4 text-base rounded-2xl";
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      data-size={inputSize}
      className={cn(
        // Base
        "w-full min-w-0 border border-white/10 bg-white/[0.04] backdrop-blur-xl text-white",
        "placeholder:text-white/40 transition-colors duration-200 outline-none",
        // Focus
        "focus-visible:border-white/[0.24] focus-visible:bg-white/[0.07]",
        // Disabled
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        // Invalid
        "aria-invalid:border-status-offline/40 aria-invalid:bg-status-offline/[0.05]",
        // File-input style (rare)
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-white",
        sizeClass,
        className,
      )}
      {...props}
    />
  );
}

export { Input };

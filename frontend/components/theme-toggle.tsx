"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

/**
 * Light/dark toggle. Flips between the two resolved themes; the choice is
 * persisted by next-themes (and overrides the system default once set).
 * Renders a stable placeholder until mounted to avoid a hydration mismatch.
 */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={`focus-ring inline-flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-[var(--line)] ${className}`}
      style={{ border: "1px solid var(--line-2)", color: "var(--t-72)" }}
      aria-label={mounted ? (isDark ? "Светлая тема" : "Тёмная тема") : "Сменить тему"}
      title={mounted ? (isDark ? "Светлая тема" : "Тёмная тема") : "Сменить тему"}
    >
      {/* Until mounted, render a neutral icon (no theme-dependent flip). */}
      {mounted && !isDark ? <Moon size={16} /> : <Sun size={16} />}
    </button>
  );
}

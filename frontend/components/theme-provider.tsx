"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * App-wide theme provider.
 *
 * - attribute="class": the resolved theme is applied as a class on <html>.
 * - value maps light → "theme-light" (NOT "light" — that collides with an
 *   existing typography utility class) and dark → "dark" (Tailwind darkMode).
 * - defaultTheme="system" + enableSystem: новые посетители получают тему ОС,
 *   с ручным переключателем поверх.
 */
export function ThemeProvider({ children, ...props }: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      value={{ light: "theme-light", dark: "dark" }}
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}

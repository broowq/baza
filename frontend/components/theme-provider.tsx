"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * App-wide theme provider.
 *
 * - attribute="class": the resolved theme is applied as a class on <html>.
 * - value maps light → "theme-light" (NOT "light" — that collides with an
 *   existing typography utility class) and dark → "dark" (Tailwind darkMode).
 * - defaultTheme="dark" без enableSystem: первого посетителя ВСЕГДА встречает
 *   тёмная тема (независимо от настройки ОС), дальше его выбор из тоггла
 *   сохраняется и перебивает дефолт. Тоггл переключает только light/dark и
 *   «system» не использует, поэтому привязка к ОС не нужна.
 */
export function ThemeProvider({ children, ...props }: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem={false}
      value={{ light: "theme-light", dark: "dark" }}
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}

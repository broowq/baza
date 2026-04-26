"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X } from "lucide-react";
import { useEffect, useState } from "react";

import { clearToken, getToken } from "@/lib/auth";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

const DASHBOARD_PREFIXES = ["/dashboard"];

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Hide navbar on dashboard routes (sidebar handles navigation there)
  const isDashboardRoute = DASHBOARD_PREFIXES.some((p) => pathname?.startsWith(p));

  useEffect(() => {
    setMounted(true);
    setAuthed(Boolean(getToken()));
    // Force dark — light theme isn't supported by the design system.
    document.documentElement.classList.add("dark");
  }, [pathname]);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  if (isDashboardRoute) return null;
  // Landing renders its own custom v2 topnav inline.
  if (pathname === "/") return null;
  // /plans renders its own sidebar layout when user is logged in.
  if (pathname?.startsWith("/plans") && mounted && authed) return null;

  const navLinkClass = "rounded-lg px-3 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/[0.06]";

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/80 backdrop-blur-xl dark:border-white/[0.06] dark:bg-[#0a0a12]/80">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 sm:px-6 py-4">
        <Link href="/" className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#191C1F] text-xs font-bold text-white dark:bg-white dark:text-[#191C1F]">
            Б
          </div>
          <span className="text-xl font-bold tracking-tight">БАЗА</span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden sm:flex items-center gap-2" aria-label="Основная навигация">
          <Link href="/plans" className={navLinkClass}>
            Тарифы
          </Link>
          {mounted && authed ? (
            <>
              <Link href="/dashboard" className={navLinkClass}>
                Дашборд
              </Link>
              <Button
                variant="ghost"
                onClick={async () => {
                  try {
                    await api("/auth/logout", { method: "POST", body: JSON.stringify({}) });
                  } catch {}
                  clearToken();
                  router.push("/login");
                }}
              >
                Выйти
              </Button>
            </>
          ) : (
            <>
              <Link href="/login" className={navLinkClass}>
                Войти
              </Link>
              <Link href="/register">
                <Button>Попробовать</Button>
              </Link>
            </>
          )}
        </nav>

        {/* Mobile hamburger */}
        <div className="flex sm:hidden items-center gap-1">
          <Button variant="ghost" onClick={() => setMobileOpen((v) => !v)} className="h-9 w-9 p-0" aria-label="Меню">
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </Button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <nav className="sm:hidden border-t border-slate-200/70 dark:border-white/[0.06] px-4 pb-4 pt-2 space-y-1" aria-label="Мобильная навигация">
          <Link href="/plans" className="block rounded-lg px-3 py-2.5 text-sm text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/[0.06]">
            Тарифы
          </Link>
          {mounted && authed ? (
            <>
              <Link href="/dashboard" className="block rounded-lg px-3 py-2.5 text-sm text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/[0.06]">
                Дашборд
              </Link>
              <button
                className="block w-full text-left rounded-lg px-3 py-2.5 text-sm text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/[0.06]"
                onClick={async () => {
                  try {
                    await api("/auth/logout", { method: "POST", body: JSON.stringify({}) });
                  } catch {}
                  clearToken();
                  router.push("/login");
                }}
              >
                Выйти
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="block rounded-lg px-3 py-2.5 text-sm text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/[0.06]">
                Войти
              </Link>
              <Link href="/register" className="block rounded-lg px-3 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-slate-100 dark:hover:bg-white/[0.06]">
                Попробовать
              </Link>
            </>
          )}
        </nav>
      )}
    </header>
  );
}

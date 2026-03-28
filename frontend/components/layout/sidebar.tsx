"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronLeft,
  CreditCard,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Settings,
  Shield,
  Sun,
  X,
} from "lucide-react";

import { clearToken, getToken } from "@/lib/auth";
import { api } from "@/lib/api";

const NAV_ITEMS: { href: Route; label: string; icon: typeof LayoutDashboard }[] = [
  { href: "/dashboard" as Route, label: "Дашборд", icon: LayoutDashboard },
  { href: "/dashboard/settings" as Route, label: "Настройки", icon: Settings },
  { href: "/plans" as Route, label: "Тарифы", icon: CreditCard },
];

const labelVariants = {
  open: {
    opacity: 1,
    width: "auto",
    marginLeft: 12,
    transition: { duration: 0.2, ease: "easeOut" },
  },
  closed: {
    opacity: 0,
    width: 0,
    marginLeft: 0,
    transition: { duration: 0.15, ease: "easeIn" },
  },
};

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const saved = localStorage.getItem("sidebar-collapsed");
    if (saved === "true") setCollapsed(true);

    setDark(document.documentElement.classList.contains("dark"));

    const token = getToken();
    if (token) {
      api<{ email: string; is_admin: boolean }>("/auth/me")
        .then((me) => {
          setIsAdmin(me.is_admin);
          setUserEmail(me.email);
        })
        .catch(() => {});
    }
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const toggleCollapse = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("sidebar-collapsed", String(next));
  };

  const toggleTheme = () => {
    const html = document.documentElement;
    html.classList.toggle("dark");
    const isDark = html.classList.contains("dark");
    setDark(isDark);
    localStorage.setItem("theme", isDark ? "dark" : "light");
  };

  const handleLogout = async () => {
    try {
      await api("/auth/logout", { method: "POST", body: JSON.stringify({}) });
    } catch {}
    clearToken();
    router.push("/login");
  };

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname?.startsWith(href);
  };

  const navItems = isAdmin
    ? [...NAV_ITEMS, { href: "/dashboard/admin" as Route, label: "Админ", icon: Shield }]
    : NAV_ITEMS;

  const sidebarContent = (
    <div className="flex h-full flex-col">
      {/* Logo area */}
      <div className="flex h-16 shrink-0 items-center justify-between px-4">
        <Link href="/dashboard" className="flex items-center gap-2.5 overflow-hidden">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-foreground to-foreground/80 text-sm font-bold text-background shadow-sm">
            Б
          </div>
          <AnimatePresence initial={false}>
            {!collapsed && (
              <motion.span
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
                className="whitespace-nowrap text-lg font-bold tracking-tight text-foreground"
              >
                БАЗА
              </motion.span>
            )}
          </AnimatePresence>
        </Link>

        {/* Desktop collapse button */}
        <button
          onClick={toggleCollapse}
          className="hidden shrink-0 rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground lg:block"
          aria-label={collapsed ? "Развернуть" : "Свернуть"}
        >
          <ChevronLeft
            size={16}
            className={`transition-transform duration-300 ${collapsed ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {/* Divider */}
      <div className="mx-4 border-t border-border/50" />

      {/* Navigation */}
      <nav className="mt-3 flex-1 space-y-1 px-3">
        {navItems.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`group relative flex items-center rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
              }`}
            >
              {/* Active left border indicator */}
              <motion.div
                initial={false}
                animate={{
                  opacity: active ? 1 : 0,
                  scaleY: active ? 1 : 0.5,
                }}
                transition={{ duration: 0.2, ease: "easeOut" }}
                className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary"
              />

              <item.icon
                size={18}
                className={`shrink-0 transition-colors duration-200 ${
                  active
                    ? "text-primary"
                    : "text-muted-foreground/70 group-hover:text-accent-foreground"
                }`}
              />

              <AnimatePresence initial={false}>
                {!collapsed && (
                  <motion.span
                    variants={labelVariants}
                    initial="closed"
                    animate="open"
                    exit="closed"
                    className="overflow-hidden whitespace-nowrap"
                  >
                    {item.label}
                  </motion.span>
                )}
              </AnimatePresence>
            </Link>
          );
        })}
      </nav>

      {/* Bottom section */}
      <div className="shrink-0 border-t border-border/50 p-3 space-y-1">
        {/* User email */}
        <AnimatePresence initial={false}>
          {!collapsed && userEmail && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2 }}
              className="truncate px-3 py-1.5 text-xs text-muted-foreground"
            >
              {userEmail}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="flex w-full items-center rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors duration-200 hover:bg-accent/50 hover:text-accent-foreground"
        >
          <AnimatePresence mode="wait" initial={false}>
            {mounted && dark ? (
              <motion.span
                key="sun"
                initial={{ rotate: -90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: 90, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="shrink-0"
              >
                <Sun size={16} />
              </motion.span>
            ) : (
              <motion.span
                key="moon"
                initial={{ rotate: 90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: -90, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="shrink-0"
              >
                <Moon size={16} />
              </motion.span>
            )}
          </AnimatePresence>

          <AnimatePresence initial={false}>
            {!collapsed && (
              <motion.span
                variants={labelVariants}
                initial="closed"
                animate="open"
                exit="closed"
                className="overflow-hidden whitespace-nowrap"
              >
                {mounted && dark ? "Светлая тема" : "Тёмная тема"}
              </motion.span>
            )}
          </AnimatePresence>
        </button>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="flex w-full items-center rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors duration-200 hover:bg-destructive/10 hover:text-destructive"
        >
          <LogOut size={16} className="shrink-0" />

          <AnimatePresence initial={false}>
            {!collapsed && (
              <motion.span
                variants={labelVariants}
                initial="closed"
                animate="open"
                exit="closed"
                className="overflow-hidden whitespace-nowrap"
              >
                Выйти
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed left-4 top-4 z-50 min-h-[44px] min-w-[44px] rounded-xl border border-border/50 bg-background/80 p-2.5 text-foreground shadow-sm backdrop-blur-xl lg:hidden"
        aria-label="Открыть меню"
      >
        <Menu size={20} />
      </button>

      {/* Mobile overlay */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
              onClick={() => setMobileOpen(false)}
            />
            <motion.aside
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="fixed left-0 top-0 z-50 flex h-full w-[260px] flex-col backdrop-blur-xl bg-background/95 border-r border-border/50 lg:hidden"
            >
              <button
                onClick={() => setMobileOpen(false)}
                className="absolute right-3 top-4 min-h-[44px] min-w-[44px] rounded-lg p-2.5 text-muted-foreground transition-colors hover:text-foreground"
                aria-label="Закрыть меню"
              >
                <X size={18} />
              </button>
              {sidebarContent}
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* Desktop sidebar */}
      <motion.aside
        animate={{ width: collapsed ? 72 : 260 }}
        transition={{ duration: 0.3, ease: "easeInOut" }}
        className="sticky top-0 hidden h-screen flex-col backdrop-blur-xl bg-background/80 border-r border-border/50 lg:flex"
      >
        {sidebarContent}
      </motion.aside>
    </>
  );
}

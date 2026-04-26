"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { clearToken, getToken } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Organization } from "@/lib/types";

type NavItem = {
  href: Route;
  label: string;
  icon: React.ReactNode;
  match?: (path: string) => boolean;
  count?: () => string | undefined;
};

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const [userName, setUserName] = useState("");
  const [org, setOrg] = useState<Organization | null>(null);
  const [projectCount, setProjectCount] = useState<number | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    api<{ email: string; full_name?: string; is_admin: boolean }>("/auth/me")
      .then((me) => {
        setIsAdmin(me.is_admin);
        setUserEmail(me.email);
        setUserName(me.full_name ?? "");
      })
      .catch(() => {});

    api<Organization>("/organizations/me")
      .then(setOrg)
      .catch(() => {});

    api<unknown[]>("/projects")
      .then((rows) => setProjectCount(Array.isArray(rows) ? rows.length : null))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const handleLogout = async () => {
    try {
      await api("/auth/logout", { method: "POST", body: JSON.stringify({}) });
    } catch {}
    clearToken();
    router.push("/login");
  };

  const navItems: NavItem[] = [
    {
      href: "/dashboard" as Route,
      label: "Дашборд",
      icon: (
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
        </svg>
      ),
      match: (p) => p === "/dashboard",
    },
    {
      href: "/dashboard/projects" as Route,
      label: "Проекты",
      icon: (
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 7l9-4 9 4-9 4-9-4z" />
          <path d="M3 12l9 4 9-4" />
          <path d="M3 17l9 4 9-4" />
        </svg>
      ),
      match: (p) => p.startsWith("/dashboard/projects"),
      count: () =>
        projectCount === null ? undefined : String(projectCount),
    },
    {
      href: "/plans" as Route,
      label: "Тарифы",
      icon: (
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M5 4h14l-2 16H7L5 4z" />
          <path d="M9 9h6" />
          <path d="M9 13h6" />
        </svg>
      ),
      match: (p) => p.startsWith("/plans"),
    },
    {
      href: "/dashboard/settings" as Route,
      label: "Настройки",
      icon: (
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.2.6.7 1 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
        </svg>
      ),
      match: (p) => p.startsWith("/dashboard/settings") || p.startsWith("/settings"),
    },
  ];

  if (isAdmin) {
    navItems.push({
      href: "/dashboard/admin" as Route,
      label: "Админ",
      icon: (
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M12 3l8 4v6c0 5-3.5 7.5-8 8-4.5-.5-8-3-8-8V7l8-4z" />
        </svg>
      ),
      match: (p) => p.startsWith("/dashboard/admin"),
    });
  }

  const userInitials = (() => {
    if (!userName) return userEmail ? userEmail.slice(0, 2).toUpperCase() : "··";
    const parts = userName.trim().split(/\s+/);
    return (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "");
  })().toUpperCase().slice(0, 2);

  const sidebar = (
    <aside className="sidebar-v3 h-full">
      {/* Top: brand + org switcher.
          Logo links to landing (/) — marketing «main screen».
          To go to the product home, use the Дашборд nav item below. */}
      <div className="px-4 pt-5 pb-4">
        <div className="flex items-center gap-2.5">
          <Link
            href={"/" as Route}
            className="flex items-center gap-2.5 min-w-0"
            aria-label="На главную"
          >
            <span className="avatar w-7 h-7 text-[12px]">Б</span>
            <span className="text-[15px] truncate" style={{ fontWeight: 500 }}>
              база
            </span>
          </Link>
        </div>
        <div className="flex items-center gap-2 mt-3 pl-1">
          <span className="text-[12px] t-72 truncate flex-1 min-w-0">
            {org?.name ?? "БАЗА Демо"}
          </span>
          {org?.plan && (
            <span
              className="chip chip-mint"
              style={{ padding: "2px 8px", fontSize: "9.5px" }}
            >
              {org.plan}
            </span>
          )}
          <svg className="car shrink-0" viewBox="0 0 24 24">
            <path d="M8 10l4 4 4-4" />
          </svg>
        </div>
      </div>

      <div className="hairline mx-4" />

      {/* Nav */}
      <nav className="px-3 pt-4 flex flex-col gap-1.5">
        {navItems.map((item) => {
          const active = item.match
            ? item.match(pathname ?? "")
            : pathname === item.href;
          const count = item.count?.();
          return (
            <Link
              key={`${item.label}-${item.href}`}
              href={item.href}
              className={`nav-item ${active ? "active" : ""}`}
            >
              {item.icon}
              <span className="truncate">{item.label}</span>
              {count !== undefined && <span className="count">{count}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Mid: beta chip */}
      <div className="px-4 mt-6">
        <span className="chip chip-mint" style={{ padding: "3px 10px", gap: 7 }}>
          <span
            className="dot dot-mt dot-pulse"
            style={{ width: 5, height: 5 }}
          />
          бета v0.9
        </span>
      </div>

      {/* Bottom sticky */}
      <div className="mt-auto px-4 pb-5">
        <div className="hairline mb-4" />
        <div className="flex items-center gap-2.5 mb-3">
          <span className="avatar steel w-6 h-6 text-[10px]">{userInitials}</span>
          <div className="min-w-0">
            <div className="text-[12.5px] truncate">
              {userName || "Пользователь"}
            </div>
            <div
              className="mono"
              style={{ fontSize: 10, color: "var(--t-48)" }}
            >
              <span className="truncate inline-block max-w-[160px] align-bottom">
                {userEmail || "—"}
              </span>
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={handleLogout}
          className="text-[12px] t-56 hover:c-rose transition-colors text-left"
        >
          Выйти →
        </button>
      </div>
    </aside>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed left-4 top-4 z-50 min-h-[44px] min-w-[44px] rounded-xl border border-[var(--line-2)] bg-[rgba(15,16,20,0.72)] backdrop-blur-xl p-2.5 text-white shadow-lg lg:hidden"
        aria-label="Открыть меню"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
          <div className="fixed left-0 top-0 z-50 h-full lg:hidden">
            <div className="relative h-full">
              <button
                onClick={() => setMobileOpen(false)}
                className="absolute right-3 top-4 z-10 min-h-[44px] min-w-[44px] rounded-lg p-2.5 t-72 hover:text-white"
                aria-label="Закрыть меню"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
              {sidebar}
            </div>
          </div>
        </>
      )}

      {/* Desktop sticky sidebar */}
      <div className="sticky top-0 hidden h-screen lg:block">{sidebar}</div>
    </>
  );
}

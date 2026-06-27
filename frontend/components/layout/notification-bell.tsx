"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";

import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { Notifications } from "@/lib/types";

/* ─────────────────────────────────────────────────────────────────
   useNotifications — shared notifications poller.

   Fetches GET /crm/notifications on mount and every ~60s. Lifted out
   of the bell so the Sidebar can also read overdue_tasks.count for the
   «Задачи» badge from the same source of truth (one fetch, two readers).
   Never throws to the tree: errors leave the last good payload in place.
───────────────────────────────────────────────────────────────── */

const POLL_MS = 60_000;

export function useNotifications(): Notifications | null {
  const [data, setData] = useState<Notifications | null>(null);

  useEffect(() => {
    if (!getToken()) return;
    let alive = true;

    const load = () => {
      api<Notifications>("/crm/notifications")
        .then((d) => {
          if (alive) setData(d);
        })
        .catch(() => {
          /* keep last good payload; bell/badge just stay stale for a cycle */
        });
    };

    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  return data;
}

/* Compact «N просрочено» style pluralisation for headers. */
function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

/* Relative-ish, compact ru date for list rows. */
function formatWhen(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameYear = d.getFullYear() === now.getFullYear();
  const dateStr = d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  });
  const hasTime = d.getHours() !== 0 || d.getMinutes() !== 0;
  const timeStr = hasTime
    ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : "";
  return timeStr ? `${dateStr} · ${timeStr}` : dateStr;
}

type Props = {
  notifications: Notifications | null;
};

/**
 * Notification bell for the sidebar. Renders a bell button with an unread
 * badge (hidden when total === 0). Clicking opens a dropdown grouping the
 * three notification kinds; each row routes the rep back into the product.
 * Closes on outside-click / Escape.
 *
 * The notifications payload is owned by the Sidebar (via useNotifications)
 * and passed in, so the «Задачи» nav badge stays in sync with the bell.
 */
export function NotificationBell({ notifications }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const total = notifications?.total ?? 0;
  const replies = notifications?.new_replies;
  const tasks = notifications?.overdue_tasks;
  const reminders = notifications?.due_reminders;
  const hasAny =
    (replies?.count ?? 0) > 0 ||
    (tasks?.count ?? 0) > 0 ||
    (reminders?.count ?? 0) > 0;

  // Outside-click closes the dropdown.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href as Route);
    },
    [router]
  );

  const badge = total > 99 ? "99+" : String(total);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Уведомления"
        aria-haspopup="true"
        aria-expanded={open}
        className="relative inline-flex items-center justify-center transition-colors"
        style={{
          width: 34,
          height: 34,
          borderRadius: 10,
          border: "1px solid var(--line)",
          background: open ? "var(--surface-hover)" : "var(--surface-input)",
          color: "var(--t-72)",
        }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ width: 16, height: 16 }}>
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {total > 0 && (
          <span
            aria-hidden
            className="tnum"
            style={{
              position: "absolute",
              top: -5,
              right: -5,
              minWidth: 16,
              height: 16,
              padding: "0 4px",
              borderRadius: 999,
              background: "var(--rose)",
              color: "#0A0A0C",
              fontSize: 9.5,
              fontWeight: 600,
              lineHeight: "16px",
              textAlign: "center",
              boxShadow: "0 0 0 2px var(--surface-1)",
            }}
          >
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="panel absolute right-0 z-50 mt-1.5 overflow-hidden"
          style={{ width: 320, maxHeight: 420, overflowY: "auto", padding: 6 }}
        >
          <div
            className="flex items-center justify-between px-2 py-1.5"
            style={{ borderBottom: "1px solid var(--line)", marginBottom: 4 }}
          >
            <span className="eyebrow" style={{ marginBottom: 0 }}>Уведомления</span>
            {total > 0 && (
              <span className="tnum" style={{ fontSize: 11, color: "var(--t-48)" }}>
                {total}
              </span>
            )}
          </div>

          {!hasAny ? (
            <div className="px-3 py-6 text-center">
              <div style={{ fontSize: 13, color: "var(--t-72)" }}>Всё разобрано</div>
              <div style={{ fontSize: 11.5, color: "var(--t-40)", marginTop: 4 }}>
                Новых ответов, задач и напоминаний нет.
              </div>
            </div>
          ) : (
            <>
              {/* New inbound replies */}
              {(replies?.count ?? 0) > 0 && (
                <Group
                  title={`${replies!.count} ${plural(replies!.count, "новый ответ", "новых ответа", "новых ответов")}`}
                  tone="var(--mint)"
                >
                  {replies!.items.map((r) => (
                    <Row
                      key={r.id}
                      onClick={() =>
                        r.lead_id
                          ? go(`/dashboard/leads?open=${r.lead_id}`)
                          : go("/dashboard/outreach")
                      }
                      primary={r.subject || r.from_email || "Без темы"}
                      secondary={r.from_email}
                      when={formatWhen(r.received_at)}
                    />
                  ))}
                </Group>
              )}

              {/* Overdue tasks */}
              {(tasks?.count ?? 0) > 0 && (
                <Group
                  title={`${tasks!.count} ${plural(tasks!.count, "просроченная задача", "просроченные задачи", "просроченных задач")}`}
                  tone="var(--rose)"
                  onHeaderClick={() => go("/dashboard/tasks")}
                >
                  {tasks!.items.map((t) => (
                    <Row
                      key={t.id}
                      onClick={() => go("/dashboard/tasks")}
                      primary={t.title}
                      secondary={t.lead_company}
                      when={formatWhen(t.due_at)}
                      whenTone="var(--rose)"
                    />
                  ))}
                </Group>
              )}

              {/* Due reminders */}
              {(reminders?.count ?? 0) > 0 && (
                <Group
                  title={`${reminders!.count} ${plural(reminders!.count, "напоминание", "напоминания", "напоминаний")}`}
                  tone="var(--amber)"
                >
                  {reminders!.items.map((rm) => (
                    <Row
                      key={rm.lead_id}
                      onClick={() => go(`/dashboard/leads?open=${rm.lead_id}`)}
                      primary={rm.company}
                      secondary="Напоминание по лиду"
                      when={formatWhen(rm.reminder_at)}
                      whenTone="var(--amber)"
                    />
                  ))}
                </Group>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Group({
  title,
  tone,
  onHeaderClick,
  children,
}: {
  title: string;
  tone: string;
  onHeaderClick?: () => void;
  children: React.ReactNode;
}) {
  const header = (
    <div className="flex items-center gap-1.5 px-2 py-1.5">
      <span aria-hidden style={{ width: 5, height: 5, borderRadius: 999, background: tone, flex: "none" }} />
      <span style={{ fontSize: 11, letterSpacing: "0.02em", color: "var(--t-72)", fontWeight: 500 }}>
        {title}
      </span>
    </div>
  );
  return (
    <div style={{ marginBottom: 2 }}>
      {onHeaderClick ? (
        <button
          type="button"
          onClick={onHeaderClick}
          className="w-full text-left rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
        >
          {header}
        </button>
      ) : (
        header
      )}
      <div className="flex flex-col">{children}</div>
    </div>
  );
}

function Row({
  onClick,
  primary,
  secondary,
  when,
  whenTone,
}: {
  onClick: () => void;
  primary: string;
  secondary?: string;
  when?: string;
  whenTone?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-start gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--surface-hover)]"
    >
      <div className="min-w-0 flex-1">
        <div className="truncate" style={{ fontSize: 12.5, color: "var(--t-100)" }} title={primary}>
          {primary}
        </div>
        {secondary && (
          <div className="truncate" style={{ fontSize: 11, color: "var(--t-48)" }} title={secondary}>
            {secondary}
          </div>
        )}
      </div>
      {when && (
        <span
          className="tnum shrink-0"
          style={{ fontSize: 10.5, color: whenTone ?? "var(--t-40)", marginTop: 1 }}
        >
          {when}
        </span>
      )}
    </button>
  );
}

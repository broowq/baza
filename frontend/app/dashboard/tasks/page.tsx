"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { useAuthGuard } from "@/lib/hooks";
import type { LeadTaskWithLead } from "@/lib/types";

type Scope = "today" | "overdue" | "open" | "done";

const SCOPES: { key: Scope; label: string }[] = [
  { key: "today", label: "Сегодня" },
  { key: "overdue", label: "Просрочено" },
  { key: "open", label: "Открытые" },
  { key: "done", label: "Выполнено" },
];

const EMPTY_COPY: Record<Scope, { title: string; body: string }> = {
  today: {
    title: "На сегодня задач нет",
    body: "Здесь появятся задачи со сроком на сегодня. Можно выдохнуть.",
  },
  overdue: {
    title: "Просроченных задач нет",
    body: "Отлично — всё под контролем, ничего не горит.",
  },
  open: {
    title: "Открытых задач нет",
    body: "Создавайте задачи в карточке лида, и они появятся здесь.",
  },
  done: {
    title: "Выполненных задач пока нет",
    body: "Закрытые задачи будут собираться здесь.",
  },
};

/** Local midnight boundaries for «today» / «overdue» date coloring. */
function dayBounds() {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start, end };
}

function formatDue(due: string): { label: string; tone: "rose" | "amber" | "muted" } {
  const d = new Date(due);
  const { start, end } = dayBounds();
  const isToday = d >= start && d < end;
  const isOverdue = d < start;

  const sameYear = d.getFullYear() === start.getFullYear();
  const dateStr = d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  });
  const hasTime = d.getHours() !== 0 || d.getMinutes() !== 0;
  const timeStr = hasTime ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "";

  if (isToday) {
    return { label: timeStr ? `Сегодня · ${timeStr}` : "Сегодня", tone: "amber" };
  }
  if (isOverdue) {
    return { label: timeStr ? `${dateStr} · ${timeStr}` : dateStr, tone: "rose" };
  }
  return { label: timeStr ? `${dateStr} · ${timeStr}` : dateStr, tone: "muted" };
}

const TONE_COLOR: Record<"rose" | "amber" | "muted", string> = {
  rose: "var(--rose)",
  amber: "var(--amber)",
  muted: "var(--t-48)",
};

export default function TasksPage() {
  const authed = useAuthGuard();
  const [scope, setScope] = useState<Scope>("today");
  const [tasks, setTasks] = useState<LeadTaskWithLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Tracks ids being toggled so their checkbox/row reflects an in-flight PATCH.
  const [pending, setPending] = useState<Set<string>>(new Set());

  const load = useCallback(async (current: Scope) => {
    setLoading(true);
    setError(null);
    try {
      const rows = await api<LeadTaskWithLead[]>(
        `/crm/tasks?scope=${current}&assignee=me`
      );
      setTasks(Array.isArray(rows) ? rows : []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Не удалось загрузить задачи";
      // api() handles auth redirects itself; surface everything else inline.
      setError(msg);
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed) void load(scope);
  }, [authed, scope, load]);

  const toggleDone = async (task: LeadTaskWithLead) => {
    if (pending.has(task.id)) return;
    const nextDone = !task.done;
    setPending((prev) => new Set(prev).add(task.id));
    try {
      await api(`/crm/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ done: nextDone }),
      });
      // The task usually leaves the current scope after the change
      // (e.g. completing in «Сегодня», reopening in «Выполнено»), so drop it
      // from the list rather than mutating it in place.
      setTasks((prev) => prev.filter((t) => t.id !== task.id));
      toast.success(nextDone ? "Задача выполнена" : "Задача возвращена в работу");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось обновить задачу");
    } finally {
      setPending((prev) => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  };

  if (!authed) {
    return (
      <main className="mx-auto max-w-[920px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <TasksSkeleton />
      </main>
    );
  }

  const empty = EMPTY_COPY[scope];

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-[920px] space-y-7 px-4 py-8 sm:px-6 lg:px-10 lg:py-10"
    >
      {/* ── Header ── */}
      <div>
        <div className="eyebrow mb-2">crm · задачи</div>
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <h1 className="h1" style={{ fontSize: 44 }}>Мои задачи</h1>
          {!loading && !error && (
            <span className="mono-cap t-40 mb-1.5">
              {tasks.length} {pluralTasks(tasks.length)}
            </span>
          )}
        </div>
        <p className="t-56 text-[13px] mt-2">
          Задачи по лидам со всех проектов, назначенные на вас.
        </p>
      </div>

      {/* ── Scope tabs ── */}
      <div className="seg flex-wrap" role="group" aria-label="Фильтр задач">
        {SCOPES.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`seg-btn${scope === s.key ? " active" : ""}`}
            aria-pressed={scope === s.key}
            onClick={() => setScope(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* ── Body ── */}
      {loading ? (
        <TasksSkeleton />
      ) : error ? (
        <div className="panel p-8 text-center space-y-4">
          <p className="t-72 text-sm">{error}</p>
          <button className="btn btn-brand" onClick={() => void load(scope)}>
            Повторить
          </button>
        </div>
      ) : tasks.length === 0 ? (
        <div className="empty-state panel-glass elev-1">
          <div className="empty-state__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="var(--mint)" strokeWidth="1.5" style={{ width: 28, height: 28 }}>
              <path d="M9 11l3 3L22 4" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
            </svg>
          </div>
          <h3 className="empty-state__title">{empty.title}</h3>
          <p className="empty-state__body">{empty.body}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          {tasks.map((task, idx) => (
            <TaskRow
              key={task.id}
              task={task}
              scope={scope}
              pending={pending.has(task.id)}
              onToggle={() => void toggleDone(task)}
              index={idx}
            />
          ))}
        </div>
      )}
    </motion.main>
  );
}

function TaskRow({
  task,
  scope,
  pending,
  onToggle,
  index,
}: {
  task: LeadTaskWithLead;
  scope: Scope;
  pending: boolean;
  onToggle: () => void;
  index: number;
}) {
  const isDone = scope === "done" || task.done;
  const due = task.due_at ? formatDue(task.due_at) : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, delay: Math.min(index * 0.03, 0.2) }}
      className="lead-card group relative"
      style={pending ? { opacity: 0.55 } : undefined}
    >
      <div className="lead-card__row" style={{ gap: 12 }}>
        {/* Complete / reopen checkbox */}
        <button
          type="button"
          onClick={onToggle}
          disabled={pending}
          aria-label={isDone ? "Вернуть в работу" : "Отметить выполненной"}
          aria-pressed={isDone}
          className="shrink-0 grid place-items-center transition-colors focus-ring"
          style={{
            width: 20,
            height: 20,
            borderRadius: 6,
            border: `1.5px solid ${isDone ? "var(--mint)" : "var(--line-3)"}`,
            background: isDone ? "var(--mint)" : "transparent",
            cursor: pending ? "default" : "pointer",
          }}
        >
          {isDone && (
            <svg viewBox="0 0 24 24" fill="none" stroke="var(--bg)" strokeWidth="3" style={{ width: 12, height: 12 }}>
              <path d="M5 13l4 4L19 7" />
            </svg>
          )}
        </button>

        {/* Title + lead */}
        <div className="min-w-0 flex-1">
          <div
            className="text-[14px] leading-snug truncate"
            style={{
              color: isDone ? "var(--t-48)" : "var(--t-100)",
              textDecoration: isDone ? "line-through" : "none",
            }}
            title={task.title}
          >
            {task.title}
          </div>
          {task.lead_company && (
            <div className="lead-card__meta mt-1">
              {task.project_id ? (
                <Link
                  href={`/dashboard/projects/${task.project_id}`}
                  className="relative z-10 hover:underline decoration-[var(--t-40)] underline-offset-2 truncate"
                  style={{ color: "var(--t-72)" }}
                >
                  {task.lead_company}
                </Link>
              ) : (
                <span className="t-72 truncate">{task.lead_company}</span>
              )}
            </div>
          )}
        </div>

        {/* Due date */}
        {due && (
          <span
            className="mono shrink-0 text-[11.5px] tnum"
            style={{ color: TONE_COLOR[due.tone] }}
          >
            {due.label}
          </span>
        )}
      </div>
    </motion.div>
  );
}

function TasksSkeleton() {
  return (
    <div className="flex flex-col gap-2.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-[68px] animate-pulse rounded-2xl border border-[var(--line)] bg-[var(--surface-1)]"
        />
      ))}
    </div>
  );
}

function pluralTasks(n: number): string {
  const rule = new Intl.PluralRules("ru").select(n);
  if (rule === "one") return "задача";
  if (rule === "few") return "задачи";
  return "задач";
}

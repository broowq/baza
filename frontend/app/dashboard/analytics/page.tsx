"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";

import { api } from "@/lib/api";
import { useAuthGuard } from "@/lib/hooks";
import type { Dashboard, LeadStatus } from "@/lib/types";

/* ── ru-RU formatting helpers ─────────────────────────────────────── */

function formatInt(n: number): string {
  return Math.round(n || 0).toLocaleString("ru-RU");
}

/* Compact ₽ (mirrors FunnelBar): 1 250 000 → «1,3 млн ₽». */
function formatRub(value: number): string {
  const v = Math.round(value || 0);
  const abs = Math.abs(v);
  if (abs >= 1_000_000) {
    const m = v / 1_000_000;
    const s = (Math.abs(m) >= 10 ? Math.round(m) : Math.round(m * 10) / 10).toLocaleString("ru-RU", {
      maximumFractionDigits: 1,
    });
    return `${s} млн ₽`;
  }
  if (abs >= 10_000) {
    return `${Math.round(v / 1000).toLocaleString("ru-RU")} тыс ₽`;
  }
  return `${v.toLocaleString("ru-RU")} ₽`;
}

const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "Новые",
  contacted: "Связались",
  qualified: "Квалиф.",
  proposal: "КП",
  won: "Выиграно",
  rejected: "Отклонено",
};

function statusColor(status: LeadStatus): string {
  if (status === "won") return "var(--mint)";
  if (status === "rejected") return "var(--rose)";
  return "var(--t-40)";
}

const SOURCE_LABELS: Record<string, string> = {
  yandex_maps: "Яндекс Карты",
  "2gis": "2ГИС",
  rusprofile: "Rusprofile",
  searxng: "SearXNG",
  bing: "Bing",
  maps_searxng: "Карты + поиск",
  manual: "Вручную",
  import: "Импорт",
  "—": "Без источника",
  "": "Без источника",
};

function sourceLabel(s: string): string {
  return SOURCE_LABELS[s] ?? s;
}

function weekday(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

/* ── Page ─────────────────────────────────────────────────────────── */

export default function AnalyticsPage() {
  const authed = useAuthGuard();
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api<Dashboard>("/crm/dashboard");
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить аналитику");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed) void load();
  }, [authed, load]);

  if (!authed) {
    return (
      <main className="mx-auto max-w-[1040px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <AnalyticsSkeleton />
      </main>
    );
  }

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-[1040px] space-y-7 px-4 py-8 sm:px-6 lg:px-10 lg:py-10"
    >
      {/* ── Header ── */}
      <div>
        <div className="eyebrow mb-2">crm · аналитика</div>
        <h1 className="h1" style={{ fontSize: 44 }}>Аналитика</h1>
        <p className="t-56 text-[13px] mt-2">
          Сводка по всем проектам организации: воронка, источники, команда и динамика.
        </p>
      </div>

      {loading ? (
        <AnalyticsSkeleton />
      ) : error ? (
        <div className="panel p-8 text-center space-y-4">
          <p className="t-72 text-sm">{error}</p>
          <button className="btn btn-brand" onClick={() => void load()}>
            Повторить
          </button>
        </div>
      ) : data ? (
        <AnalyticsBody data={data} />
      ) : null}
    </motion.main>
  );
}

function AnalyticsBody({ data }: { data: Dashboard }) {
  return (
    <div className="space-y-7">
      {/* ── Stat tiles ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="stat-tile elev-1">
          <div className="stat-tile__label">Лидов всего</div>
          <div className="stat-tile__value tnum">{formatInt(data.leads_total)}</div>
          <div className="stat-tile__sub">по всем проектам</div>
        </div>
        <div className="stat-tile elev-1">
          <div className="stat-tile__label">За месяц</div>
          <div className="stat-tile__value tnum">{formatInt(data.leads_this_month)}</div>
          <div className="stat-tile__sub">новых в этом месяце</div>
        </div>
        <div className="stat-tile elev-1">
          <div className="stat-tile__label">Конверсия</div>
          <div className="stat-tile__value tnum">
            {Math.round((data.conversion_rate || 0) * 100)}%
          </div>
          <div className="stat-tile__sub">
            {formatInt(data.won)} из {formatInt(data.won + data.lost)} закрытых
          </div>
        </div>
        <div className="stat-tile elev-1">
          <div className="stat-tile__label">В работе</div>
          <div className="stat-tile__value tnum">{formatRub(data.pipeline_value)}</div>
          <div className="stat-tile__sub">открытый pipeline</div>
        </div>
      </div>

      {/* ── Pipeline funnel by status ── */}
      <FunnelSection data={data} />

      {/* ── Sources + Team side by side on wide screens ── */}
      <div className="grid gap-5 lg:grid-cols-2">
        <SourcesSection data={data} />
        <TeamSection data={data} />
      </div>

      {/* ── Over-time bars ── */}
      <OverTimeSection data={data} />
    </div>
  );
}

/* ── Pipeline funnel (horizontal bars per stage) ──────────────────── */

function FunnelSection({ data }: { data: Dashboard }) {
  const stages = data.by_status ?? [];
  const maxCount = Math.max(1, ...stages.map((s) => s.count));

  return (
    <section className="panel-glass" style={{ padding: 18 }} aria-label="Воронка по этапам">
      <div className="eyebrow" style={{ marginBottom: 14 }}>Воронка по этапам</div>
      {stages.length === 0 ? (
        <p className="t-40" style={{ fontSize: 12.5 }}>Нет данных по этапам</p>
      ) : (
        <div className="flex flex-col gap-3">
          {stages.map((s) => {
            const label = STATUS_LABELS[s.status] ?? s.status;
            const frac = Math.max(s.count > 0 ? 0.04 : 0, s.count / maxCount);
            return (
              <div key={s.status} className="flex items-center gap-3">
                <span
                  style={{
                    fontSize: 11,
                    letterSpacing: "0.04em",
                    textTransform: "uppercase",
                    color: "var(--t-56)",
                    width: 92,
                    flex: "none",
                  }}
                >
                  {label}
                </span>
                <div
                  aria-hidden
                  style={{
                    flex: 1,
                    height: 8,
                    borderRadius: 999,
                    background: "var(--surface-3)",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${Math.round(frac * 100)}%`,
                      borderRadius: 999,
                      background: statusColor(s.status),
                      opacity: 0.85,
                      transition: "width 320ms cubic-bezier(0.4, 0, 0.2, 1)",
                    }}
                  />
                </div>
                <span
                  className="tnum"
                  style={{ fontSize: 14, color: "var(--t-100)", width: 56, textAlign: "right", flex: "none" }}
                >
                  {formatInt(s.count)}
                </span>
                <span
                  className="tnum"
                  style={{ fontSize: 11.5, color: "var(--t-56)", width: 88, textAlign: "right", flex: "none" }}
                >
                  {formatRub(s.value)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ── По источникам (horizontal bar list) ──────────────────────────── */

function SourcesSection({ data }: { data: Dashboard }) {
  const sources = data.by_source ?? [];
  const maxCount = Math.max(1, ...sources.map((s) => s.count));

  return (
    <section className="panel-glass" style={{ padding: 18 }} aria-label="По источникам">
      <div className="eyebrow" style={{ marginBottom: 14 }}>По источникам</div>
      {sources.length === 0 ? (
        <p className="t-40" style={{ fontSize: 12.5 }}>Нет данных по источникам</p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {sources.map((s) => {
            const frac = Math.max(s.count > 0 ? 0.04 : 0, s.count / maxCount);
            return (
              <div key={s.source || "—"} className="flex items-center gap-3">
                <span
                  className="truncate"
                  style={{ fontSize: 12, color: "var(--t-72)", width: 110, flex: "none" }}
                  title={sourceLabel(s.source)}
                >
                  {sourceLabel(s.source)}
                </span>
                <div
                  aria-hidden
                  style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--surface-3)", overflow: "hidden" }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${Math.round(frac * 100)}%`,
                      borderRadius: 999,
                      background: "var(--mint)",
                      opacity: 0.8,
                      transition: "width 320ms cubic-bezier(0.4, 0, 0.2, 1)",
                    }}
                  />
                </div>
                <span
                  className="tnum"
                  style={{ fontSize: 12.5, color: "var(--t-100)", width: 44, textAlign: "right", flex: "none" }}
                >
                  {formatInt(s.count)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ── Команда (table: имя · лидов · выиграно) ──────────────────────── */

function TeamSection({ data }: { data: Dashboard }) {
  const team = data.by_assignee ?? [];

  return (
    <section className="panel-glass" style={{ padding: 18 }} aria-label="Команда">
      <div className="eyebrow" style={{ marginBottom: 14 }}>Команда</div>
      {team.length === 0 ? (
        <p className="t-40" style={{ fontSize: 12.5 }}>Пока нет назначенных лидов</p>
      ) : (
        <div className="flex flex-col">
          <div
            className="flex items-center gap-3 pb-2"
            style={{ borderBottom: "1px solid var(--line)" }}
          >
            <span className="mono-cap t-40 flex-1" style={{ fontSize: 10 }}>Сотрудник</span>
            <span className="mono-cap t-40" style={{ fontSize: 10, width: 56, textAlign: "right" }}>Лидов</span>
            <span className="mono-cap t-40" style={{ fontSize: 10, width: 64, textAlign: "right" }}>Выиграно</span>
          </div>
          {team.map((m) => (
            <div
              key={m.user_id ?? "unassigned"}
              className="flex items-center gap-3 py-2"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              <span
                className="truncate flex-1"
                style={{ fontSize: 12.5, color: m.user_id ? "var(--t-100)" : "var(--t-48)" }}
                title={m.name}
              >
                {m.name}
              </span>
              <span className="tnum" style={{ fontSize: 12.5, color: "var(--t-72)", width: 56, textAlign: "right" }}>
                {formatInt(m.leads)}
              </span>
              <span
                className="tnum"
                style={{
                  fontSize: 12.5,
                  color: m.won > 0 ? "var(--mint)" : "var(--t-40)",
                  width: 64,
                  textAlign: "right",
                }}
              >
                {formatInt(m.won)}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/* ── Динамика за 14 дней (row of mini bars) ───────────────────────── */

function OverTimeSection({ data }: { data: Dashboard }) {
  const points = data.over_time ?? [];
  const maxCount = Math.max(1, ...points.map((p) => p.count));

  return (
    <section className="panel-glass" style={{ padding: 18 }} aria-label="Динамика за 14 дней">
      <div className="eyebrow" style={{ marginBottom: 14 }}>Динамика за 14 дней</div>
      {points.length === 0 ? (
        <p className="t-40" style={{ fontSize: 12.5 }}>Нет данных за период</p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${points.length}, minmax(0, 1fr))`,
            gap: 6,
            alignItems: "end",
            height: 120,
          }}
        >
          {points.map((p) => {
            const frac = p.count > 0 ? Math.max(0.06, p.count / maxCount) : 0;
            return (
              <div
                key={p.date}
                className="flex flex-col items-center justify-end gap-1.5"
                style={{ minWidth: 0, height: "100%" }}
                title={`${weekday(p.date)}: ${formatInt(p.count)}`}
              >
                <span className="tnum" style={{ fontSize: 10, color: p.count > 0 ? "var(--t-72)" : "var(--t-28)" }}>
                  {p.count > 0 ? formatInt(p.count) : ""}
                </span>
                <div
                  aria-hidden
                  style={{
                    width: "100%",
                    maxWidth: 22,
                    height: `${Math.round(frac * 100)}%`,
                    minHeight: p.count > 0 ? 3 : 0,
                    borderRadius: 5,
                    background: "var(--mint)",
                    opacity: 0.8,
                    transition: "height 320ms cubic-bezier(0.4, 0, 0.2, 1)",
                  }}
                />
                <span
                  className="tnum"
                  style={{ fontSize: 9, color: "var(--t-40)", whiteSpace: "nowrap" }}
                >
                  {weekday(p.date)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ── Loading skeleton ─────────────────────────────────────────────── */

function AnalyticsSkeleton() {
  return (
    <div className="space-y-7" aria-busy="true" aria-label="Загрузка аналитики">
      <div>
        <div className="skeleton" style={{ height: 11, width: 120, borderRadius: 4, marginBottom: 12 }} />
        <div className="skeleton" style={{ height: 44, width: 280, borderRadius: 8 }} />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="stat-tile elev-1" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="skeleton" style={{ height: 10, width: 70, borderRadius: 4 }} />
            <div className="skeleton" style={{ height: 28, width: 90, borderRadius: 6 }} />
            <div className="skeleton" style={{ height: 10, width: 80, borderRadius: 4 }} />
          </div>
        ))}
      </div>
      <section className="panel-glass" style={{ padding: 18 }}>
        <div className="skeleton" style={{ height: 11, width: 140, borderRadius: 4, marginBottom: 14 }} />
        <div className="flex flex-col gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 8, borderRadius: 999, width: "100%" }} />
          ))}
        </div>
      </section>
      <div className="grid gap-5 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <section key={i} className="panel-glass" style={{ padding: 18 }}>
            <div className="skeleton" style={{ height: 11, width: 120, borderRadius: 4, marginBottom: 14 }} />
            <div className="flex flex-col gap-2.5">
              {Array.from({ length: 5 }).map((_, j) => (
                <div key={j} className="skeleton" style={{ height: 6, borderRadius: 999, width: "100%" }} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

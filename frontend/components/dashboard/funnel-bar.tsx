"use client";

import React from "react";

import { api } from "@/lib/api";
import type { Funnel, FunnelStage, LeadStatus } from "@/lib/types";

/* ─────────────────────────────────────────────────────────────────
   FunnelBar — compact pipeline funnel for the project page.
   Renders a horizontal row of the 6 pipeline stages (label, count,
   Σ value in ₽, proportional bar) plus a summary line.

   Self-contained: safe to drop above the leads list. Fetches the
   funnel on mount and whenever projectId / refreshKey change; on any
   error it renders a muted note (never throws to the page).
───────────────────────────────────────────────────────────────── */

export type FunnelBarProps = {
  projectId: string;
  refreshKey?: number;
};

/* Stage-appropriate bar colour using theme tokens only.
   won → mint, rejected → rose, everything else → neutral track tint. */
function stageColor(stage: FunnelStage): string {
  if (stage.won || stage.key === "won") return "var(--mint)";
  if (stage.key === "rejected") return "var(--rose)";
  return "var(--t-40)";
}

/* Compact ₽ formatter (ru): 1 250 000 → «1,3 млн ₽», 48 000 → «48 тыс ₽». */
function formatRub(value: number): string {
  const v = Math.round(value || 0);
  const abs = Math.abs(v);
  if (abs >= 1_000_000) {
    const m = v / 1_000_000;
    const s = (Math.abs(m) >= 10 ? Math.round(m) : Math.round(m * 10) / 10)
      .toLocaleString("ru-RU", { maximumFractionDigits: 1 });
    return `${s} млн ₽`;
  }
  if (abs >= 10_000) {
    return `${Math.round(v / 1000).toLocaleString("ru-RU")} тыс ₽`;
  }
  return `${v.toLocaleString("ru-RU")} ₽`;
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

/* Fallback labels if the API ever omits one. */
const STAGE_LABELS: Record<LeadStatus, string> = {
  new: "Новые",
  contacted: "Связались",
  qualified: "Квалиф.",
  proposal: "КП",
  won: "Выиграно",
  rejected: "Отклонено",
};

export function FunnelBar({ projectId, refreshKey }: FunnelBarProps) {
  const [funnel, setFunnel] = React.useState<Funnel | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [errored, setErrored] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    if (!projectId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setErrored(false);
    api<Funnel>(`/crm/project/${projectId}/funnel`)
      .then((data) => {
        if (!alive) return;
        setFunnel(data);
        setLoading(false);
      })
      .catch(() => {
        if (!alive) return;
        setErrored(true);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [projectId, refreshKey]);

  // Loading skeleton — six stage placeholders.
  if (loading) {
    return (
      <section className="panel-glass" style={{ padding: 14 }} aria-busy="true" aria-label="Загрузка воронки">
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 sm:gap-2.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div className="skeleton" style={{ height: 9, borderRadius: 4, maxWidth: 56 }} />
              <div className="skeleton" style={{ height: 18, borderRadius: 4, maxWidth: 32 }} />
              <div className="skeleton" style={{ height: 6, borderRadius: 999, width: "100%" }} />
              <div className="skeleton" style={{ height: 9, borderRadius: 4, maxWidth: 44 }} />
            </div>
          ))}
        </div>
      </section>
    );
  }

  // Graceful failure — a muted, unobtrusive note (page still renders).
  if (errored || !funnel) {
    return (
      <p className="t-40" style={{ fontSize: 12, padding: "2px 2px 6px" }}>
        Воронка временно недоступна
      </p>
    );
  }

  const stages = funnel.stages ?? [];
  const maxCount = Math.max(1, ...stages.map((s) => s.count));

  return (
    <section className="panel-glass" style={{ padding: 14 }} aria-label="Воронка проекта">
      <div className="eyebrow" style={{ marginBottom: 10 }}>Воронка</div>

      {/* На <sm 6 колонок в один ряд нечитаемы (~50px на стадию при 360px),
          поэтому мобильная сетка — 3×2; с sm возвращается один ряд из 6. */}
      <div
        role="list"
        className="grid grid-cols-3 items-end gap-2 sm:grid-cols-6 sm:gap-2.5"
      >
        {stages.map((stage) => {
          const color = stageColor(stage);
          const frac = Math.max(stage.count > 0 ? 0.06 : 0, stage.count / maxCount);
          const label = stage.label || STAGE_LABELS[stage.key] || stage.key;
          return (
            <div
              key={stage.key}
              role="listitem"
              style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 5 }}
              title={`${label}: ${stage.count} · ${formatRub(stage.value)}`}
            >
              <span
                style={{
                  fontSize: 10.5,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  color: "var(--t-56)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {label}
              </span>

              <span
                className="tnum"
                style={{
                  fontSize: 19,
                  fontWeight: 300,
                  letterSpacing: "-0.02em",
                  lineHeight: 1,
                  color: stage.count > 0 ? "var(--t-100)" : "var(--t-40)",
                }}
              >
                {stage.count.toLocaleString("ru-RU")}
              </span>

              {/* Proportional bar — width ∝ count */}
              <div
                aria-hidden="true"
                style={{
                  height: 6,
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
                    background: color,
                    opacity: 0.85,
                    transition: "width 280ms cubic-bezier(0.4, 0, 0.2, 1)",
                  }}
                />
              </div>

              <span
                className="tnum"
                style={{
                  fontSize: 11,
                  color: "var(--t-56)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {formatRub(stage.value)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Summary line */}
      <div
        className="hairline"
        style={{
          marginTop: 12,
          paddingTop: 10,
          fontSize: 12.5,
          color: "var(--t-72)",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "baseline",
          gap: "4px 7px",
          lineHeight: 1.5,
        }}
      >
        <span>
          В работе:{" "}
          <span className="tnum" style={{ color: "var(--t-100)" }}>
            {funnel.open_leads.toLocaleString("ru-RU")}
          </span>{" "}
          {plural(funnel.open_leads, "лид", "лида", "лидов")}
        </span>
        <span style={{ color: "var(--t-28)" }}>·</span>
        <span className="tnum">{formatRub(funnel.open_value)}</span>

        <span style={{ color: "var(--t-28)", margin: "0 2px" }}>·</span>

        <span>
          Выиграно:{" "}
          <span className="tnum" style={{ color: "var(--mint)" }}>
            {funnel.won_count.toLocaleString("ru-RU")}
          </span>
        </span>
        <span style={{ color: "var(--t-28)" }}>·</span>
        <span className="tnum" style={{ color: "var(--mint)" }}>{formatRub(funnel.won_value)}</span>

        <span style={{ color: "var(--t-28)", margin: "0 2px" }}>·</span>

        <span>
          Конверсия:{" "}
          <span className="tnum" style={{ color: "var(--t-100)" }}>
            {Math.round((funnel.conversion_rate || 0) * 100)}%
          </span>
        </span>
      </div>
    </section>
  );
}

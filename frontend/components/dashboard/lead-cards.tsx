"use client";

import React, { useMemo } from "react";
import { Mail, Phone } from "lucide-react";

import { LeadDetailDrawer } from "@/components/dashboard/lead-detail-drawer";
import type { Lead } from "@/lib/types";

/* ─────────────────────────────────────────────────────────────────
   Constants
───────────────────────────────────────────────────────────────── */

const STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  proposal: "КП отправлено",
  won: "Сделка",
  rejected: "Отказ",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
  new: "badge--new",
  contacted: "badge--contacted",
  qualified: "badge--qualified",
  proposal: "badge--proposal",
  won: "badge--won",
  rejected: "badge--rejected",
};

const SOURCE_LABELS: Record<string, string> = {
  yandex_maps: "Яндекс Карты",
  "2gis": "2ГИС",
  rusprofile: "ЕГРЮЛ",
  maps_searxng: "Я.Карты (web)",
  searxng: "Web",
  yandex_search: "Web",
  bing: "Bing",
  warehouse: "Наша база",
  manual: "Вручную",
};

/* ─────────────────────────────────────────────────────────────────
   ScoreBar (inline, compact)
───────────────────────────────────────────────────────────────── */
function ScoreBar({ score }: { score: number }) {
  const frac = Math.max(0, Math.min(100, score)) / 100;
  return (
    <div className="score-bar score-bar--sm" style={{ "--score": frac } as React.CSSProperties} aria-label={`Score ${score}`}>
      <div className="score-bar__fill" />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Single LeadCard
───────────────────────────────────────────────────────────────── */
type LeadCardProps = {
  lead: Lead;
  onClick: () => void;
};

function scoreColor(score: number): string {
  if (score >= 80) return "var(--mint)";
  if (score >= 60) return "rgba(232,196,128,0.92)";
  return "var(--t-48)";
}

function LeadCard({ lead, onClick }: LeadCardProps) {
  const isAccent = lead.score >= 80;
  const httpSite =
    lead.website && /^https?:\/\//i.test(lead.website) ? lead.website : "";
  const domain =
    lead.domain || (httpSite ? httpSite.replace(/^https?:\/\//i, "").split("/")[0] : "");
  const statusBadgeClass = STATUS_BADGE_CLASS[lead.status] ?? "";
  const sourceLabel = lead.source ? (SOURCE_LABELS[lead.source] ?? lead.source) : null;
  const subtitle = [domain, lead.city].filter(Boolean).join("  ·  ") || "—";

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      className={`lead-card animate-lift-in${isAccent ? " lead-card--accent" : ""}`}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      aria-label={`Открыть детали: ${lead.company}`}
    >
      {/* Header: name + score */}
      <div className="lead-card__row">
        <span className="lead-card__name flex-1" title={lead.company}>
          {lead.company}
        </span>
        <span className="lead-card__score" style={{ color: scoreColor(lead.score) }} aria-label={`Score ${lead.score}`}>
          {lead.score}
        </span>
      </div>

      {/* Subtitle: domain · city (always one line) */}
      <div className="lead-card__sub" title={subtitle}>
        {subtitle}
      </div>

      {/* Score bar — own full-width row */}
      <div className="lead-card__scorewrap">
        <ScoreBar score={lead.score} />
      </div>

      {/* Badges — status + source, single line */}
      <div className="lead-card__badges">
        <span className={`badge ${statusBadgeClass}`}>
          {STATUS_LABELS[lead.status] ?? lead.status}
        </span>
        {sourceLabel && <span className="badge badge--source">{sourceLabel}</span>}
        {lead.tags?.includes("есть сайт") && (
          <span
            className="badge"
            style={{
              background: "rgba(168, 197, 192, 0.12)",
              borderColor: "rgba(168, 197, 192, 0.32)",
              color: "var(--mint)",
            }}
          >
            есть сайт
          </span>
        )}
      </div>

      <hr className="lead-card__divider" />

      {/* Contacts — always two rows so every card is the same height */}
      <div className="lead-card__contacts">
        <span
          className={`lead-card__contact${
            lead.email ? (lead.email_status === "valid" ? " lead-card__contact--valid" : "") : " lead-card__contact--empty"
          }`}
          title={lead.email || undefined}
        >
          <Mail size={11} />
          <span>{lead.email || "—"}</span>
        </span>
        <span
          className={`lead-card__contact${lead.phone ? "" : " lead-card__contact--empty"}`}
          title={lead.phone || undefined}
        >
          <Phone size={11} />
          <span className="font-mono">{lead.phone || "—"}</span>
        </span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Skeleton card for loading state
───────────────────────────────────────────────────────────────── */
function SkeletonCard() {
  return (
    <div className="lead-card" aria-hidden="true">
      <div className="lead-card__row">
        <div className="skeleton flex-1" style={{ height: 14, borderRadius: 6, maxWidth: 150 }} />
        <div className="skeleton" style={{ width: 22, height: 12, borderRadius: 4 }} />
      </div>
      <div className="lead-card__sub">
        <div className="skeleton" style={{ height: 11, borderRadius: 4, maxWidth: 110 }} />
      </div>
      <div className="lead-card__scorewrap">
        <div className="skeleton" style={{ width: "100%", height: 4, borderRadius: 999 }} />
      </div>
      <div className="lead-card__badges">
        <div className="skeleton" style={{ width: 96, height: 20, borderRadius: 999 }} />
        <div className="skeleton" style={{ width: 48, height: 20, borderRadius: 999 }} />
      </div>
      <hr className="lead-card__divider" />
      <div className="lead-card__contacts">
        <div className="skeleton" style={{ height: 11, borderRadius: 4, maxWidth: 150 }} />
        <div className="skeleton" style={{ height: 11, borderRadius: 4, maxWidth: 110 }} />
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   LeadCards — the grid view
───────────────────────────────────────────────────────────────── */
export type LeadCardsProps = {
  leads: Lead[];
  loading?: boolean;
  onLeadUpdate?: (leadId: string, patch: Partial<Lead>) => void;
};

export function LeadCards({ leads, loading = false, onLeadUpdate }: LeadCardsProps) {
  const [openLeadId, setOpenLeadId] = React.useState<string | null>(null);

  const handleClose = React.useCallback(() => setOpenLeadId(null), []);

  const displayLeads = useMemo(() => leads, [leads]);

  if (loading) {
    return (
      <>
        <div
          className="lead-cards-grid grid gap-3"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          }}
          aria-busy="true"
          aria-label="Загрузка лидов"
        >
          {Array.from({ length: 9 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
        <LeadDetailDrawer leadId={null} onClose={handleClose} onLeadUpdate={onLeadUpdate} />
      </>
    );
  }

  if (displayLeads.length === 0) {
    return (
      <>
        <div className="empty-state panel-flat">
          <svg
            className="empty-state__icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.4}
            aria-hidden="true"
          >
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span className="empty-state__title">Нет лидов по текущим фильтрам</span>
          <span className="empty-state__body">
            Попробуйте изменить фильтры или запустите новый сбор
          </span>
        </div>
        <LeadDetailDrawer leadId={null} onClose={handleClose} onLeadUpdate={onLeadUpdate} />
      </>
    );
  }

  return (
    <>
      <div
        className="lead-cards-grid grid gap-3"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
        }}
        role="list"
        aria-label="Список лидов"
      >
        {displayLeads.map((lead) => (
          <div key={lead.id} role="listitem" className="h-full">
            <LeadCard
              lead={lead}
              onClick={() => setOpenLeadId(lead.id)}
            />
          </div>
        ))}
      </div>

      <LeadDetailDrawer
        leadId={openLeadId}
        onClose={handleClose}
        onLeadUpdate={onLeadUpdate}
      />
    </>
  );
}

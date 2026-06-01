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
  contacted: "Контакт",
  qualified: "Квалифицирован",
  rejected: "Отклонён",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
  new: "badge--new",
  contacted: "badge--contacted",
  qualified: "badge--qualified",
  rejected: "badge--rejected",
};

const SOURCE_LABELS: Record<string, string> = {
  yandex_maps: "Яндекс Карты",
  "2gis": "2ГИС",
  rusprofile: "ЕГРЮЛ",
  maps_searxng: "Я.Карты (web)",
  searxng: "Web",
  bing: "Bing",
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

function LeadCard({ lead, onClick }: LeadCardProps) {
  const isAccent = lead.score >= 80;
  const domain = lead.domain || (lead.website ? lead.website.replace(/^https?:\/\//, "").split("/")[0] : "");
  const statusBadgeClass = STATUS_BADGE_CLASS[lead.status] ?? "";
  const sourceLabel = lead.source ? (SOURCE_LABELS[lead.source] ?? lead.source) : null;

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
      {/* Row 1: name + score */}
      <div className="lead-card__row">
        <span className="lead-card__name flex-1 truncate" title={lead.company}>
          {lead.company}
        </span>
        <span
          className="font-mono tnum shrink-0 text-[11px]"
          style={{ color: isAccent ? "var(--mint)" : "rgba(255,255,255,0.48)" }}
          aria-label={`Score ${lead.score}`}
        >
          {lead.score}
        </span>
      </div>

      {/* Row 2: domain · city */}
      {(domain || lead.city) && (
        <div className="lead-card__row mt-1">
          <span className="lead-card__sub flex-1 truncate">
            {domain && <span>{domain}</span>}
            {domain && lead.city && <span className="mx-1 opacity-40">·</span>}
            {lead.city && <span>{lead.city}</span>}
          </span>
        </div>
      )}

      {/* Score bar */}
      <div className="lead-card__meta">
        <ScoreBar score={lead.score} />
        <span className={`badge ${statusBadgeClass}`}>
          {STATUS_LABELS[lead.status] ?? lead.status}
        </span>
        {sourceLabel && (
          <span className="badge badge--source">
            {sourceLabel}
          </span>
        )}
      </div>

      {/* Contact indicators */}
      <div className="lead-card__meta" style={{ marginTop: 6 }}>
        {lead.email && (
          <span
            className="inline-flex items-center gap-1 text-[11px]"
            style={{ color: lead.email_status === "valid" ? "var(--green)" : "rgba(255,255,255,0.48)" }}
            title={lead.email}
          >
            <Mail size={10} />
            <span className="truncate max-w-[120px]">{lead.email}</span>
          </span>
        )}
        {lead.phone && (
          <span
            className="inline-flex items-center gap-1 text-[11px]"
            style={{ color: "rgba(255,255,255,0.48)" }}
            title={lead.phone}
          >
            <Phone size={10} />
            <span className="font-mono truncate max-w-[100px]">{lead.phone}</span>
          </span>
        )}
        {!lead.email && !lead.phone && (
          <span className="t-40 text-[11px]">нет контактов</span>
        )}
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
        <div className="skeleton flex-1" style={{ height: 14, borderRadius: 6, maxWidth: 160 }} />
        <div className="skeleton" style={{ width: 24, height: 12, borderRadius: 4 }} />
      </div>
      <div className="lead-card__row mt-1">
        <div className="skeleton flex-1" style={{ height: 12, borderRadius: 4, maxWidth: 100 }} />
      </div>
      <div className="lead-card__meta">
        <div className="skeleton" style={{ width: 56, height: 3, borderRadius: 999 }} />
        <div className="skeleton" style={{ width: 64, height: 20, borderRadius: 999 }} />
      </div>
      <div className="lead-card__meta" style={{ marginTop: 6 }}>
        <div className="skeleton" style={{ width: 110, height: 12, borderRadius: 4 }} />
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
          className="grid gap-3"
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
        className="grid gap-3"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
        }}
        role="list"
        aria-label="Список лидов"
      >
        {displayLeads.map((lead) => (
          <div key={lead.id} role="listitem">
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

"use client";

import React, { useMemo, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { Lead, LeadStatus, OrgMember } from "@/lib/types";

/* ─────────────────────────────────────────────────────────────────
   Pipeline definition — 6 ordered stages with Russian labels
───────────────────────────────────────────────────────────────── */

type StageDef = {
  key: LeadStatus;
  label: string;
};

const STAGES: StageDef[] = [
  { key: "new", label: "Новый" },
  { key: "contacted", label: "Связались" },
  { key: "qualified", label: "Квалифицирован" },
  { key: "proposal", label: "КП отправлено" },
  { key: "won", label: "Сделка" },
  { key: "rejected", label: "Отказ" },
];

/* Map each stage to a reusable badge class where one exists; proposal/won
   have no badge--* variant in globals.css, so they fall back to an
   inline token-based accent (amber for proposal, mint for won). */
const STAGE_BADGE_CLASS: Partial<Record<LeadStatus, string>> = {
  new: "badge--new",
  contacted: "badge--contacted",
  qualified: "badge--qualified",
  rejected: "badge--rejected",
};

/* Accent colour per stage — drives the column header dot + drop highlight.
   Tokens only, so both themes stay correct. */
const STAGE_ACCENT: Record<LeadStatus, string> = {
  new: "var(--sky)",
  contacted: "var(--mint)",
  qualified: "var(--green)",
  proposal: "var(--amber)",
  won: "var(--mint)",
  rejected: "var(--rose)",
};

/* ─────────────────────────────────────────────────────────────────
   Formatting helpers
───────────────────────────────────────────────────────────────── */

/** Format ₽ amount: large sums collapse to "1,2 млн ₽", else grouped. */
function formatRub(value: number): string {
  if (value >= 1_000_000) {
    const millions = value / 1_000_000;
    // 1 decimal, RU comma; drop trailing ",0"
    const text = millions
      .toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 1 });
    return `${text} млн ₽`;
  }
  return `${value.toLocaleString("ru-RU")} ₽`;
}

/** Initials from a full name: "Иван Петров" → "ИП"; fallback to "—". */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "—";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function scoreColor(score: number): string {
  if (score >= 80) return "var(--mint)";
  if (score >= 60) return "var(--amber)";
  return "var(--t-48)";
}

/* ─────────────────────────────────────────────────────────────────
   Card
───────────────────────────────────────────────────────────────── */

type CardProps = {
  lead: Lead;
  memberName: string | null;
  onOpen: (id: string) => void;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  dragging: boolean;
};

function PipelineCard({ lead, memberName, onOpen, onDragStart, onDragEnd, dragging }: CardProps) {
  const value = lead.deal_value ?? 0;
  const assigneeInitials = memberName ? initials(memberName) : "—";

  return (
    <div
      draggable
      role="button"
      tabIndex={0}
      className="lead-card animate-lift-in"
      style={{
        cursor: "grab",
        opacity: dragging ? 0.4 : 1,
        gap: 8,
        padding: 12,
      }}
      onClick={() => onOpen(lead.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(lead.id);
        }
      }}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", lead.id);
        onDragStart(lead.id);
      }}
      onDragEnd={onDragEnd}
      aria-label={`Открыть лид: ${lead.company}`}
    >
      {/* Company + score */}
      <div className="lead-card__row">
        <span
          className="lead-card__name flex-1"
          title={lead.company}
          onClick={(e) => {
            e.stopPropagation();
            onOpen(lead.id);
          }}
        >
          {lead.company}
        </span>
        <span
          className="lead-card__score"
          style={{ color: scoreColor(lead.score) }}
          aria-label={`Оценка ${lead.score}`}
        >
          {lead.score}
        </span>
      </div>

      {/* City (muted) */}
      {lead.city && (
        <div className="lead-card__sub" title={lead.city}>
          {lead.city}
        </div>
      )}

      {/* Footer: assignee + deal value */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          marginTop: 2,
        }}
      >
        <span
          className="chip chip-sans"
          title={memberName ?? "Не назначен"}
          style={{ padding: "3px 8px", fontSize: 11, gap: 5 }}
        >
          <span
            aria-hidden="true"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 18,
              height: 18,
              borderRadius: "50%",
              background: memberName ? "rgba(168, 197, 192, 0.16)" : "var(--surface-3)",
              color: memberName ? "var(--mint)" : "var(--t-48)",
              fontSize: 9,
              fontWeight: 600,
              fontFamily: "'Geist Mono', monospace",
              letterSpacing: 0,
            }}
          >
            {assigneeInitials}
          </span>
          <span style={{ color: "var(--t-72)" }}>{memberName ? assigneeInitials : "—"}</span>
        </span>

        {value > 0 && (
          <span
            className="tnum"
            style={{
              fontSize: 11.5,
              fontWeight: 600,
              color: "var(--green)",
              whiteSpace: "nowrap",
            }}
          >
            {formatRub(value)}
          </span>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Board
───────────────────────────────────────────────────────────────── */

export type PipelineBoardProps = {
  leads: Lead[];
  members: OrgMember[];
  onLeadUpdate: (id: string, patch: Partial<Lead>) => void;
  onOpenLead: (id: string) => void;
  orgRole?: string;
};

export function PipelineBoard({
  leads,
  members,
  onLeadUpdate,
  onOpenLead,
}: PipelineBoardProps) {
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverStage, setDragOverStage] = useState<LeadStatus | null>(null);

  const memberById = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of members) map.set(m.user_id, m.full_name || m.email);
    return map;
  }, [members]);

  // Group leads by stage, preserving incoming order.
  const byStage = useMemo(() => {
    const groups: Record<LeadStatus, Lead[]> = {
      new: [],
      contacted: [],
      qualified: [],
      proposal: [],
      won: [],
      rejected: [],
    };
    for (const lead of leads) {
      const s = lead.status;
      if (s in groups) groups[s].push(lead);
      else groups.new.push(lead);
    }
    return groups;
  }, [leads]);

  const handleDrop = async (targetStage: LeadStatus, leadId: string) => {
    setDragOverStage(null);
    setDraggingId(null);

    const lead = leads.find((l) => l.id === leadId);
    if (!lead) return;
    const prevStatus = lead.status;
    if (prevStatus === targetStage) return;

    // Optimistic update.
    onLeadUpdate(leadId, { status: targetStage });

    try {
      await api<Lead>(`/leads/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: targetStage }),
      });
    } catch (err) {
      // Revert on failure.
      onLeadUpdate(leadId, { status: prevStatus });
      const reason = err instanceof Error ? err.message : "неизвестная ошибка";
      toast.error(`Не удалось перенести лид: ${reason}`);
    }
  };

  return (
    <div
      className="pipeline-board"
      style={{
        display: "flex",
        gap: 12,
        overflowX: "auto",
        paddingBottom: 8,
        // smooth horizontal scroll on narrow screens
        scrollSnapType: "x proximity",
      }}
      role="list"
      aria-label="Воронка продаж"
    >
      {STAGES.map((stage) => {
        const stageLeads = byStage[stage.key];
        const count = stageLeads.length;
        const sum = stageLeads.reduce((acc, l) => acc + (l.deal_value ?? 0), 0);
        const isOver = dragOverStage === stage.key;
        const accent = STAGE_ACCENT[stage.key];
        const badgeClass = STAGE_BADGE_CLASS[stage.key];

        return (
          <section
            key={stage.key}
            role="listitem"
            aria-label={`${stage.label}: ${count}`}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              if (dragOverStage !== stage.key) setDragOverStage(stage.key);
            }}
            onDragLeave={(e) => {
              // Only clear when leaving the column entirely.
              if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                setDragOverStage((cur) => (cur === stage.key ? null : cur));
              }
            }}
            onDrop={(e) => {
              e.preventDefault();
              const id = e.dataTransfer.getData("text/plain") || draggingId;
              if (id) void handleDrop(stage.key, id);
            }}
            className="panel-glass"
            style={{
              display: "flex",
              flexDirection: "column",
              flex: "0 0 280px",
              width: 280,
              maxHeight: "100%",
              borderRadius: 14,
              padding: 0,
              scrollSnapAlign: "start",
              background: isOver ? "var(--surface-2)" : "var(--surface-1)",
              border: isOver
                ? `1px solid ${accent}`
                : "1px solid var(--line)",
              boxShadow: isOver ? `inset 0 0 0 1px ${accent}` : "none",
              transition: "background 120ms ease, border-color 120ms ease, box-shadow 120ms ease",
            }}
          >
            {/* Header */}
            <header
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "12px 14px 10px",
                borderBottom: "1px solid var(--line)",
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: accent,
                  flex: "none",
                }}
              />
              {badgeClass ? (
                <span className={`badge ${badgeClass}`}>{stage.label}</span>
              ) : (
                <span
                  className="badge"
                  style={{
                    background:
                      stage.key === "won"
                        ? "rgba(168, 197, 192, 0.12)"
                        : "rgba(251, 191, 36, 0.12)",
                    borderColor:
                      stage.key === "won"
                        ? "rgba(168, 197, 192, 0.30)"
                        : "rgba(251, 191, 36, 0.30)",
                    color: stage.key === "won" ? "var(--mint)" : "var(--amber)",
                  }}
                >
                  {stage.label}
                </span>
              )}
              <span
                className="tnum"
                style={{
                  marginLeft: "auto",
                  fontSize: 12,
                  fontWeight: 600,
                  color: "var(--t-72)",
                }}
                aria-label={`${count} лидов`}
              >
                {count}
              </span>
            </header>

            {/* Σ deal value */}
            <div
              style={{
                padding: "7px 14px",
                fontSize: 11,
                letterSpacing: "0.04em",
                color: sum > 0 ? "var(--t-72)" : "var(--t-40)",
                borderBottom: "1px solid var(--line)",
              }}
            >
              <span className="tnum">{sum > 0 ? formatRub(sum) : "—"}</span>
            </div>

            {/* Cards */}
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
                padding: 10,
                overflowY: "auto",
                flex: 1,
                minHeight: 120,
              }}
            >
              {count === 0 ? (
                <div
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minHeight: 90,
                    borderRadius: 10,
                    border: `1px dashed ${isOver ? accent : "var(--line-2)"}`,
                    color: "var(--t-40)",
                    fontSize: 12,
                    textAlign: "center",
                    padding: 12,
                    transition: "border-color 120ms ease",
                  }}
                >
                  {isOver ? "Отпустите здесь" : "Нет лидов"}
                </div>
              ) : (
                stageLeads.map((lead) => (
                  <PipelineCard
                    key={lead.id}
                    lead={lead}
                    memberName={
                      lead.assigned_to_user_id
                        ? memberById.get(lead.assigned_to_user_id) ?? null
                        : null
                    }
                    onOpen={onOpenLead}
                    onDragStart={setDraggingId}
                    onDragEnd={() => {
                      setDraggingId(null);
                      setDragOverStage(null);
                    }}
                    dragging={draggingId === lead.id}
                  />
                ))
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export default PipelineBoard;

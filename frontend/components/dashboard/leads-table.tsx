"use client";

import { KeyboardEvent, useMemo, useState } from "react";
import { ArrowDownUp, ExternalLink, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/glass-card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import type { Lead } from "@/lib/types";

const SCORE_HIGH = 75;
const SCORE_MEDIUM = 50;

type Props = {
  leads: Lead[];
  loading?: boolean;
  onBulkEnrich: (leadIds: string[]) => Promise<boolean>;
  canBulkEnrich?: boolean;
  hideInternalFilters?: boolean;
  onLeadUpdate?: (leadId: string, patch: Partial<Lead>) => void;
  onLeadDelete?: (leadId: string) => void;
};

const STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  rejected: "Отклонён",
};

type StatusVariant = "default" | "online" | "brand" | "offline";
type StatusDot = "online" | "offline" | "warning" | undefined;

const STATUS_VARIANTS: Record<string, StatusVariant> = {
  new: "default",
  contacted: "online",
  qualified: "brand",
  rejected: "offline",
};

const STATUS_DOTS: Record<string, StatusDot> = {
  new: undefined,
  contacted: "online",
  qualified: undefined,
  rejected: "offline",
};

const STATUS_OPTIONS: { value: Lead["status"]; label: string }[] = [
  { value: "new", label: "Новый" },
  { value: "contacted", label: "Связались" },
  { value: "qualified", label: "Квалифицирован" },
  { value: "rejected", label: "Отклонён" },
];

const SOURCE_META: Record<string, { label: string; emoji: string; color: string }> = {
  yandex_maps: { label: "Яндекс Карты", emoji: "🅉", color: "text-status-offline" },
  "2gis": { label: "2ГИС", emoji: "②", color: "text-status-online" },
  rusprofile: { label: "ЕГРЮЛ (rusprofile)", emoji: "📋", color: "text-white/[0.72]" },
  maps_searxng: { label: "Яндекс Карты (web)", emoji: "🅉", color: "text-status-offline" },
  searxng: { label: "Web-поиск", emoji: "🌐", color: "text-white/[0.56]" },
  bing: { label: "Bing", emoji: "🅱", color: "text-white/[0.56]" },
};

function SourceBadge({ source, externalId }: { source?: string; externalId?: string }) {
  if (!source) return null;
  const meta = SOURCE_META[source];
  if (!meta) return null;
  const titleExt = externalId ? `${meta.label} · id ${externalId}` : meta.label;
  const href =
    source === "rusprofile" && externalId
      ? `https://www.rusprofile.ru/id/${externalId}`
      : null;
  const content = (
    <span
      title={titleExt}
      className={`inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded px-1 text-[9px] font-semibold ${meta.color}`}
    >
      {meta.emoji}
    </span>
  );
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" className="hover:opacity-80">
      {content}
    </a>
  ) : (
    content
  );
}

function EmailStatusBadge({ status }: { status?: string }) {
  if (!status || status === "skipped") return null;
  if (status === "valid") {
    return (
      <span
        title="Email доставляемый (MX-запись найдена)"
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-status-online/15 text-[10px] text-status-online"
        aria-label="email verified"
      >
        ✓
      </span>
    );
  }
  if (status === "no_mx" || status === "syntax") {
    return (
      <span
        title={
          status === "no_mx"
            ? "У домена нет MX-записи — письма не дойдут"
            : "Email синтаксически некорректен"
        }
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-status-offline/15 text-[10px] text-status-offline"
        aria-label="email invalid"
      >
        !
      </span>
    );
  }
  return null;
}

function TruncatedCell({ value, className = "" }: { value: string | null | undefined; className?: string }) {
  if (!value) return <span className="text-white/[0.40]">—</span>;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={<span className={`block max-w-full cursor-default truncate ${className}`} />}
        >
          {value}
        </TooltipTrigger>
        <TooltipContent>{value}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function ScoreIndicator({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 w-20 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full bg-brand transition-[width] duration-300"
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums text-white/[0.72]">{score}</span>
    </div>
  );
}

function NotesRow({ lead, onLeadUpdate }: { lead: Lead; onLeadUpdate?: (leadId: string, patch: Partial<Lead>) => void }) {
  const [notes, setNotes] = useState(lead.notes ?? "");
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const tags = lead.tags ?? [];

  const patchLead = async (patch: Partial<Lead> & { mark_contacted?: boolean }) => {
    setSaving(true);
    try {
      const updated = await api<Lead>(`/leads/${lead.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      onLeadUpdate?.(lead.id, updated);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const saveNotes = async () => {
    if (notes === (lead.notes ?? "")) return;
    await patchLead({ notes });
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void saveNotes();
    }
  };

  const addTag = async () => {
    const t = tagInput.trim();
    if (!t || tags.includes(t)) { setTagInput(""); return; }
    const newTags = [...tags, t];
    setTagInput("");
    await patchLead({ tags: newTags });
  };

  const removeTag = async (t: string) => {
    await patchLead({ tags: tags.filter((x) => x !== t) });
  };

  const setReminder = async (days: number | null) => {
    if (days === null) {
      await patchLead({ reminder_at: null });
      return;
    }
    const d = new Date();
    d.setDate(d.getDate() + days);
    d.setHours(10, 0, 0, 0); // 10am that day
    await patchLead({ reminder_at: d.toISOString() });
  };

  const reminderDateStr = lead.reminder_at ? new Date(lead.reminder_at).toLocaleDateString("ru-RU") : null;
  const lastContactStr = lead.last_contacted_at ? new Date(lead.last_contacted_at).toLocaleDateString("ru-RU") : null;
  const reminderOverdue = lead.reminder_at && new Date(lead.reminder_at) < new Date();

  return (
    <TableRow className="border-b border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.02]">
      <TableCell colSpan={11} className="px-4 py-4 sm:px-8">
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Notes */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Заметка</span>
            <Input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => void saveNotes()}
              onKeyDown={handleKeyDown}
              placeholder="Контекст переговоров, кто принимает решение..."
              className="h-9 text-sm"
              disabled={saving}
            />
          </div>
          {/* Tags */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Теги</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {tags.map((t) => (
                <Badge
                  key={t}
                  variant="default"
                  className="cursor-pointer text-xs"
                  render={<button type="button" onClick={() => void removeTag(t)} />}
                >
                  {t} ✕
                </Badge>
              ))}
              <Input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addTag(); } }}
                placeholder="+ тег"
                className="h-8 w-28 text-xs"
                disabled={saving}
              />
            </div>
          </div>
          {/* Workflow actions */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Действия</span>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Button size="sm" variant="brand" disabled={saving} onClick={() => void patchLead({ mark_contacted: true })}>
                ✓ Связались сейчас
              </Button>
              {lastContactStr && (
                <span className="text-white/[0.48]">последний контакт: {lastContactStr}</span>
              )}
            </div>
          </div>
          {/* Reminder */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Напоминание</span>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <Button size="sm" variant="secondary" disabled={saving} onClick={() => void setReminder(1)}>+1д</Button>
              <Button size="sm" variant="secondary" disabled={saving} onClick={() => void setReminder(3)}>+3д</Button>
              <Button size="sm" variant="secondary" disabled={saving} onClick={() => void setReminder(7)}>+7д</Button>
              <Button size="sm" variant="secondary" disabled={saving} onClick={() => void setReminder(14)}>+14д</Button>
              {reminderDateStr && (
                <>
                  <span className={reminderOverdue ? "font-medium text-status-offline" : "text-white/[0.48]"}>
                    напомнить {reminderDateStr}{reminderOverdue && " (просрочено)"}
                  </span>
                  <Button size="icon-xs" variant="ghost" disabled={saving} onClick={() => void setReminder(null)}>×</Button>
                </>
              )}
            </div>
          </div>
        </div>
      </TableCell>
    </TableRow>
  );
}

export function LeadsTable({
  leads,
  loading = false,
  onBulkEnrich,
  canBulkEnrich = true,
  hideInternalFilters = false,
  onLeadUpdate,
  onLeadDelete,
}: Props) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | Lead["status"]>("all");
  const [scoreSort, setScoreSort] = useState<"desc" | "asc">("desc");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [runningBulk, setRunningBulk] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (hideInternalFilters) return leads;
    const q = query.toLowerCase().trim();
    return leads
      .filter((lead) => (statusFilter === "all" ? true : lead.status === statusFilter))
      .filter((lead) =>
        q
          ? [lead.company, lead.domain, lead.city, lead.email, lead.phone]
              .filter(Boolean).join(" ").toLowerCase().includes(q)
          : true
      )
      .sort((a, b) => (scoreSort === "desc" ? b.score - a.score : a.score - b.score));
  }, [leads, query, statusFilter, scoreSort, hideInternalFilters]);

  const allVisibleSelected = filtered.length > 0 && filtered.every((l) => selectedIds.includes(l.id));

  const toggleAll = () => {
    if (allVisibleSelected) {
      setSelectedIds((prev) => prev.filter((id) => !filtered.find((l) => l.id === id)));
      return;
    }
    setSelectedIds((prev) => {
      const set = new Set(prev);
      filtered.forEach((l) => set.add(l.id));
      return [...set];
    });
  };

  const runBulk = async () => {
    if (selectedIds.length === 0) return;
    setRunningBulk(true);
    try {
      const success = await onBulkEnrich(selectedIds);
      if (success) setSelectedIds([]);
    } finally {
      setRunningBulk(false);
    }
  };

  const changeStatus = async (leadId: string, newStatus: Lead["status"]) => {
    onLeadUpdate?.(leadId, { status: newStatus });
    try {
      await api(`/leads/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus }),
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить статус");
    }
  };

  const deleteLead = async (leadId: string) => {
    onLeadDelete?.(leadId);
    try {
      await api(`/leads/${leadId}`, { method: "DELETE" });
      toast.success("Лид удалён");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось удалить лид");
    }
  };

  const handleRowClick = (leadId: string, e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (
      target.closest("a") ||
      target.closest("button") ||
      target.closest("input") ||
      target.closest("[data-slot]") ||
      target.tagName === "INPUT"
    ) {
      return;
    }
    setExpandedId((prev) => (prev === leadId ? null : leadId));
  };

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="h-11 animate-pulse rounded-2xl border border-white/[0.08] bg-white/[0.03]" />
        <div className="h-56 animate-pulse rounded-2xl border border-white/[0.08] bg-white/[0.03]" />
      </div>
    );
  }

  if (leads.length === 0) {
    return (
      <GlassCard variant="default" className="p-8 text-center">
        <h3 className="text-base font-medium text-white">Лидов пока нет</h3>
        <p className="mt-1 text-sm text-white/[0.48]">Запустите сбор, чтобы заполнить таблицу.</p>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-3">
      {!hideInternalFilters && (
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-3 backdrop-blur-xl">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по компании, домену, email..."
            className="w-full sm:w-64"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "all" | Lead["status"])}
            className="h-9 rounded-xl border border-white/[0.10] bg-white/[0.05] px-3 text-sm text-white outline-none backdrop-blur-xl transition-colors focus:border-white/[0.24] focus:bg-white/[0.08]"
          >
            <option value="all">Все статусы</option>
            <option value="new">Новый</option>
            <option value="contacted">Связались</option>
            <option value="qualified">Квалифицирован</option>
            <option value="rejected">Отклонён</option>
          </select>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setScoreSort((p) => (p === "desc" ? "asc" : "desc"))}
          >
            <ArrowDownUp size={13} className="mr-1" />
            Score {scoreSort === "desc" ? "↓" : "↑"}
          </Button>
        </div>
      )}

      {selectedIds.length > 0 && (
        <div className="flex items-center gap-2">
          <Button size="sm" variant="brand" disabled={!canBulkEnrich || runningBulk} onClick={runBulk}>
            <Sparkles size={13} className="mr-1" />
            {runningBulk ? "Обогащаем..." : `Обогатить выбранные (${selectedIds.length})`}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedIds([])}
          >
            Снять выбор
          </Button>
        </div>
      )}

      {/* Mobile: card view (md:hidden). Each lead shows ALL fields stacked
          so users on phones can see phone/email/address without horizontal scroll. */}
      <div className="space-y-2 md:hidden">
        {filtered.length === 0 && (
          <GlassCard variant="default" className="px-4 py-6 text-center">
            <p className="text-sm text-white/[0.48]">Нет лидов по текущим фильтрам.</p>
          </GlassCard>
        )}
        {filtered.map((lead) => {
          const isSelected = selectedIds.includes(lead.id);
          const domain = lead.domain || (lead.website ? lead.website.replace(/^https?:\/\//, "").split("/")[0] : "");
          const statusVariant = STATUS_VARIANTS[lead.status] ?? "default";
          const statusDot = STATUS_DOTS[lead.status];
          return (
            <GlassCard key={lead.id} variant="default" className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-2">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(e) => setSelectedIds((prev) =>
                      e.target.checked ? [...new Set([...prev, lead.id])] : prev.filter((id) => id !== lead.id)
                    )}
                    className="mt-1 h-4 w-4 cursor-pointer rounded"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 break-words text-sm font-medium text-white">
                      <SourceBadge source={lead.source} externalId={lead.external_id} />
                      <span>{lead.company}</span>
                    </p>
                    {lead.city && <p className="mt-0.5 text-xs text-white/[0.48]">{lead.city}</p>}
                  </div>
                </div>
                <div className="shrink-0">
                  <ScoreIndicator score={lead.score} />
                </div>
              </div>
              <div className="space-y-1.5 text-xs">
                {lead.phone && (
                  <a href={`tel:${lead.phone}`} className="block text-white underline decoration-white/30 underline-offset-2 hover:decoration-white">
                    📞 {lead.phone}
                  </a>
                )}
                {lead.email && (
                  <a href={`mailto:${lead.email}`} className="block break-all text-white underline decoration-white/30 underline-offset-2 hover:decoration-white">
                    ✉️ {lead.email}
                  </a>
                )}
                {lead.address && (
                  <p className="text-white/[0.56]">📍 {lead.address}</p>
                )}
                {domain && lead.website && /^https?:\/\//i.test(lead.website) && (
                  <a href={lead.website} target="_blank" rel="noopener noreferrer" className="block truncate text-white underline decoration-white/30 underline-offset-2 hover:decoration-white">
                    🌐 {domain}
                  </a>
                )}
              </div>
              <div className="flex items-center justify-between pt-1">
                <Badge variant={statusVariant} dot={statusDot} className="text-xs">
                  {STATUS_LABELS[lead.status] ?? lead.status}
                </Badge>
                {!lead.enriched && (
                  <Badge variant="warning" dot="warning" className="text-[10px]">
                    не обогащён
                  </Badge>
                )}
              </div>
            </GlassCard>
          );
        })}
      </div>

      {/* Desktop: full table (hidden on mobile) */}
      <div
        className="hidden min-w-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] md:block"
        role="region"
        aria-label="Таблица лидов"
      >
        <div className="overflow-x-auto">
          <Table aria-label="Список лидов" className="min-w-[700px]">
            <TableHeader className="border-b border-white/[0.08] bg-white/[0.04] [&_tr]:border-b-0">
              <TableRow className="border-b-0 hover:bg-transparent">
                <TableHead className="h-11 w-8 px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48] sm:w-10">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAll}
                    className="cursor-pointer rounded"
                    aria-label={allVisibleSelected ? "Снять выбор со всех" : "Выбрать все"}
                  />
                </TableHead>
                <TableHead className="h-11 min-w-[140px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Компания</TableHead>
                <TableHead className="h-11 min-w-[80px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Город</TableHead>
                <TableHead className="h-11 min-w-[110px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Сайт</TableHead>
                <TableHead className="hidden h-11 min-w-[140px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48] md:table-cell">Email</TableHead>
                <TableHead className="hidden h-11 min-w-[110px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48] sm:table-cell">Телефон</TableHead>
                <TableHead className="hidden h-11 min-w-[130px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48] md:table-cell">Адрес</TableHead>
                <TableHead className="h-11 min-w-[80px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48]">Статус</TableHead>
                <TableHead className="hidden h-11 min-w-[120px] px-4 text-[11px] font-medium uppercase tracking-wider text-white/[0.48] md:table-cell">Score</TableHead>
                <TableHead className="h-11 w-10 px-4" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((lead) => {
                const isSelected = selectedIds.includes(lead.id);
                const isExpanded = expandedId === lead.id;
                const domain = lead.domain || lead.website?.replace(/^https?:\/\/(www\.)?/, "").split("/")[0] || "";
                const statusVariant = STATUS_VARIANTS[lead.status] ?? "default";
                const statusDot = STATUS_DOTS[lead.status];

                return (
                  <>
                    <TableRow
                      key={lead.id}
                      data-state={isSelected ? "selected" : undefined}
                      className="cursor-pointer border-b border-white/[0.06] transition-colors duration-150 hover:bg-white/[0.04] data-[state=selected]:bg-white/[0.06]"
                      onClick={(e) => handleRowClick(lead.id, e)}
                    >
                      <TableCell className="px-4 py-3.5">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={(e) =>
                            setSelectedIds((prev) =>
                              e.target.checked ? [...new Set([...prev, lead.id])] : prev.filter((id) => id !== lead.id)
                            )
                          }
                          className="cursor-pointer rounded"
                          aria-label={`Выбрать ${lead.company}`}
                        />
                      </TableCell>
                      <TableCell className="max-w-[192px] px-4 py-3.5">
                        <div>
                          <p className="flex items-center gap-1.5 truncate text-sm font-medium text-white" title={lead.company}>
                            <SourceBadge source={lead.source} externalId={lead.external_id} />
                            <span className="truncate">{lead.company}</span>
                          </p>
                          {lead.enriched ? (
                            <span className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-white/[0.48]">
                              <Sparkles size={9} /> обогащён
                            </span>
                          ) : (
                            <span
                              className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-status-warning"
                              title="Контакты ещё не собраны — запустите обогащение"
                            >
                              <span className="status-dot" data-state="warning" aria-hidden />
                              не обогащён
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[96px] px-4 py-3.5">
                        <TruncatedCell value={lead.city} className="text-white/[0.72]" />
                      </TableCell>
                      <TableCell className="max-w-[144px] px-4 py-3.5">
                        {lead.website && /^https?:\/\//i.test(lead.website.trim()) && !lead.website.trim().toLowerCase().startsWith('data:') ? (
                          <a
                            href={lead.website}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={lead.website}
                            className="inline-flex max-w-full items-center gap-1 truncate text-white underline decoration-white/[0.30] underline-offset-2 hover:decoration-white"
                          >
                            <span className="truncate">{domain}</span>
                            <ExternalLink size={10} className="shrink-0 text-white/[0.48]" />
                          </a>
                        ) : (
                          <span className="text-white/[0.40]">—</span>
                        )}
                      </TableCell>
                      <TableCell className="hidden max-w-[176px] px-4 py-3.5 md:table-cell">
                        {lead.email ? (
                          <div className="flex items-center gap-1.5">
                            <a
                              href={`mailto:${lead.email}`}
                              title={lead.email}
                              className="block truncate text-white underline decoration-white/[0.30] underline-offset-2 hover:decoration-white"
                            >
                              {lead.email}
                            </a>
                            <EmailStatusBadge status={lead.email_status} />
                          </div>
                        ) : (
                          <span className="text-white/[0.40]">—</span>
                        )}
                      </TableCell>
                      <TableCell className="hidden max-w-[128px] px-4 py-3.5 sm:table-cell">
                        <TruncatedCell value={lead.phone} className="font-mono text-white/[0.72]" />
                      </TableCell>
                      <TableCell className="hidden max-w-[176px] px-4 py-3.5 md:table-cell">
                        <TruncatedCell value={lead.address} className="text-white/[0.56]" />
                      </TableCell>
                      <TableCell className="px-4 py-3.5">
                        {onLeadUpdate ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger
                              render={
                                <button type="button" className="cursor-pointer">
                                  <Badge variant={statusVariant} dot={statusDot}>
                                    {STATUS_LABELS[lead.status] ?? lead.status}
                                  </Badge>
                                </button>
                              }
                            />
                            <DropdownMenuContent align="start" sideOffset={4}>
                              {STATUS_OPTIONS.map((opt) => {
                                const optVariant = STATUS_VARIANTS[opt.value] ?? "default";
                                const optDot = STATUS_DOTS[opt.value];
                                return (
                                  <DropdownMenuItem
                                    key={opt.value}
                                    onClick={() => void changeStatus(lead.id, opt.value)}
                                  >
                                    <Badge variant={optVariant} dot={optDot} className="pointer-events-none">
                                      {opt.label}
                                    </Badge>
                                  </DropdownMenuItem>
                                );
                              })}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : (
                          <Badge variant={statusVariant} dot={statusDot}>
                            {STATUS_LABELS[lead.status] ?? lead.status}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="hidden px-4 py-3.5 md:table-cell">
                        <ScoreIndicator score={lead.score} />
                      </TableCell>
                      <TableCell className="px-4 py-3.5">
                        {onLeadDelete && (
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="text-white/[0.48] hover:text-status-offline"
                            onClick={(e) => {
                              e.stopPropagation();
                              void deleteLead(lead.id);
                            }}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <NotesRow key={`${lead.id}-notes`} lead={lead} onLeadUpdate={onLeadUpdate} />
                    )}
                  </>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>

      <p className="text-[11px] text-white/[0.48]">
        Показано {filtered.length} из {leads.length}
        {selectedIds.length > 0 && ` · Выбрано: ${selectedIds.length}`}
      </p>
    </div>
  );
}

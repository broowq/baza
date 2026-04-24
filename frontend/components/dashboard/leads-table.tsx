"use client";

import { KeyboardEvent, useMemo, useState } from "react";
import { ArrowDownUp, ExternalLink, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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

const STATUS_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  new: "secondary",
  contacted: "outline",
  qualified: "default",
  rejected: "destructive",
};

const STATUS_OPTIONS: { value: Lead["status"]; label: string }[] = [
  { value: "new", label: "Новый" },
  { value: "contacted", label: "Связались" },
  { value: "qualified", label: "Квалифицирован" },
  { value: "rejected", label: "Отклонён" },
];

const SOURCE_META: Record<string, { label: string; emoji: string; color: string }> = {
  yandex_maps: { label: "Яндекс Карты", emoji: "🅉", color: "text-red-500" },
  "2gis": { label: "2ГИС", emoji: "②", color: "text-emerald-500" },
  rusprofile: { label: "ЕГРЮЛ (rusprofile)", emoji: "📋", color: "text-blue-500" },
  maps_searxng: { label: "Яндекс Карты (web)", emoji: "🅉", color: "text-rose-400" },
  searxng: { label: "Web-поиск", emoji: "🌐", color: "text-slate-500" },
  bing: { label: "Bing", emoji: "🅱", color: "text-slate-500" },
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
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-green-500/15 text-[10px] text-green-600"
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
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-red-500/15 text-[10px] text-red-500"
        aria-label="email invalid"
      >
        !
      </span>
    );
  }
  return null;
}

function TruncatedCell({ value, className = "" }: { value: string | null | undefined; className?: string }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
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
  const colorClass =
    score >= SCORE_HIGH
      ? "text-emerald-600 dark:text-emerald-400"
      : score >= SCORE_MEDIUM
        ? "text-amber-600 dark:text-amber-400"
        : "text-rose-600 dark:text-rose-400";

  const bgClass =
    score >= SCORE_HIGH
      ? "bg-emerald-500"
      : score >= SCORE_MEDIUM
        ? "bg-amber-500"
        : "bg-rose-500";

  return (
    <div className="flex items-center gap-2">
      <span className={`inline-block h-2 w-2 rounded-full ${bgClass}`} />
      <span className={`text-sm font-semibold tabular-nums ${colorClass}`}>{score}</span>
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
    <TableRow className="bg-muted/30 hover:bg-muted/30">
      <TableCell colSpan={11} className="px-4 py-3 sm:px-8">
        <div className="grid gap-3 sm:grid-cols-2">
          {/* Notes */}
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Заметка</span>
            <Input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => void saveNotes()}
              onKeyDown={handleKeyDown}
              placeholder="Контекст переговоров, кто принимает решение..."
              className="h-8 text-sm"
              disabled={saving}
            />
          </div>
          {/* Tags */}
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Теги</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {tags.map((t) => (
                <Badge key={t} variant="secondary" className="cursor-pointer text-xs" onClick={() => void removeTag(t)}>
                  {t} ✕
                </Badge>
              ))}
              <Input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addTag(); } }}
                placeholder="+ тег"
                className="h-7 w-24 text-xs"
                disabled={saving}
              />
            </div>
          </div>
          {/* Workflow actions */}
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Действия</span>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Button size="sm" variant="outline" disabled={saving} onClick={() => void patchLead({ mark_contacted: true })}>
                ✓ Связались сейчас
              </Button>
              {lastContactStr && (
                <span className="text-muted-foreground">последний контакт: {lastContactStr}</span>
              )}
            </div>
          </div>
          {/* Reminder */}
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Напоминание</span>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <Button size="sm" variant="outline" disabled={saving} onClick={() => void setReminder(1)}>+1д</Button>
              <Button size="sm" variant="outline" disabled={saving} onClick={() => void setReminder(3)}>+3д</Button>
              <Button size="sm" variant="outline" disabled={saving} onClick={() => void setReminder(7)}>+7д</Button>
              <Button size="sm" variant="outline" disabled={saving} onClick={() => void setReminder(14)}>+14д</Button>
              {reminderDateStr && (
                <>
                  <span className={reminderOverdue ? "font-semibold text-red-600" : "text-muted-foreground"}>
                    напомнить {reminderDateStr}{reminderOverdue && " (просрочено)"}
                  </span>
                  <Button size="sm" variant="ghost" disabled={saving} onClick={() => void setReminder(null)}>×</Button>
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
        <div className="h-10 animate-pulse rounded-xl bg-muted" />
        <div className="h-56 animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  if (leads.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-8 text-center">
        <h3 className="text-base font-semibold">Лидов пока нет</h3>
        <p className="mt-1 text-sm text-muted-foreground">Запустите сбор, чтобы заполнить таблицу.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!hideInternalFilters && (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по компании, домену, email..."
            className="w-full sm:w-56"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "all" | Lead["status"])}
            className="h-8 rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="all">Все статусы</option>
            <option value="new">Новый</option>
            <option value="contacted">Связались</option>
            <option value="qualified">Квалифицирован</option>
            <option value="rejected">Отклонён</option>
          </select>
          <Button
            variant="outline"
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
          <Button size="sm" disabled={!canBulkEnrich || runningBulk} onClick={runBulk}>
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
          <p className="rounded-lg border bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground">
            Нет лидов по текущим фильтрам.
          </p>
        )}
        {filtered.map((lead) => {
          const isSelected = selectedIds.includes(lead.id);
          const domain = lead.domain || (lead.website ? lead.website.replace(/^https?:\/\//, "").split("/")[0] : "");
          const scoreColor = lead.score >= SCORE_HIGH ? "text-emerald-600" : lead.score >= SCORE_MEDIUM ? "text-amber-600" : "text-red-500";
          return (
            <div key={lead.id} className="rounded-lg border bg-card p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0 flex-1">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(e) => setSelectedIds((prev) =>
                      e.target.checked ? [...new Set([...prev, lead.id])] : prev.filter((id) => id !== lead.id)
                    )}
                    className="mt-1 h-4 w-4 cursor-pointer rounded"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm break-words">{lead.company}</p>
                    {lead.city && <p className="text-xs text-muted-foreground mt-0.5">{lead.city}</p>}
                  </div>
                </div>
                <div className={`text-sm font-bold ${scoreColor} shrink-0`}>{lead.score}</div>
              </div>
              <div className="space-y-1.5 text-xs">
                {lead.phone && (
                  <a href={`tel:${lead.phone}`} className="block text-blue-600 underline">
                    📞 {lead.phone}
                  </a>
                )}
                {lead.email && (
                  <a href={`mailto:${lead.email}`} className="block text-blue-600 underline break-all">
                    ✉️ {lead.email}
                  </a>
                )}
                {lead.address && (
                  <p className="text-muted-foreground">📍 {lead.address}</p>
                )}
                {domain && lead.website && /^https?:\/\//i.test(lead.website) && (
                  <a href={lead.website} target="_blank" rel="noopener noreferrer" className="block text-blue-600 underline truncate">
                    🌐 {domain}
                  </a>
                )}
              </div>
              <div className="flex items-center justify-between pt-1">
                <Badge variant={STATUS_VARIANTS[lead.status] ?? "secondary"} className="text-xs">
                  {STATUS_LABELS[lead.status] ?? lead.status}
                </Badge>
                {!lead.enriched && (
                  <span className="text-[10px] text-amber-600">не обогащён</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop: full table (hidden on mobile) */}
      <div className="hidden min-w-0 overflow-x-auto rounded-lg border md:block" role="region" aria-label="Таблица лидов">
        <Table aria-label="Список лидов" className="min-w-[700px]">
          <TableHeader>
            <TableRow>
              <TableHead className="w-8 sm:w-10">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleAll}
                  className="cursor-pointer rounded"
                  aria-label={allVisibleSelected ? "Снять выбор со всех" : "Выбрать все"}
                />
              </TableHead>
              <TableHead className="min-w-[140px]">Компания</TableHead>
              <TableHead className="min-w-[80px]">Город</TableHead>
              <TableHead className="min-w-[110px]">Сайт</TableHead>
              <TableHead className="hidden min-w-[140px] md:table-cell">Email</TableHead>
              <TableHead className="hidden min-w-[110px] sm:table-cell">Телефон</TableHead>
              <TableHead className="hidden min-w-[130px] md:table-cell">Адрес</TableHead>
              <TableHead className="min-w-[80px]">Статус</TableHead>
              <TableHead className="hidden min-w-[60px] md:table-cell">Score</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((lead) => {
              const isSelected = selectedIds.includes(lead.id);
              const isExpanded = expandedId === lead.id;
              const domain = lead.domain || lead.website?.replace(/^https?:\/\/(www\.)?/, "").split("/")[0] || "";

              return (
                <>
                  <TableRow
                    key={lead.id}
                    data-state={isSelected ? "selected" : undefined}
                    className="cursor-pointer"
                    onClick={(e) => handleRowClick(lead.id, e)}
                  >
                    <TableCell>
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
                    <TableCell className="max-w-[192px]">
                      <div>
                        <p className="truncate font-medium flex items-center gap-1" title={lead.company}>
                          <SourceBadge source={lead.source} externalId={lead.external_id} />
                          <span className="truncate">{lead.company}</span>
                        </p>
                        {lead.enriched ? (
                          <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-muted-foreground">
                            <Sparkles size={9} /> обогащён
                          </span>
                        ) : (
                          <span
                            className="mt-0.5 inline-flex items-center gap-1 text-xs text-amber-600"
                            title="Контакты ещё не собраны — запустите обогащение"
                          >
                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
                            не обогащён
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-[96px]">
                      <TruncatedCell value={lead.city} className="text-muted-foreground" />
                    </TableCell>
                    <TableCell className="max-w-[144px]">
                      {lead.website && /^https?:\/\//i.test(lead.website.trim()) && !lead.website.trim().toLowerCase().startsWith('data:') ? (
                        <a
                          href={lead.website}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={lead.website}
                          className="inline-flex max-w-full items-center gap-1 truncate text-foreground underline decoration-muted-foreground/50 underline-offset-2 hover:decoration-foreground"
                        >
                          <span className="truncate">{domain}</span>
                          <ExternalLink size={10} className="shrink-0 text-muted-foreground" />
                        </a>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden max-w-[176px] md:table-cell">
                      {lead.email ? (
                        <div className="flex items-center gap-1">
                          <a
                            href={`mailto:${lead.email}`}
                            title={lead.email}
                            className="block truncate text-foreground underline decoration-muted-foreground/50 underline-offset-2 hover:decoration-foreground"
                          >
                            {lead.email}
                          </a>
                          <EmailStatusBadge status={lead.email_status} />
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden max-w-[128px] sm:table-cell">
                      <TruncatedCell value={lead.phone} className="font-mono text-muted-foreground" />
                    </TableCell>
                    <TableCell className="hidden max-w-[176px] md:table-cell">
                      <TruncatedCell value={lead.address} className="text-muted-foreground" />
                    </TableCell>
                    <TableCell>
                      {onLeadUpdate ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            render={
                              <button type="button" className="cursor-pointer">
                                <Badge variant={STATUS_VARIANTS[lead.status] ?? "secondary"}>
                                  {STATUS_LABELS[lead.status] ?? lead.status}
                                </Badge>
                              </button>
                            }
                          />
                          <DropdownMenuContent align="start" sideOffset={4}>
                            {STATUS_OPTIONS.map((opt) => (
                              <DropdownMenuItem
                                key={opt.value}
                                onClick={() => void changeStatus(lead.id, opt.value)}
                              >
                                <Badge variant={STATUS_VARIANTS[opt.value]} className="pointer-events-none">
                                  {opt.label}
                                </Badge>
                              </DropdownMenuItem>
                            ))}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      ) : (
                        <Badge variant={STATUS_VARIANTS[lead.status] ?? "secondary"}>
                          {STATUS_LABELS[lead.status] ?? lead.status}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <ScoreIndicator score={lead.score} />
                    </TableCell>
                    <TableCell>
                      {onLeadDelete && (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="text-muted-foreground hover:text-destructive"
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

      <p className="text-xs text-muted-foreground">
        Показано {filtered.length} из {leads.length}
        {selectedIds.length > 0 && ` · Выбрано: ${selectedIds.length}`}
      </p>
    </div>
  );
}

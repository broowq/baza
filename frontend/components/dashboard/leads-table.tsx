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
  const [saving, setSaving] = useState(false);

  const saveNotes = async () => {
    if (notes === (lead.notes ?? "")) return;
    setSaving(true);
    try {
      await api(`/leads/${lead.id}`, {
        method: "PATCH",
        body: JSON.stringify({ notes }),
      });
      onLeadUpdate?.(lead.id, { notes });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось сохранить заметку");
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void saveNotes();
    }
  };

  return (
    <TableRow className="bg-muted/30 hover:bg-muted/30">
      <TableCell colSpan={11} className="px-4 py-3 sm:px-8">
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted-foreground">Заметки</span>
          <div className="flex items-center gap-2">
            <Input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => void saveNotes()}
              onKeyDown={handleKeyDown}
              placeholder="Добавить заметку..."
              className="h-8 max-w-md text-sm"
              disabled={saving}
            />
            {saving && <span className="text-xs text-muted-foreground">Сохранение...</span>}
          </div>
          {lead.notes && notes === lead.notes && (
            <p className="text-sm text-muted-foreground">{lead.notes}</p>
          )}
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

      <div className="min-w-0 overflow-x-auto rounded-lg border" role="region" aria-label="Таблица лидов">
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
                        <p className="truncate font-medium" title={lead.company}>{lead.company}</p>
                        {lead.enriched && (
                          <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-muted-foreground">
                            <Sparkles size={9} /> обогащён
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
                        <a
                          href={`mailto:${lead.email}`}
                          title={lead.email}
                          className="block truncate text-foreground underline decoration-muted-foreground/50 underline-offset-2 hover:decoration-foreground"
                        >
                          {lead.email}
                        </a>
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

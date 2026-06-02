"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, ChevronDown, Download, Loader2, Play, RefreshCw, SlidersHorizontal, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { motion } from "framer-motion";

import { JobHistory } from "@/components/dashboard/job-history";
import { LeadCards } from "@/components/dashboard/lead-cards";
import { LeadsTable } from "@/components/dashboard/leads-table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Loader } from "@/components/ui/loader";
import { api, apiFetch } from "@/lib/api";
import { getOrgId, getToken } from "@/lib/auth";
import { useDebounce } from "@/lib/hooks";
import type { CollectionJob, Lead, Project } from "@/lib/types";

const STAT_CARDS = [
  { key: "total", label: "Всего лидов" },
  { key: "enriched", label: "Обогащено" },
  { key: "withEmail", label: "С email" },
  { key: "avgScore", label: "Средний score" },
] as const;

const JOB_KIND_RU: Record<string, string> = { collect: "сбор", enrich: "обогащение" };
const JOB_STATUS_RU: Record<string, string> = {
  queued: "в очереди",
  running: "идёт",
  done: "готово",
  failed: "ошибка",
};

// Select value→label maps. Base UI's <SelectValue> renders the raw value unless
// given a function child, so map each value to its Russian label explicitly.
const STATUS_LABELS: Record<string, string> = {
  all: "Все статусы",
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  rejected: "Отклонён",
};
const SORT_LABELS: Record<string, string> = { score: "По score", created_at: "По дате", company: "По компании" };
const ORDER_LABELS: Record<string, string> = { desc: "Убывание", asc: "Возрастание" };
const EMAIL_LABELS: Record<string, string> = { all: "Email: все", true: "С email", false: "Без email" };
const PHONE_LABELS: Record<string, string> = { all: "Тел: все", true: "С телефоном", false: "Без телефона" };

export default function ProjectDetailsPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;

  const [project, setProject] = useState<Project | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [jobs, setJobs] = useState<CollectionJob[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState("score");
  const [order, setOrder] = useState("desc");
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [hasEmail, setHasEmail] = useState("all");
  const [hasPhone, setHasPhone] = useState("all");
  const [page, setPage] = useState(1);
  const [perPage] = useState(25);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [orgRole, setOrgRole] = useState<"owner" | "admin" | "member">("member");
  const [stats, setStats] = useState({ total: 0, enriched: 0, withEmail: 0, avgScore: 0 });
  const [activeTab, setActiveTab] = useState<string>("leads");
  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [showFilters, setShowFilters] = useState(false);

  const debouncedSearch = useDebounce(search, 400);
  const leadsTableRef = useRef<HTMLDivElement>(null);

  const fetchAll = useCallback(async () => {
    setTableLoading(true);
    try {
      const query = new URLSearchParams({ page: String(page), per_page: String(perPage), q: debouncedSearch, sort, order });
      if (status !== "all") query.set("status", status);
      if (minScore) query.set("min_score", minScore);
      if (maxScore) query.set("max_score", maxScore);
      if (hasEmail !== "all") query.set("has_email", hasEmail);
      if (hasPhone !== "all") query.set("has_phone", hasPhone);

      const [projectsList, projectLeads, projectJobs, membership, statsData] = await Promise.all([
        api<Project[]>("/projects"),
        api<{ items: Lead[]; total: number }>(`/leads/project/${projectId}/table?${query.toString()}`),
        api<CollectionJob[]>(`/leads/jobs/project/${projectId}`),
        api<{ role: "owner" | "admin" | "member" }>("/organizations/membership"),
        api<{ total: number; enriched: number; with_email: number; avg_score: number }>(`/leads/project/${projectId}/stats`),
      ]);
      // Cross-org guard: if the requested project_id is not in the user's
      // accessible list (different org or deleted), redirect to dashboard
      // instead of rendering a blank page with null project.
      const current = projectsList.find((item) => item.id === projectId) ?? null;
      if (!current) {
        toast.error("Проект не найден или принадлежит другой организации");
        window.location.href = "/dashboard";
        return;
      }
      setProject(current);
      setLeads(projectLeads.items);
      setTotal(projectLeads.total);
      setJobs(Array.isArray(projectJobs) ? projectJobs : []);
      setOrgRole(membership.role);
      setStats({ total: statsData.total, enriched: statsData.enriched, withEmail: statsData.with_email, avgScore: Math.round(statsData.avg_score) });
    } catch (error) {
      const msg = error instanceof Error ? error.message : "";
      if (msg.includes("авториз") || msg.includes("Сессия")) {
        window.location.href = "/login";
        return;
      }
      setError(msg || "Не удалось загрузить проект");
    } finally {
      setLoading(false);
      setTableLoading(false);
    }
  }, [hasEmail, hasPhone, maxScore, minScore, order, page, perPage, projectId, debouncedSearch, sort, status]);

  const hasActiveJobs = jobs.some((j) => j.status === "queued" || j.status === "running");

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    if (!hasActiveJobs) return;
    const id = setInterval(() => void fetchAll(), 6000);
    return () => clearInterval(id);
  }, [hasActiveJobs, fetchAll]);

  useEffect(() => {
    const token = getToken();
    const orgId = getOrgId();
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
    if (!token || !orgId) return;

    let cancelled = false;
    const controller = new AbortController();

    (async () => {
      try {
        const res = await fetch(
          `${base}/jobs/subscribe?project_id=${projectId}&org_id=${orgId}`,
          { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal },
        );
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!cancelled) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const parsed = JSON.parse(line.slice(6));
              if (Array.isArray(parsed)) setJobs(parsed);
            } catch { /* ignore */ }
          }
        }
      } catch { /* Connection closed */ }
    })();

    return () => { cancelled = true; controller.abort(); };
  }, [projectId]);

  const queueJob = async (kind: "collect" | "enrich", limit: number) => {
    setRunning(true);
    try {
      await api(`/leads/project/${projectId}/${kind}`, {
        method: "POST",
        body: JSON.stringify({ lead_limit: limit }),
      });
      toast.success(`Задача ${kind === "collect" ? "сбора" : "обогащения"} добавлена в очередь`);
      await fetchAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось запустить задачу");
    } finally {
      setRunning(false);
    }
  };

  const [exporting, setExporting] = useState<"" | "csv" | "xlsx">("");
  const exportFile = async (format: "csv" | "xlsx") => {
    if (exporting) return;
    setExporting(format);
    try {
      const path = format === "xlsx" ? "/export.xlsx" : "/export";
      const response = await apiFetch(`/leads/project/${projectId}${path}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `project-${projectId}-leads.${format}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`${format.toUpperCase()} выгружен`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Ошибка экспорта");
    } finally {
      setExporting("");
    }
  };
  const exportCsv = () => void exportFile("csv");
  const exportXlsx = () => void exportFile("xlsx");

  const handleBulkEnrich = async (leadIds: string[]) => {
    try {
      await api(`/leads/project/${projectId}/enrich-selected`, {
        method: "POST",
        body: JSON.stringify({ lead_ids: leadIds }),
      });
      toast.success(`Обогащение запущено для ${leadIds.length} лидов`);
      await fetchAll();
      return true;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось запустить обогащение");
      return false;
    }
  };

  if (loading) {
    return <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6 lg:px-10"><Loader /></main>;
  }

  if (error) {
    return (
      <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6 lg:px-10">
        <div className="panel p-8 text-center space-y-4">
          <p className="t-72 text-sm">{error}</p>
          <button
            className="btn btn-brand"
            onClick={() => { setError(null); setLoading(true); void fetchAll(); }}
          >
            Повторить
          </button>
        </div>
      </main>
    );
  }

  const canManage = orgRole === "owner" || orgRole === "admin";
  const collectBusy = jobs.some((job) => job.kind === "collect" && (job.status === "queued" || job.status === "running"));
  const enrichBusy = jobs.some((job) => job.kind === "enrich" && (job.status === "queued" || job.status === "running"));

  // How many filters are narrowing the list (sort/order don't count) — drives
  // the badge on the «Фильтры» button so active filters are visible when collapsed.
  const activeFilterCount =
    (status !== "all" ? 1 : 0) +
    (minScore ? 1 : 0) +
    (maxScore ? 1 : 0) +
    (hasEmail !== "all" ? 1 : 0) +
    (hasPhone !== "all" ? 1 : 0);

  const resetFilters = () => {
    setPage(1);
    setStatus("all");
    setMinScore("");
    setMaxScore("");
    setHasEmail("all");
    setHasPhone("all");
  };

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-[1280px] space-y-6 px-4 py-8 sm:px-6 lg:px-10"
    >
      {/* Header */}
      <div className="space-y-5">
        {/* Breadcrumb */}
        <div className="mono-cap" style={{ fontSize: "10.5px" }}>
          <Link href="/dashboard" className="t-40 hover:text-white transition-colors">дашборд</Link>
          <span className="t-28 mx-1.5">/</span>
          <span className="t-40">проекты</span>
          <span className="t-28 mx-1.5">/</span>
          <span className="t-72">{project?.name ?? "—"}</span>
        </div>

        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="eyebrow mb-2">проект</div>
            <h1 className="h1" style={{ fontSize: "clamp(36px,5vw,56px)" }}>
              {project?.name ?? "Проект"}
            </h1>
            <div className="mono-cap mt-3 flex items-center flex-wrap" style={{ gap: "0 4px" }}>
              {project?.niche && <span>ниша: {project.niche}</span>}
              {project?.geography && (
                <>
                  <span className="sep-dot mx-2" />
                  <span>гео: {project.geography}</span>
                </>
              )}
            </div>
          </div>

        </div>

        {/* Chips row */}
        {project && (project.segments.length > 0 || (project.okved_codes?.length ?? 0) > 0) && (
          <div className="flex items-center gap-2 flex-wrap">
            {project.segments.slice(0, 8).map((seg) => (
              <span key={seg} className="chip chip-sans">{seg}</span>
            ))}
            {project.okved_codes?.map((o) => (
              <span key={o.code} className="chip chip-okv" title={o.label}>
                ОКВЭД {o.code}
              </span>
            ))}
          </div>
        )}

        {/* Action bar (sticky) */}
        <div className="panel-flat px-5 flex items-center gap-2.5 flex-wrap" style={{ minHeight: 56, paddingTop: 8, paddingBottom: 8 }}>
          <button
            className="btn btn-brand"
            disabled={running || collectBusy || !canManage}
            onClick={() => queueJob("collect", 500)}
          >
            {collectBusy ? (
              <><Loader2 size={12} className="animate-spin" /> Собираем…</>
            ) : (
              <><Play size={11} /> Собрать лиды</>
            )}
          </button>
          <button
            className="btn btn-ghost"
            disabled={running || enrichBusy || !canManage}
            onClick={() => queueJob("enrich", 200)}
          >
            {enrichBusy ? (
              <><Loader2 size={12} className="animate-spin" /> Обогащаем…</>
            ) : (
              <><Sparkles size={12} /> Обогатить</>
            )}
          </button>
          <button
            className="btn btn-ghost"
            onClick={exportXlsx}
            disabled={!!exporting}
          >
            {exporting === "xlsx" ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
            Excel
          </button>
          <button
            className="btn btn-ghost"
            onClick={exportCsv}
            disabled={!!exporting}
          >
            {exporting === "csv" ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
            CSV
          </button>
          <span className="mono-cap t-40 ml-auto mr-2">
            {jobs.length > 0
              ? `${JOB_KIND_RU[jobs[0].kind] ?? jobs[0].kind} · ${JOB_STATUS_RU[jobs[0].status] ?? jobs[0].status}`
              : "сбор ещё не запускали"}
          </span>
        </div>

        {project && canManage && (
          <AutoCollectionBar project={project} onUpdate={(updated) => setProject(updated)} />
        )}
      </div>

      {/* Stats strip (v3) */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {STAT_CARDS.map((s, i) => {
          const value = stats[s.key];
          return (
            <motion.div
              key={s.key}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.08 }}
              className="panel-flat"
              style={{ padding: 20 }}
            >
              <div className="eyebrow mb-3">{s.label}</div>
              <div className="h2 tnum mono">{value}</div>
            </motion.div>
          );
        })}
      </div>

      <Separator />

      {/* Tabs */}
      <Tabs defaultValue="leads" value={activeTab} onValueChange={(v) => setActiveTab(v ?? "leads")}>
        <div className="flex items-center justify-between gap-4 overflow-x-auto">
          <TabsList className="shrink-0">
            <TabsTrigger value="leads" className="font-medium">Лиды</TabsTrigger>
            <TabsTrigger value="jobs" className="font-medium">История задач</TabsTrigger>
          </TabsList>
          {activeTab === "leads" && (
            <Button size="sm" variant="ghost" onClick={() => void fetchAll()}>
              <RefreshCw size={13} className="mr-1" /> Обновить
            </Button>
          )}
        </div>

        <TabsContent value="leads" className="overflow-hidden">
          <div ref={leadsTableRef} className="space-y-4 min-w-0">
            {/* Filters + view toggle bar */}
            <div className="rounded-xl bg-muted/30 p-2.5 space-y-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  className="w-full sm:w-64"
                  placeholder="Поиск по компании, сайту, городу…"
                  value={search}
                  aria-label="Поиск по лидам"
                  onChange={(e) => { setPage(1); setSearch(e.target.value); }}
                />

                {/* Toggle the filter panel — keeps the bar clean by default */}
                <button
                  type="button"
                  className="btn btn-ghost shrink-0"
                  aria-expanded={showFilters}
                  aria-controls="lead-filters-panel"
                  onClick={() => setShowFilters((v) => !v)}
                >
                  <SlidersHorizontal size={13} />
                  Фильтры
                  {activeFilterCount > 0 && (
                    <span className="ml-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-[var(--mint)] px-1 text-[10.5px] font-semibold leading-none text-black tnum">
                      {activeFilterCount}
                    </span>
                  )}
                  <ChevronDown
                    size={13}
                    className="transition-transform"
                    style={{ transform: showFilters ? "rotate(180deg)" : "none", opacity: 0.55 }}
                  />
                </button>

                {/* View toggle — Cards | Table */}
                <div className="seg ml-auto shrink-0" role="group" aria-label="Вид отображения">
                  <button
                    type="button"
                    className={`seg-btn${viewMode === "cards" ? " active" : ""}`}
                    aria-pressed={viewMode === "cards"}
                    onClick={() => setViewMode("cards")}
                  >
                    Карточки
                  </button>
                  <button
                    type="button"
                    className={`seg-btn${viewMode === "table" ? " active" : ""}`}
                    aria-pressed={viewMode === "table"}
                    onClick={() => setViewMode("table")}
                  >
                    Таблица
                  </button>
                </div>
              </div>

              {/* Collapsible filter panel — rendered in normal flow (no portal) so
                  the nested selects work reliably */}
              {showFilters && (
                <div
                  id="lead-filters-panel"
                  className="grid gap-x-4 gap-y-3 border-t border-[var(--line-2)] pt-3 sm:grid-cols-2 lg:grid-cols-4"
                >
                  <div className="space-y-1.5">
                    <div className="eyebrow">Статус</div>
                    <Select value={status} onValueChange={(val: string | null) => { if (val) { setPage(1); setStatus(val); } }}>
                      <SelectTrigger className="w-full" aria-label="Фильтр по статусу">
                        <SelectValue placeholder="Все статусы">
                          {(v: string | null) => (v ? STATUS_LABELS[v] ?? v : "Все статусы")}
                        </SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Все статусы</SelectItem>
                        <SelectItem value="new">Новый</SelectItem>
                        <SelectItem value="contacted">Связались</SelectItem>
                        <SelectItem value="qualified">Квалифицирован</SelectItem>
                        <SelectItem value="rejected">Отклонён</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <div className="eyebrow">Сортировка</div>
                    <div className="flex gap-2">
                      <Select value={sort} onValueChange={(val: string | null) => { if (val) setSort(val); }}>
                        <SelectTrigger className="w-full flex-1" aria-label="Сортировка">
                          <SelectValue placeholder="По score">
                            {(v: string | null) => (v ? SORT_LABELS[v] ?? v : "По score")}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="score">По score</SelectItem>
                          <SelectItem value="created_at">По дате</SelectItem>
                          <SelectItem value="company">По компании</SelectItem>
                        </SelectContent>
                      </Select>
                      <Select value={order} onValueChange={(val: string | null) => { if (val) setOrder(val); }}>
                        <SelectTrigger className="w-full flex-1" aria-label="Порядок сортировки">
                          <SelectValue placeholder="Убывание">
                            {(v: string | null) => (v ? ORDER_LABELS[v] ?? v : "Убывание")}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="desc">Убывание</SelectItem>
                          <SelectItem value="asc">Возрастание</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="eyebrow">Score</div>
                    <div className="flex items-center gap-2">
                      <Input type="number" min={0} max={100} className="w-full" placeholder="от" value={minScore} aria-label="Минимальный score" onChange={(e) => { setPage(1); setMinScore(e.target.value); }} />
                      <span className="t-40">—</span>
                      <Input type="number" min={0} max={100} className="w-full" placeholder="до" value={maxScore} aria-label="Максимальный score" onChange={(e) => { setPage(1); setMaxScore(e.target.value); }} />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="eyebrow">Контакты</div>
                    <div className="flex gap-2">
                      <Select value={hasEmail} onValueChange={(val: string | null) => { if (val) { setPage(1); setHasEmail(val); } }}>
                        <SelectTrigger className="w-full flex-1" aria-label="Фильтр по email">
                          <SelectValue placeholder="Email: все">
                            {(v: string | null) => (v ? EMAIL_LABELS[v] ?? v : "Email: все")}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">Email: все</SelectItem>
                          <SelectItem value="true">С email</SelectItem>
                          <SelectItem value="false">Без email</SelectItem>
                        </SelectContent>
                      </Select>
                      <Select value={hasPhone} onValueChange={(val: string | null) => { if (val) { setPage(1); setHasPhone(val); } }}>
                        <SelectTrigger className="w-full flex-1" aria-label="Фильтр по телефону">
                          <SelectValue placeholder="Тел: все">
                            {(v: string | null) => (v ? PHONE_LABELS[v] ?? v : "Тел: все")}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">Тел: все</SelectItem>
                          <SelectItem value="true">С телефоном</SelectItem>
                          <SelectItem value="false">Без телефона</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  {activeFilterCount > 0 && (
                    <div className="flex justify-end sm:col-span-2 lg:col-span-4">
                      <button type="button" className="btn btn-ghost" onClick={resetFilters}>
                        Сбросить фильтры
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Cards view */}
            {viewMode === "cards" && (
              <LeadCards
                leads={leads}
                loading={tableLoading}
                onLeadUpdate={(leadId, patch) => {
                  setLeads((prev) => prev.map((l) => (l.id === leadId ? { ...l, ...patch } : l)));
                }}
              />
            )}

            {/* Table view */}
            {viewMode === "table" && (
              <LeadsTable
                leads={leads}
                loading={tableLoading}
                onBulkEnrich={handleBulkEnrich}
                canBulkEnrich={canManage && !enrichBusy}
                hideInternalFilters
                onLeadUpdate={(leadId, patch) => {
                  setLeads((prev) => prev.map((l) => (l.id === leadId ? { ...l, ...patch } : l)));
                }}
                onLeadDelete={(leadId) => {
                  setLeads((prev) => prev.filter((l) => l.id !== leadId));
                  setTotal((prev) => Math.max(0, prev - 1));
                }}
              />
            )}

            {/* Pagination */}
            <div className="flex flex-col items-center gap-2 text-sm text-muted-foreground sm:flex-row sm:justify-between">
              <span>Итого: {total} лидов</span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => { setPage((p) => Math.max(1, p - 1)); leadsTableRef.current?.scrollIntoView({ behavior: "smooth" }); }}>
                  Назад
                </Button>
                <span className="text-xs tabular-nums">
                  Страница {page} из {Math.max(1, Math.ceil(total / perPage))}
                </span>
                <Button variant="outline" size="sm" disabled={page * perPage >= total} onClick={() => { setPage((p) => p + 1); leadsTableRef.current?.scrollIntoView({ behavior: "smooth" }); }}>
                  Вперёд
                </Button>
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="jobs">
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Статус сбора и обогащения в реальном времени</p>
            <JobHistory jobs={jobs} />
          </div>
        </TabsContent>
      </Tabs>
    </motion.main>
  );
}


const SCHEDULE_PRESETS: { label: string; value: string }[] = [
  { label: "Каждый день 9:00", value: "0 9 * * *" },
  { label: "Каждый пн 9:00", value: "0 9 * * 1" },
  { label: "1-е и 15-е число 9:00", value: "0 9 1,15 * *" },
  { label: "Первое число месяца", value: "0 9 1 * *" },
];

function AutoCollectionBar({
  project,
  onUpdate,
}: {
  project: Project;
  onUpdate: (updated: Project) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [schedule, setSchedule] = useState(project.cron_schedule || SCHEDULE_PRESETS[1].value);

  const save = async (patch: { auto_collection_enabled?: boolean; cron_schedule?: string }) => {
    setSaving(true);
    try {
      const updated = await api<Project>(`/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      onUpdate(updated);
      toast.success(patch.auto_collection_enabled ? "Автосбор включён" : "Сохранено");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const onScheduleChange = (value: string | null) => {
    if (!value) return;
    setSchedule(value);
    if (project.auto_collection_enabled) void save({ cron_schedule: value });
  };

  const currentPreset = SCHEDULE_PRESETS.find((p) => p.value === schedule);

  return (
    <div className="panel-flat flex flex-wrap items-center gap-3 px-5 text-sm" style={{ minHeight: 56, paddingTop: 8, paddingBottom: 8 }}>
      <div className="flex items-center gap-2">
        <CalendarClock
          size={15}
          className={project.auto_collection_enabled ? "" : "text-muted-foreground"}
          style={project.auto_collection_enabled ? { color: "var(--mint)" } : undefined}
        />
        <span className="font-medium">Автосбор</span>
      </div>

      <label className="flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          checked={project.auto_collection_enabled}
          disabled={saving}
          onChange={(e) => void save({ auto_collection_enabled: e.target.checked, cron_schedule: schedule })}
          className="h-4 w-4 cursor-pointer rounded accent-[var(--mint)]"
        />
        <span className={project.auto_collection_enabled ? "" : "t-56"}>
          {project.auto_collection_enabled ? "Включён" : "Выключен"}
        </span>
      </label>

      <Select value={schedule} onValueChange={onScheduleChange} disabled={saving}>
        <SelectTrigger className="h-8 w-auto min-w-[200px] text-xs">
          <SelectValue placeholder="Расписание">
            {(v: string | null) => SCHEDULE_PRESETS.find((p) => p.value === v)?.label ?? "Расписание"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {SCHEDULE_PRESETS.map((preset) => (
            <SelectItem key={preset.value} value={preset.value}>{preset.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      {project.auto_collection_enabled && currentPreset && (
        <span className="mono-cap t-40 ml-auto">
          след. запуск: {currentPreset.label.toLowerCase()} · уведомим на email
        </span>
      )}
      {saving && <Loader2 size={13} className="animate-spin text-muted-foreground" />}
    </div>
  );
}

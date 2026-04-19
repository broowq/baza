"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, CalendarClock, Download, Loader2, Play, RefreshCw, Sparkles, Hash, Mail, TrendingUp, Users } from "lucide-react";
import { toast } from "sonner";
import { motion } from "framer-motion";

import { JobHistory } from "@/components/dashboard/job-history";
import { LeadsTable } from "@/components/dashboard/leads-table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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
  { key: "total", label: "Всего лидов", icon: Users },
  { key: "enriched", label: "Обогащено", icon: Sparkles },
  { key: "withEmail", label: "С email", icon: Mail },
  { key: "avgScore", label: "Средний score", icon: TrendingUp },
] as const;

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
  const [running, setRunning] = useState(false);
  const [orgRole, setOrgRole] = useState<"owner" | "admin" | "member">("member");
  const [stats, setStats] = useState({ total: 0, enriched: 0, withEmail: 0, avgScore: 0 });
  const [activeTab, setActiveTab] = useState<string | null>("leads");

  const debouncedSearch = useDebounce(search, 400);
  const leadsTableRef = useRef<HTMLElement>(null);

  const fetchAll = useCallback(async () => {
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
      setStats({ total: statsData.total, enriched: statsData.enriched, withEmail: statsData.with_email, avgScore: statsData.avg_score });
    } catch (error) {
      const msg = error instanceof Error ? error.message : "";
      if (msg.includes("авториз") || msg.includes("Сессия")) {
        window.location.href = "/login";
        return;
      }
      toast.error(msg || "Не удалось загрузить проект");
    } finally {
      setLoading(false);
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
    return <main className="mx-auto max-w-7xl px-6 py-10"><Loader /></main>;
  }

  const canManage = orgRole === "owner" || orgRole === "admin";
  const collectBusy = jobs.some((job) => job.kind === "collect" && (job.status === "queued" || job.status === "running"));
  const enrichBusy = jobs.some((job) => job.kind === "enrich" && (job.status === "queued" || job.status === "running"));

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6"
    >
      {/* Header */}
      <div className="space-y-4">
        <Link href="/dashboard" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft size={14} /> Назад
        </Link>
        <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold tracking-tight">{project?.name ?? "Проект"}</h1>
            <div className="flex flex-wrap items-center gap-2">
              {project?.niche && <Badge variant="secondary" className="rounded-full">{project.niche}</Badge>}
              {project?.geography && <Badge variant="secondary" className="rounded-full">{project.geography}</Badge>}
              {project?.segments.map((seg) => (
                <Badge key={seg} variant="outline" className="rounded-full">{seg}</Badge>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-4">
            {/* Collect group */}
            <Button size="sm" disabled={running || collectBusy || !canManage} onClick={() => queueJob("collect", 500)}>
              {collectBusy ? (
                <><Loader2 size={12} className="mr-1.5 animate-spin" /> Собираем…</>
              ) : (
                <><Play size={12} className="mr-1.5" /> Собрать лиды</>
              )}
            </Button>
            {/* Actions */}
            <div className="flex items-center gap-1.5">
              <Button size="sm" variant="outline" disabled={running || enrichBusy || !canManage} onClick={() => queueJob("enrich", 200)}>
                {enrichBusy ? (
                  <><Loader2 size={12} className="mr-1 animate-spin" /> Обогащаем…</>
                ) : (
                  <><Sparkles size={12} /> Обогатить</>
                )}
              </Button>
              <Button size="sm" variant="ghost" onClick={exportXlsx} disabled={!!exporting}>
                {exporting === "xlsx" ? (
                  <><Loader2 size={12} className="animate-spin" /> Excel…</>
                ) : (
                  <><Download size={12} /> Excel</>
                )}
              </Button>
              <Button size="sm" variant="ghost" onClick={exportCsv} disabled={!!exporting}>
                {exporting === "csv" ? (
                  <><Loader2 size={12} className="animate-spin" /> CSV…</>
                ) : (
                  <><Download size={12} /> CSV</>
                )}
              </Button>
            </div>
          </div>
        </div>

        {/* Auto-collection schedule bar */}
        {project && canManage && (
          <AutoCollectionBar project={project} onUpdate={(updated) => setProject(updated)} />
        )}
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {STAT_CARDS.map((s, i) => {
          const value = stats[s.key];
          return (
            <motion.div
              key={s.key}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.08 }}
            >
              <Card size="sm" className="bg-gradient-to-b from-card to-card/80">
                <CardContent className="flex flex-col gap-1">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <s.icon size={14} />
                    <span className="text-xs">{s.label}</span>
                  </div>
                  <p className="text-3xl font-bold tracking-tight">{value}</p>
                </CardContent>
              </Card>
            </motion.div>
          );
        })}
      </div>

      <Separator />

      {/* Tabs */}
      <Tabs defaultValue="leads" value={activeTab} onValueChange={setActiveTab}>
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
          <div ref={leadsTableRef as React.RefObject<HTMLDivElement>} className="space-y-4 min-w-0">
            {/* Filters bar */}
            <div className="flex flex-wrap items-center gap-2 rounded-xl bg-muted/30 p-3 [&>*]:w-full [&>*]:sm:w-auto">
              <Input
                className="w-full sm:w-48"
                placeholder="Поиск..."
                value={search}
                aria-label="Поиск по лидам"
                onChange={(e) => { setPage(1); setSearch(e.target.value); }}
              />
              <Select value={status} onValueChange={(val: string | null) => { if (val) { setPage(1); setStatus(val); } }}>
                <SelectTrigger aria-label="Фильтр по статусу">
                  <SelectValue placeholder="Все статусы" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все статусы</SelectItem>
                  <SelectItem value="new">Новый</SelectItem>
                  <SelectItem value="contacted">Контакт</SelectItem>
                  <SelectItem value="qualified">Горячий</SelectItem>
                  <SelectItem value="rejected">Отказ</SelectItem>
                </SelectContent>
              </Select>
              <Select value={sort} onValueChange={(val: string | null) => { if (val) setSort(val); }}>
                <SelectTrigger aria-label="Сортировка">
                  <SelectValue placeholder="По score" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="score">По score</SelectItem>
                  <SelectItem value="created_at">По дате</SelectItem>
                  <SelectItem value="company">По компании</SelectItem>
                </SelectContent>
              </Select>
              <Select value={order} onValueChange={(val: string | null) => { if (val) setOrder(val); }}>
                <SelectTrigger aria-label="Порядок сортировки">
                  <SelectValue placeholder="Убывание" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="desc">Убывание</SelectItem>
                  <SelectItem value="asc">Возрастание</SelectItem>
                </SelectContent>
              </Select>
              <Input
                type="number"
                min={0}
                max={100}
                className="w-full sm:w-24"
                placeholder="Score от"
                value={minScore}
                aria-label="Минимальный score"
                onChange={(e) => { setPage(1); setMinScore(e.target.value); }}
              />
              <Input
                type="number"
                min={0}
                max={100}
                className="w-full sm:w-24"
                placeholder="Score до"
                value={maxScore}
                aria-label="Максимальный score"
                onChange={(e) => { setPage(1); setMaxScore(e.target.value); }}
              />
              <Select value={hasEmail} onValueChange={(val: string | null) => { if (val) { setPage(1); setHasEmail(val); } }}>
                <SelectTrigger aria-label="Фильтр по email">
                  <SelectValue placeholder="Email: все" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Email: все</SelectItem>
                  <SelectItem value="true">С email</SelectItem>
                  <SelectItem value="false">Без email</SelectItem>
                </SelectContent>
              </Select>
              <Select value={hasPhone} onValueChange={(val: string | null) => { if (val) { setPage(1); setHasPhone(val); } }}>
                <SelectTrigger aria-label="Фильтр по телефону">
                  <SelectValue placeholder="Тел: все" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Тел: все</SelectItem>
                  <SelectItem value="true">С телефоном</SelectItem>
                  <SelectItem value="false">Без телефона</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <LeadsTable
              leads={leads}
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

  const onScheduleChange = (value: string) => {
    setSchedule(value);
    if (project.auto_collection_enabled) void save({ cron_schedule: value });
  };

  const currentPreset = SCHEDULE_PRESETS.find((p) => p.value === schedule);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/30 px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <CalendarClock size={15} className="text-muted-foreground" />
        <span className="font-medium">Автосбор</span>
      </div>

      <label className="flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          checked={project.auto_collection_enabled}
          disabled={saving}
          onChange={(e) => void save({ auto_collection_enabled: e.target.checked, cron_schedule: schedule })}
          className="h-4 w-4 cursor-pointer rounded"
        />
        <span>{project.auto_collection_enabled ? "Включён" : "Выключен"}</span>
      </label>

      <Select value={schedule} onValueChange={onScheduleChange} disabled={saving}>
        <SelectTrigger className="h-8 w-auto min-w-[200px] text-xs">
          <SelectValue placeholder="Расписание" />
        </SelectTrigger>
        <SelectContent>
          {SCHEDULE_PRESETS.map((preset) => (
            <SelectItem key={preset.value} value={preset.value}>{preset.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      {project.auto_collection_enabled && currentPreset && (
        <span className="text-xs text-muted-foreground">
          Следующий запуск: {currentPreset.label.toLowerCase()}. Получите email когда готово.
        </span>
      )}
      {saving && <Loader2 size={13} className="animate-spin text-muted-foreground" />}
    </div>
  );
}

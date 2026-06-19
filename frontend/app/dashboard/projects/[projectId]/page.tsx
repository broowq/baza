"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, ChevronDown, Download, Loader2, Play, RefreshCw, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { motion } from "framer-motion";

import { JobHistory } from "@/components/dashboard/job-history";
import { LeadCards } from "@/components/dashboard/lead-cards";
import { LeadsTable } from "@/components/dashboard/leads-table";
import { PipelineBoard } from "@/components/dashboard/pipeline-board";
import { FunnelBar } from "@/components/dashboard/funnel-bar";
import { LeadDetailDrawer } from "@/components/dashboard/lead-detail-drawer";
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
import type { CollectionJob, Lead, OrgMember, Project } from "@/lib/types";

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

// CRM pipeline stages — used by the bulk «change stage» action. Mirrors the
// 6-stage pipeline (proposal/won have no badge--* variant, hence not in
// STATUS_LABELS above which only covers the legacy 4 statuses).
const BULK_STAGE_LABELS: Record<string, string> = {
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  proposal: "КП отправлено",
  won: "Сделка",
  rejected: "Отказ",
};

function pluralCompanies(n: number): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "новая компания";
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return "новые компании";
  return "новых компаний";
}

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
  // Assignee filter for the table query: "all" | "me" | "none" | <user_id>.
  const [assignedTo, setAssignedTo] = useState("all");
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
  const [viewMode, setViewMode] = useState<"cards" | "table" | "kanban">("cards");
  const [showFilters, setShowFilters] = useState(false);

  // CRM additions.
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [openLeadId, setOpenLeadId] = useState<string | null>(null);
  // Funnel refresh trigger — bumped after collect or any stage change so
  // <FunnelBar> refetches.
  const [funnelKey, setFunnelKey] = useState(0);
  // Full project lead set for the Kanban board (the table is paginated, the
  // board needs all leads). Fetched lazily the first time Kanban is opened.
  const [kanbanLeads, setKanbanLeads] = useState<Lead[]>([]);
  const [kanbanLoading, setKanbanLoading] = useState(false);
  const [kanbanLoaded, setKanbanLoaded] = useState(false);
  // Lifted table selection for the bulk action bar.
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkTag, setBulkTag] = useState("");

  const debouncedSearch = useDebounce(search, 400);
  const leadsTableRef = useRef<HTMLDivElement>(null);

  // Monotonic request counter: only the most recent fetchAll call may write
  // state, so a slow older response can't overwrite a newer filtered one.
  const reqSeq = useRef(0);

  // `background: true` — silent refresh (6s polling, post-job refetch): data is
  // updated without flipping tableLoading, so the table doesn't collapse into
  // skeletons and unmount rows (wiping half-typed notes) mid-run.
  const fetchAll = useCallback(async (background = false) => {
    const seq = ++reqSeq.current;
    if (!background) setTableLoading(true);
    try {
      const query = new URLSearchParams({ page: String(page), per_page: String(perPage), q: debouncedSearch, sort, order });
      if (status !== "all") query.set("status", status);
      if (minScore) query.set("min_score", minScore);
      if (maxScore) query.set("max_score", maxScore);
      if (hasEmail !== "all") query.set("has_email", hasEmail);
      if (hasPhone !== "all") query.set("has_phone", hasPhone);
      if (assignedTo !== "all") query.set("assigned_to", assignedTo);

      const [projectsList, projectLeads, projectJobs, membership, statsData] = await Promise.all([
        api<Project[]>("/projects"),
        api<{ items: Lead[]; total: number }>(`/leads/project/${projectId}/table?${query.toString()}`),
        api<CollectionJob[]>(`/leads/jobs/project/${projectId}`),
        api<{ role: "owner" | "admin" | "member" }>("/organizations/membership"),
        api<{ total: number; enriched: number; with_email: number; avg_score: number }>(`/leads/project/${projectId}/stats`),
      ]);
      // Stale response — a newer fetchAll has started since; drop this one.
      if (seq !== reqSeq.current) return;
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
      if (seq !== reqSeq.current) return;
      const msg = error instanceof Error ? error.message : "";
      if (msg.includes("авториз") || msg.includes("Сессия")) {
        window.location.href = "/login";
        return;
      }
      setError(msg || "Не удалось загрузить проект");
    } finally {
      if (seq === reqSeq.current) {
        setLoading(false);
        setTableLoading(false);
      }
    }
  }, [assignedTo, hasEmail, hasPhone, maxScore, minScore, order, page, perPage, projectId, debouncedSearch, sort, status]);

  const hasActiveJobs = jobs.some((j) => j.status === "queued" || j.status === "running");

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    if (!hasActiveJobs) return;
    const id = setInterval(() => void fetchAll(true), 6000);
    return () => clearInterval(id);
  }, [hasActiveJobs, fetchAll]);

  // Org members — fetched once for the board + assignee filter/bulk dropdowns.
  useEffect(() => {
    let cancelled = false;
    api<OrgMember[]>("/organizations/members")
      .then((data) => { if (!cancelled) setMembers(Array.isArray(data) ? data : []); })
      .catch(() => { /* non-fatal: dropdowns simply show no per-member options */ });
    return () => { cancelled = true; };
  }, [projectId]);

  // Pull the full lead set for the Kanban board (the table view is paginated).
  // GET /leads/project/{id} returns up to 5000; refetch on demand after edits.
  const fetchKanbanLeads = useCallback(async () => {
    setKanbanLoading(true);
    try {
      const all = await api<Lead[]>(`/leads/project/${projectId}`);
      setKanbanLeads(Array.isArray(all) ? all : []);
      setKanbanLoaded(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось загрузить доску");
    } finally {
      setKanbanLoading(false);
    }
  }, [projectId]);

  // Load the board's full list the first time Kanban is opened.
  useEffect(() => {
    if (viewMode === "kanban" && !kanbanLoaded && !kanbanLoading) void fetchKanbanLeads();
  }, [viewMode, kanbanLoaded, kanbanLoading, fetchKanbanLeads]);

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
              if (Array.isArray(parsed)) {
                // Transient backend errors can emit `data: []` mid-run; don't
                // let such a tick wipe the existing job history.
                setJobs((prev) => (parsed.length === 0 && prev.length > 0 ? prev : parsed));
              }
            } catch { /* ignore */ }
          }
        }
      } catch { /* Connection closed */ }
    })();

    return () => { cancelled = true; controller.abort(); };
  }, [projectId]);

  // Toast the outcome when a collect job finishes — how many NEW companies were
  // added this dose, or an honest "nothing new" when the query is exhausted.
  const lastCollectToastRef = useRef<string | null>(null);
  const collectToastInitRef = useRef(false);
  useEffect(() => {
    const last = jobs.find((j) => j.kind === "collect");
    if (!last) return;
    if (!collectToastInitRef.current) {
      // First load — remember current state, don't toast historical completions.
      collectToastInitRef.current = true;
      if (last.status === "done") lastCollectToastRef.current = last.id;
      return;
    }
    if (last.status !== "done" || lastCollectToastRef.current === last.id) return;
    lastCollectToastRef.current = last.id;
    const n = last.added_count ?? 0;
    // New leads landed — refresh the funnel and (if open) the board.
    if (n > 0) {
      setFunnelKey((k) => k + 1);
      setKanbanLoaded(false);
    }
    if (n > 0) toast.success(`Добавлено ${n} ${pluralCompanies(n)}`);
    // 0 added — show the backend's honest reason (quota hit vs. nothing left).
    else toast(last.error || "Новых компаний не найдено — всё доступное по запросу уже собрано. Измените нишу/гео или включите автосбор.");
  }, [jobs]);

  // Toast the outcome when an enrich job finishes. Surfaces the backend's
  // honest reason (e.g. "источники недоступны — проверьте API-ключи") instead
  // of leaving the user to wonder why "обогащено"/"с email" didn't move.
  const lastEnrichToastRef = useRef<string | null>(null);
  const enrichToastInitRef = useRef(false);
  useEffect(() => {
    const last = jobs.find((j) => j.kind === "enrich");
    if (!last) return;
    if (!enrichToastInitRef.current) {
      enrichToastInitRef.current = true;
      if (last.status === "done" || last.status === "failed") lastEnrichToastRef.current = last.id;
      return;
    }
    if ((last.status !== "done" && last.status !== "failed") || lastEnrichToastRef.current === last.id) return;
    lastEnrichToastRef.current = last.id;
    if (last.status === "failed") toast.error(last.error || "Обогащение не удалось");
    else if (last.error) toast(last.error);
    else toast.success(`Обогащение завершено: обработано ${last.enriched_count}`);
  }, [jobs]);

  // Synchronous re-entrancy lock: blocks a fast double-click from firing a
  // second POST before React re-renders the disabled button (that second click
  // was hitting the "сбор уже запущен"/"перегруз" guard and showing an error).
  const submittingJobRef = useRef(false);
  const queueJob = async (kind: "collect" | "enrich", limit: number) => {
    if (submittingJobRef.current || running) return;
    submittingJobRef.current = true;
    setRunning(true);
    try {
      await api(`/leads/project/${projectId}/${kind}`, {
        method: "POST",
        body: JSON.stringify({ lead_limit: limit }),
      });
      toast.success(kind === "collect" ? "Собираем новые компании…" : "Задача обогащения добавлена в очередь");
      await fetchAll(true);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "";
      // The concurrency guards (409 "уже запущен" / 429 "Превышен лимит") aren't
      // failures — the previous run is simply still going. Show a calm hint.
      if (/уже запущен/i.test(msg)) {
        toast.info("Сбор уже идёт — дождитесь завершения текущего.");
      } else if (/одновременных задач|Превышен лимит/i.test(msg)) {
        toast.info("Слишком много задач сразу — дождитесь завершения текущих.");
      } else {
        toast.error(msg || "Не удалось запустить задачу");
      }
    } finally {
      submittingJobRef.current = false;
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
      await fetchAll(true);
      return true;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось запустить обогащение");
      return false;
    }
  };

  // Single source of truth for lead patches — keeps cards/table/board in sync.
  // A status change also refreshes the funnel (counts/value per stage move).
  const handleLeadUpdate = useCallback((leadId: string, patch: Partial<Lead>) => {
    setLeads((prev) => prev.map((l) => (l.id === leadId ? { ...l, ...patch } : l)));
    setKanbanLeads((prev) => prev.map((l) => (l.id === leadId ? { ...l, ...patch } : l)));
    if ("status" in patch || "deal_value" in patch || "assigned_to_user_id" in patch) {
      setFunnelKey((k) => k + 1);
    }
  }, []);

  // Bulk action over the current table selection. Calls the bulk endpoint then
  // refetches both the table and (if loaded) the board, clearing the selection.
  const runBulkAction = async (
    body:
      | { action: "stage"; status: string }
      | { action: "assign"; assigned_to_user_id: string | null }
      | { action: "add_tag"; tag: string }
      | { action: "delete" },
  ) => {
    if (selectedIds.length === 0 || bulkBusy) return;
    setBulkBusy(true);
    try {
      const res = await api<{ updated: number }>(`/leads/project/${projectId}/bulk`, {
        method: "POST",
        body: JSON.stringify({ lead_ids: selectedIds, ...body }),
      });
      toast.success(`Обновлено: ${res.updated}`);
      setSelectedIds([]);
      setBulkTag("");
      setFunnelKey((k) => k + 1);
      await fetchAll(true);
      if (kanbanLoaded) await fetchKanbanLeads();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось выполнить действие");
    } finally {
      setBulkBusy(false);
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
    (hasPhone !== "all" ? 1 : 0) +
    (assignedTo !== "all" ? 1 : 0);

  const resetFilters = () => {
    setPage(1);
    setStatus("all");
    setMinScore("");
    setMaxScore("");
    setHasEmail("all");
    setHasPhone("all");
    setAssignedTo("all");
  };

  // Label for the assignee filter trigger (value → display name).
  const assigneeLabel = (v: string | null): string => {
    if (!v || v === "all") return "Ответственный: все";
    if (v === "me") return "Мои";
    if (v === "none") return "Не назначены";
    const m = members.find((x) => x.user_id === v);
    return m ? (m.full_name || m.email) : "Ответственный";
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
          <Link href="/dashboard" className="t-40 hover:text-[var(--t-100)] transition-colors">Проекты</Link>
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
              <span
                key={seg}
                className="chip chip-sans max-w-full"
                style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}
              >
                {seg}
              </span>
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
            title="Добавляет до 10 новых компаний (без повторов). Сначала из нашей базы, затем живой поиск."
            onClick={() => queueJob("collect", 10)}
          >
            {collectBusy ? (
              <><Loader2 size={12} className="animate-spin" /> Собираем…</>
            ) : (
              <><Play size={11} /> Собрать 10</>
            )}
          </button>
          <button
            className="btn btn-ghost"
            disabled={running || enrichBusy || !canManage}
            title="Обогатить лиды без контактов (до 200 за раз)"
            onClick={() => queueJob("enrich", 200)}
          >
            {enrichBusy ? (
              <><Loader2 size={12} className="animate-spin" /> Обогащаем…</>
            ) : (
              <><Sparkles size={12} /> Обогатить новые</>
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
            {/* Pipeline funnel — refreshes on stage changes / after collect */}
            <FunnelBar projectId={projectId} refreshKey={funnelKey} />

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
                    <span className="ml-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-[var(--mint)] px-1 text-[10.5px] font-semibold leading-none text-[var(--on-accent)] tnum">
                      {activeFilterCount}
                    </span>
                  )}
                  <ChevronDown
                    size={13}
                    className="transition-transform"
                    style={{ transform: showFilters ? "rotate(180deg)" : "none", opacity: 0.55 }}
                  />
                </button>

                {/* View toggle — Cards | Table | Kanban */}
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
                  <button
                    type="button"
                    className={`seg-btn${viewMode === "kanban" ? " active" : ""}`}
                    aria-pressed={viewMode === "kanban"}
                    onClick={() => setViewMode("kanban")}
                  >
                    Канбан
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

                  <div className="space-y-1.5">
                    <div className="eyebrow">Ответственный</div>
                    <Select value={assignedTo} onValueChange={(val: string | null) => { if (val) { setPage(1); setAssignedTo(val); } }}>
                      <SelectTrigger className="w-full" aria-label="Фильтр по ответственному">
                        <SelectValue placeholder="Ответственный: все">
                          {(v: string | null) => assigneeLabel(v)}
                        </SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Все</SelectItem>
                        <SelectItem value="me">Мои</SelectItem>
                        <SelectItem value="none">Не назначены</SelectItem>
                        {members.map((m) => (
                          <SelectItem key={m.user_id} value={m.user_id}>
                            {m.full_name || m.email}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
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

            {/* Bulk action bar — visible when ≥1 lead is selected in the table */}
            {viewMode === "table" && selectedIds.length > 0 && (
              <div className="panel-flat flex flex-wrap items-center gap-2.5 px-4" style={{ paddingTop: 10, paddingBottom: 10 }}>
                <span className="mono-cap t-72 mr-1">Выбрано: {selectedIds.length}</span>

                {/* Change stage */}
                <Select value="" onValueChange={(val: string | null) => { if (val) void runBulkAction({ action: "stage", status: val }); }} disabled={bulkBusy}>
                  <SelectTrigger className="h-8 w-auto min-w-[150px] text-xs" aria-label="Сменить этап">
                    <SelectValue placeholder="Сменить этап">{() => "Сменить этап"}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(BULK_STAGE_LABELS).map(([value, label]) => (
                      <SelectItem key={value} value={value}>{label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* Assign */}
                <Select value="" onValueChange={(val: string | null) => { if (val) void runBulkAction({ action: "assign", assigned_to_user_id: val === "__none__" ? null : val }); }} disabled={bulkBusy}>
                  <SelectTrigger className="h-8 w-auto min-w-[160px] text-xs" aria-label="Назначить ответственного">
                    <SelectValue placeholder="Назначить">{() => "Назначить"}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Снять назначение</SelectItem>
                    {members.map((m) => (
                      <SelectItem key={m.user_id} value={m.user_id}>{m.full_name || m.email}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* Add tag */}
                <div className="flex items-center gap-1.5">
                  <Input
                    className="h-8 w-32 text-xs"
                    placeholder="+ тег"
                    value={bulkTag}
                    disabled={bulkBusy}
                    aria-label="Тег для массового добавления"
                    onChange={(e) => setBulkTag(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && bulkTag.trim()) { e.preventDefault(); void runBulkAction({ action: "add_tag", tag: bulkTag.trim() }); } }}
                  />
                  <Button size="sm" variant="secondary" disabled={bulkBusy || !bulkTag.trim()} onClick={() => void runBulkAction({ action: "add_tag", tag: bulkTag.trim() })}>
                    Добавить
                  </Button>
                </div>

                {/* Delete */}
                <Button size="sm" variant="ghost" className="text-status-offline" disabled={bulkBusy} onClick={() => void runBulkAction({ action: "delete" })}>
                  <Trash2 size={13} className="mr-1" /> Удалить
                </Button>

                <Button size="sm" variant="ghost" className="ml-auto" disabled={bulkBusy} onClick={() => setSelectedIds([])}>
                  Снять выбор
                </Button>
                {bulkBusy && <Loader2 size={13} className="animate-spin text-muted-foreground" />}
              </div>
            )}

            {/* Cards view */}
            {viewMode === "cards" && (
              <LeadCards
                leads={leads}
                loading={tableLoading}
                onLeadUpdate={handleLeadUpdate}
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
                selectedIds={selectedIds}
                onSelectionChange={setSelectedIds}
                onLeadUpdate={handleLeadUpdate}
                onLeadDelete={(leadId) => {
                  setLeads((prev) => prev.filter((l) => l.id !== leadId));
                  setKanbanLeads((prev) => prev.filter((l) => l.id !== leadId));
                  setTotal((prev) => Math.max(0, prev - 1));
                  setFunnelKey((k) => k + 1);
                }}
              />
            )}

            {/* Kanban (pipeline) view — needs ALL project leads, not just the page */}
            {viewMode === "kanban" && (
              kanbanLoading && !kanbanLoaded ? (
                <Loader />
              ) : (
                <PipelineBoard
                  leads={kanbanLeads}
                  members={members}
                  onLeadUpdate={handleLeadUpdate}
                  onOpenLead={setOpenLeadId}
                  orgRole={orgRole}
                />
              )
            )}

            {/* Pagination — hidden in Kanban (the board shows the full set) */}
            {viewMode !== "kanban" && (
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
            )}
          </div>
        </TabsContent>

        <TabsContent value="jobs">
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Статус сбора и обогащения в реальном времени</p>
            <JobHistory jobs={jobs} />
          </div>
        </TabsContent>
      </Tabs>

      {/* Page-level lead drawer — opened from the Kanban board */}
      <LeadDetailDrawer
        leadId={openLeadId}
        onClose={() => setOpenLeadId(null)}
        onLeadUpdate={handleLeadUpdate}
      />
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

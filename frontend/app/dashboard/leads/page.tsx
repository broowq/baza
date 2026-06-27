"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useSearchParams } from "next/navigation";

import { api } from "@/lib/api";
import { useAuthGuard, useDebounce } from "@/lib/hooks";
import type { Lead, Project } from "@/lib/types";
import { LeadDetailDrawer } from "@/components/dashboard/lead-detail-drawer";

type PaginatedLeads = {
  items: Lead[];
  total: number;
  page: number;
  per_page: number;
};

const PER_PAGE = 50;

const STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  proposal: "КП отправлено",
  won: "Сделка",
  rejected: "Отклонён",
};

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "Все статусы" },
  { value: "new", label: "Новый" },
  { value: "contacted", label: "Связались" },
  { value: "qualified", label: "Квалифицирован" },
  { value: "proposal", label: "КП отправлено" },
  { value: "won", label: "Сделка" },
  { value: "rejected", label: "Отклонён" },
];

const STATUS_BADGE_CLASS: Record<string, string> = {
  new: "badge--new",
  contacted: "badge--contacted",
  qualified: "badge--qualified",
  rejected: "badge--rejected",
};

/* proposal/won have no dedicated CSS badge variant — derive themed inline
   styles from tokens (amber for proposal, mint for won), same as the drawer. */
const STATUS_BADGE_STYLE: Record<string, React.CSSProperties> = {
  proposal: {
    background: "rgba(251, 191, 36, 0.10)",
    borderColor: "rgba(251, 191, 36, 0.28)",
    color: "var(--amber)",
  },
  won: {
    background: "rgba(168, 197, 192, 0.12)",
    borderColor: "rgba(168, 197, 192, 0.32)",
    color: "var(--mint)",
  },
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_BADGE_CLASS[status];
  const style = STATUS_BADGE_STYLE[status];
  return (
    <span className={`badge ${cls ?? ""}`} style={style}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function pluralLeads(n: number): string {
  const rule = new Intl.PluralRules("ru").select(n);
  if (rule === "one") return "лид";
  if (rule === "few") return "лида";
  return "лидов";
}

function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

function LeadsHub() {
  const authed = useAuthGuard();
  const searchParams = useSearchParams();

  // URL-driven initial state: ?q= prefills the search, ?open=<id> opens a drawer.
  const initialQ = searchParams.get("q") ?? "";
  const initialOpen = searchParams.get("open");

  const [search, setSearch] = useState(initialQ);
  const debouncedSearch = useDebounce(search, 300);
  const [status, setStatus] = useState("all");
  const [projectId, setProjectId] = useState("all");
  const [page, setPage] = useState(1);

  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [projects, setProjects] = useState<Project[]>([]);
  const [openLeadId, setOpenLeadId] = useState<string | null>(initialOpen);

  const listRef = useRef<HTMLDivElement | null>(null);

  // Reset to page 1 whenever a filter or the (debounced) query changes so the
  // user never lands on an out-of-range page after narrowing the result set.
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, status, projectId]);

  // Load project options once (for the project filter dropdown).
  useEffect(() => {
    if (!authed) return;
    api<Project[]>("/projects")
      .then((rows) => setProjects(Array.isArray(rows) ? rows : []))
      .catch(() => {});
  }, [authed]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        search: debouncedSearch.trim(),
        status,
        sort: "score",
        order: "desc",
        page: String(page),
        per_page: String(PER_PAGE),
      });
      if (projectId !== "all") params.set("project_id", projectId);
      const data = await api<PaginatedLeads>(`/leads/all?${params.toString()}`);
      setLeads(Array.isArray(data.items) ? data.items : []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить лиды");
      setLeads([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [debouncedSearch, status, projectId, page]);

  useEffect(() => {
    if (authed) void load();
  }, [authed, load]);

  // After a lead edit in the drawer, refetch the current page so the list
  // reflects the change (status badge, last contact, etc.).
  const handleLeadUpdate = useCallback(() => {
    void load();
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const goToPage = (next: number) => {
    setPage(next);
    listRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const hasFilters =
    debouncedSearch.trim().length > 0 || status !== "all" || projectId !== "all";

  const projectNameById = useMemo(() => {
    const map = new Map<string, string>();
    projects.forEach((p) => map.set(p.id, p.name));
    return map;
  }, [projects]);

  if (!authed) {
    return (
      <main className="mx-auto max-w-[1100px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <ListSkeleton />
      </main>
    );
  }

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-[1100px] space-y-7 px-4 py-8 sm:px-6 lg:px-10 lg:py-10"
    >
      {/* ── Header ── */}
      <div>
        <div className="eyebrow mb-2">crm · все лиды</div>
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <h1 className="h1" style={{ fontSize: 44 }}>Все лиды</h1>
          {!loading && !error && (
            <span className="mono-cap t-40 mb-1.5">
              {total} {pluralLeads(total)}
            </span>
          )}
        </div>
        <p className="t-56 text-[13px] mt-2">
          Лиды со всех проектов организации в одном месте — ищите и фильтруйте по всей базе.
        </p>
      </div>

      {/* ── Filters ── */}
      <div className="panel p-3 flex flex-wrap items-center gap-2">
        <input
          className="input flex-1 min-w-[200px]"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Поиск по компании, email, телефону, городу..."
          aria-label="Поиск лидов"
        />
        <select
          className="input w-auto"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="Статус"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          className="input w-auto max-w-[220px]"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          aria-label="Проект"
        >
          <option value="all">Все проекты</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* ── Body ── */}
      <div ref={listRef}>
        {loading ? (
          <ListSkeleton />
        ) : error ? (
          <div className="panel p-8 text-center space-y-4">
            <p className="t-72 text-sm">{error}</p>
            <button className="btn btn-brand" onClick={() => void load()}>
              Повторить
            </button>
          </div>
        ) : leads.length === 0 ? (
          <div className="empty-state panel-glass elev-1">
            <div className="empty-state__icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="var(--mint)" strokeWidth="1.5" style={{ width: 28, height: 28 }}>
                <circle cx="11" cy="11" r="7" />
                <path d="M21 21l-4.3-4.3" />
              </svg>
            </div>
            <h3 className="empty-state__title">Лидов не найдено</h3>
            <p className="empty-state__body">
              {hasFilters
                ? "Попробуйте изменить запрос или сбросить фильтры."
                : "Соберите лиды в проектах — и они появятся здесь."}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {leads.map((lead, idx) => (
              <LeadRow
                key={lead.id}
                lead={lead}
                projectName={lead.project_name || projectNameById.get(lead.project_id ?? "") || ""}
                index={idx}
                onOpen={() => setOpenLeadId(lead.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Pagination ── */}
      {!loading && !error && total > 0 && (
        <div className="flex flex-col items-center gap-2 t-56 text-sm sm:flex-row sm:justify-between">
          <span>Итого: {total} {pluralLeads(total)}</span>
          <div className="flex items-center gap-3">
            <button
              className="btn btn-ghost"
              disabled={page <= 1}
              onClick={() => goToPage(Math.max(1, page - 1))}
            >
              Назад
            </button>
            <span className="text-xs tnum t-56">
              Страница {page} из {totalPages}
            </span>
            <button
              className="btn btn-ghost"
              disabled={page >= totalPages}
              onClick={() => goToPage(page + 1)}
            >
              Вперёд
            </button>
          </div>
        </div>
      )}

      <LeadDetailDrawer
        leadId={openLeadId}
        onClose={() => setOpenLeadId(null)}
        onLeadUpdate={handleLeadUpdate}
      />
    </motion.main>
  );
}

function LeadRow({
  lead,
  projectName,
  index,
  onOpen,
}: {
  lead: Lead;
  projectName: string;
  index: number;
  onOpen: () => void;
}) {
  return (
    <motion.button
      type="button"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, delay: Math.min(index * 0.03, 0.2) }}
      onClick={onOpen}
      className="lead-card group relative text-left w-full focus-ring"
    >
      <div className="lead-card__row" style={{ gap: 12 }}>
        {/* Company + project */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="text-[14px] leading-snug truncate"
              style={{ color: "var(--t-100)", fontWeight: 500 }}
              title={lead.company}
            >
              {lead.company}
            </span>
            {projectName && (
              <span className="chip shrink-0" title={projectName}>
                {projectName}
              </span>
            )}
          </div>
          <div className="lead-card__meta mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            {lead.city && <span className="t-72 truncate">{lead.city}</span>}
            {lead.city && (lead.phone || lead.email) && <span className="t-28">·</span>}
            {lead.phone && (
              <span className="mono t-72 tnum" title={lead.phone}>{lead.phone}</span>
            )}
            {lead.phone && lead.email && <span className="t-28">·</span>}
            {lead.email && (
              <span className="t-72 truncate" title={lead.email}>{lead.email}</span>
            )}
            {!lead.phone && !lead.email && (
              <span className="t-40">нет контактов</span>
            )}
          </div>
        </div>

        {/* Score */}
        <div className="hidden sm:flex items-center gap-2 shrink-0" aria-label={`Score ${lead.score}`}>
          <div className="h-1 w-16 overflow-hidden rounded-full" style={{ background: "var(--surface-hover)" }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max(0, Math.min(100, lead.score))}%`, background: "var(--mint)" }}
            />
          </div>
          <span className="mono text-[11.5px] tnum t-72 w-6 text-right">{lead.score}</span>
        </div>

        {/* Last contact */}
        <span className="mono shrink-0 text-[11.5px] tnum t-48 hidden md:inline w-12 text-right">
          {formatDate(lead.last_contacted_at)}
        </span>

        {/* Status */}
        <div className="shrink-0">
          <StatusBadge status={lead.status} />
        </div>
      </div>
    </motion.button>
  );
}

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-2.5">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-[64px] animate-pulse rounded-2xl border border-[var(--line)] bg-[var(--surface-1)]"
        />
      ))}
    </div>
  );
}

export default function AllLeadsPage() {
  // useSearchParams requires a Suspense boundary in the App Router.
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-[1100px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
          <ListSkeleton />
        </main>
      }
    >
      <LeadsHub />
    </Suspense>
  );
}

"use client";

import { FormEvent, useEffect, useState, useCallback } from "react";
import { Plus, ChevronRight, Trash2, Pencil, Sparkles, Search, Wand2, Loader2, X } from "lucide-react";

import { VoiceInput } from "@/components/voice-input";
import { toast } from "sonner";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Loader } from "@/components/ui/loader";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogMedia,
} from "@/components/ui/alert-dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { projectsN, seatsN } from "@/lib/plural";
import { getOrgId, setOrgId } from "@/lib/auth";
import { formatPlan } from "@/lib/plans";
import { useAuthGuard } from "@/lib/hooks";
import type { CollectionJob, Organization, Project, PromptEnhanceResponse } from "@/lib/types";

type ProjectForm = {
  prompt: string;
  name: string;
  niche: string;
  geography: string;
  segments: string;
};

const initialProject: ProjectForm = {
  prompt: "",
  name: "",
  niche: "",
  geography: "",
  segments: "",
};

const JOB_STATUS_MAP: Record<string, string> = {
  queued: "В очереди",
  running: "В работе",
  done: "Готово",
  failed: "Ошибка",
};

// Onboarding preview rows. Real values come from the public /public/landing feed
// (demo project, contacts masked to booleans); this fallback keeps the table
// populated before the fetch resolves / if it fails.
type DemoSample = { company: string; city: string; score: number; has_email: boolean; has_phone: boolean };
const DEMO_SAMPLE_FALLBACK: DemoSample[] = [
  { company: "Хонда-Сан, автосервис", city: "Новосибирск", score: 88, has_email: true, has_phone: true },
  { company: "Пятое колесо, автосервис", city: "Томск", score: 86, has_email: true, has_phone: true },
  { company: "Гибрид-Сервис", city: "Томск", score: 81, has_email: true, has_phone: true },
  { company: "ИТ-Партнёр", city: "Екатеринбург", score: 80, has_email: true, has_phone: true },
  { company: "Мастер Шин", city: "Екатеринбург", score: 77, has_email: false, has_phone: true },
  { company: "СпецТехникаСиб", city: "Кемерово", score: 76, has_email: true, has_phone: true },
];

// Кнопка создания проекта. При исчерпанном лимите тарифа блокируется сразу,
// с тултипом и ссылкой на тарифы — а не отказом в конце двухшагового диалога.
function CreateProjectButton({
  limitReached,
  onClick,
  className,
  style,
  children,
}: {
  limitReached: boolean;
  onClick: () => void;
  className: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
}) {
  const router = useRouter();
  if (!limitReached) {
    return (
      <button type="button" onClick={onClick} className={className} style={style}>
        {children}
      </button>
    );
  }
  // На таче hover-тултипа нет — по тапу объясняем лимит toast'ом с действием.
  // На десктопе остаётся тултип (hover/focus), клик дублирует его toast'ом.
  const showLimitToast = () =>
    toast("Достигнут лимит проектов тарифа", {
      action: { label: "Тарифы", onClick: () => router.push("/plans") },
    });
  return (
    <TooltipProvider>
      <Tooltip>
        {/* aria-disabled вместо disabled: disabled-кнопка не получает hover/focus,
            и тултип с объяснением никогда бы не показался. */}
        <TooltipTrigger
          render={
            <button
              type="button"
              aria-disabled
              onClick={showLimitToast}
              className={`${className} cursor-not-allowed opacity-50`}
              style={style}
            />
          }
        >
          {children}
        </TooltipTrigger>
        <TooltipContent>
          <span>
            Достигнут лимит проектов тарифа —{" "}
            <Link href="/plans" className="underline underline-offset-2">
              обновите тариф
            </Link>
          </span>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function DashboardPage() {
  const authed = useAuthGuard();
  const [loading, setLoading] = useState(true);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [org, setOrg] = useState<Organization | null>(null);
  const [orgRole, setOrgRole] = useState<"owner" | "admin" | "member">("member");
  const [projects, setProjects] = useState<Project[]>([]);
  const [latestJobs, setLatestJobs] = useState<Record<string, CollectionJob | null>>({});
  const [allJobs, setAllJobs] = useState<CollectionJob[]>([]);
  const [projectForm, setProjectForm] = useState<ProjectForm>(initialProject);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [switchingOrg, setSwitchingOrg] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [editTarget, setEditTarget] = useState<Project | null>(null);
  const [editForm, setEditForm] = useState<ProjectForm>(initialProject);
  const [saving, setSaving] = useState(false);
  const [enhancing, setEnhancing] = useState(false);
  const [enhanced, setEnhanced] = useState<PromptEnhanceResponse | null>(null);
  const [formStep, setFormStep] = useState<"prompt" | "review">("prompt");
  const [error, setError] = useState<string | null>(null);
  const [demoSamples, setDemoSamples] = useState<DemoSample[] | null>(null);

  // Real sample rows for the onboarding preview, from the public stats feed.
  useEffect(() => {
    let cancelled = false;
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
    fetch(`${base}/public/landing`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled && d && d.available && Array.isArray(d.samples) && d.samples.length) {
          setDemoSamples(d.samples as DemoSample[]);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const bootstrap = useCallback(async () => {
    setError(null);
    try {
      // Critical calls: /auth/me determines session validity. If it throws an
      // auth error after refresh-retry inside api(), redirect to login rather
      // than rendering a blank dashboard.
      let orgs: Organization[] | null = null;
      try {
        [orgs] = await Promise.all([
          api<Organization[]>("/organizations/my-list"),
          api<{ email: string; is_admin: boolean; full_name?: string }>("/auth/me"),
        ]);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "";
        if (msg.includes("авториз") || msg.includes("Сессия")) {
          window.location.href = "/login";
          return;
        }
        throw e;
      }

      if (orgs) {
        setOrganizations(orgs);
        const currentOrg = orgs.find((o) => o.id === getOrgId()) ?? orgs[0];
        if (currentOrg) {
          setOrgId(currentOrg.id);
          setOrg(currentOrg);

          const [membership, prs] = await Promise.all([
            api<{ role: "owner" | "admin" | "member" }>("/organizations/membership").catch(() => null),
            api<Project[]>("/projects").catch(() => null),
          ]);
          if (membership) setOrgRole(membership.role);
          if (prs) {
            setProjects(prs);
            const jobLists = await Promise.all(
              prs.map(async (p) => {
                const jobs = await api<CollectionJob[]>(`/leads/jobs/project/${p.id}`).catch(() => []);
                return [p.id, jobs] as const;
              })
            );
            // latestJobs = most-recent job per project (for per-card display);
            // allJobs = every job across every project (for org-level totals).
            setLatestJobs(Object.fromEntries(jobLists.map(([id, jobs]) => [id, jobs[0] ?? null])));
            setAllJobs(jobLists.flatMap(([, jobs]) => jobs));
          }
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Не удалось загрузить данные";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (authed) void bootstrap(); }, [authed, bootstrap]);

  const refreshProjects = async () => {
    const prs = await api<Project[]>("/projects");
    setProjects(prs);
  };

  const enhancePrompt = async () => {
    if (!projectForm.prompt.trim() || projectForm.prompt.trim().length < 5) {
      toast.error("Опишите ваш бизнес подробнее (минимум 5 символов)");
      return;
    }
    setEnhancing(true);
    try {
      const result = await api<PromptEnhanceResponse>("/projects/enhance-prompt", {
        method: "POST",
        body: JSON.stringify({ prompt: projectForm.prompt.trim() }),
      });
      setEnhanced(result);
      setProjectForm((p) => ({
        ...p,
        name: result.project_name || p.name,
        niche: result.niche || p.niche,
        geography: result.geography || p.geography,
        segments: (result.segments || []).join(", "),
      }));
      setFormStep("review");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось проанализировать запрос");
    } finally {
      setEnhancing(false);
    }
  };

  const createProject = async (e: FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({
          prompt: projectForm.prompt || undefined,
          name: projectForm.name,
          niche: projectForm.niche,
          geography: projectForm.geography,
          segments: projectForm.segments.split(",").map((s) => s.trim()).filter(Boolean),
          // Жёсткие исключения из enhance-ответа («только b2b» → не розница).
          // Без этого поля бэкенд-автоэнханс не срабатывает (niche уже
          // заменена) и ограничения пользователя терялись насовсем.
          excluded_segments: enhanced?.excluded_segments ?? [],
          website_preference: enhanced?.website_preference ?? "any",
        }),
      });
      setProjectForm(initialProject);
      setShowForm(false);
      setFormStep("prompt");
      setEnhanced(null);
      await refreshProjects();
      toast.success("Проект создан");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось создать проект");
    } finally {
      setCreating(false);
    }
  };

  const deleteProject = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api(`/projects/${deleteTarget.id}`, { method: "DELETE" });
      setDeleteTarget(null);
      await refreshProjects();
      toast.success("Проект удалён");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось удалить проект");
    } finally {
      setDeleting(false);
    }
  };

  const openEditDialog = (project: Project) => {
    setEditForm({
      prompt: project.prompt || "",
      name: project.name,
      niche: project.niche,
      geography: project.geography,
      segments: project.segments.join(", "),
    });
    setEditTarget(project);
  };

  const updateProject = async (e: FormEvent) => {
    e.preventDefault();
    if (!editTarget) return;
    setSaving(true);
    try {
      await api(`/projects/${editTarget.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...editForm,
          segments: editForm.segments.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });
      setEditTarget(null);
      await refreshProjects();
      toast.success("Проект обновлён");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить проект");
    } finally {
      setSaving(false);
    }
  };

  if (!authed || loading) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-14">
        <Loader />
      </main>
    );
  }

  if (error) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-14">
        <div className="panel p-8 text-center space-y-4">
          <p className="t-72 text-sm">{error}</p>
          <button
            className="btn btn-brand"
            onClick={() => { setLoading(true); void bootstrap(); }}
          >
            Повторить
          </button>
        </div>
      </main>
    );
  }

  const canManage = orgRole === "owner" || orgRole === "admin";
  const usagePercent = org ? Math.min(100, Math.round(((org.leads_used_current_month ?? 0) / (org.leads_limit_per_month || 1)) * 100)) : 0;
  const projectsRemaining = org ? Math.max(0, org.projects_limit - projects.length) : 0;
  const projectLimitReached = !!org && projects.length >= org.projects_limit;

  const roleLabel: Record<string, string> = {
    owner: "Владелец",
    admin: "Админ",
    member: "Участник",
  };

  // Derive aggregate metrics from already-fetched data — no new API calls.
  // Sum across ALL jobs of ALL projects (not just the latest per project) so
  // the «по всем проектам» totals reflect the full collection history.
  const totalLeads = allJobs.reduce((acc, job) => acc + (job.added_count ?? 0), 0);
  // TODO: replace with a lead-level stats endpoint — summing enriched_count over jobs double-counts re-enriched leads and can exceed the total. Until then, clamp to the collected total.
  const totalEnriched = Math.min(totalLeads, allJobs.reduce((acc, job) => acc + (job.enriched_count ?? 0), 0));
  const activeJobs = allJobs.filter((j) => j.status === "running").length;

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-[1180px] space-y-8 px-4 py-8 sm:px-6 lg:px-10 lg:py-10"
    >
      {/* ── Workspace card (v4 elevated) ── */}
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="panel elev-2 p-5 sm:p-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10">
          {/* Left: org + chips */}
          <div className="lg:col-span-7 min-w-0">
            <div className="eyebrow mb-3">workspace</div>
            <div className="flex items-center gap-3 flex-wrap">
              {organizations.length > 1 ? (
                <Select
                  value={org?.id ?? ""}
                  disabled={switchingOrg}
                  onValueChange={async (val) => {
                    if (!val) return;
                    const selected = organizations.find((item) => item.id === val);
                    if (!selected || switchingOrg) return;
                    setSwitchingOrg(true);
                    setOrgId(selected.id);
                    setOrg(selected);
                    // Clear the previous org's data so org A's stats/jobs never
                    // render under org B's name while the refetch is in flight.
                    setProjects([]);
                    setLatestJobs({});
                    setAllJobs([]);
                    setLoading(true);
                    try {
                      // Full bootstrap re-fetches membership, projects AND
                      // per-project jobs under the new X-Org-Id. It never
                      // rejects (errors are caught inside and shown via the
                      // error panel), so no try/catch-toast here.
                      await bootstrap();
                    } finally {
                      setSwitchingOrg(false);
                    }
                  }}
                >
                  <SelectTrigger className="rounded-full border border-[var(--line-2)] px-4 py-1.5 text-[26px] font-light tracking-tight text-[var(--t-100)] outline-none focus:border-[var(--line-3)] h-auto max-w-[70vw] sm:max-w-sm" style={{ background: "var(--surface-input)" }}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {organizations.map((item) => (
                      <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <h2 className="h2 truncate min-w-0 max-w-full" style={{ fontSize: "clamp(22px, 6vw, 32px)" }}>{org?.name ?? "Организация"}</h2>
              )}
              {org?.plan && (
                <span className="chip chip-mint" style={{ padding: "4px 10px" }}>
                  <span className="dot dot-mt" style={{ width: 5, height: 5 }} />
                  {formatPlan(org.plan)}
                </span>
              )}
              <span className="chip">{roleLabel[orgRole] ?? orgRole}</span>
            </div>
            <div className="mono-cap mt-3 flex items-center flex-wrap" style={{ gap: "0 4px" }}>
              <span>{projectsN(projects.length)}</span>
              <span className="sep-dot mx-2" />
              <span>{org?.users_limit ? seatsN(org.users_limit) : "—"}</span>
            </div>
          </div>

          {/* Right: quota with v-hairline. Free = разовый пробный доступ:
              счётчик НЕ сбрасывается 1-го числа — не обещаем этого в подписи. */}
          <div className="lg:col-span-5 lg:v-hairline lg:pl-10 min-w-0">
            <div className="eyebrow mb-3">{org?.plan === "free" ? "пробный доступ · лиды" : "квота · лиды"}</div>
            <div className="h2 tnum mono truncate min-w-0" style={{ fontSize: "clamp(22px, 6vw, 32px)" }}>
              {(org?.leads_used_current_month ?? 0).toLocaleString("ru-RU")}{" "}
              <span className="t-40" style={{ fontWeight: 200 }}>/ {(org?.leads_limit_per_month ?? 0).toLocaleString("ru-RU")}</span>
            </div>
            <div className="prog mt-5">
              <i style={{ width: `${usagePercent}%`, background: usagePercent >= 90 ? "var(--rose)" : usagePercent >= 70 ? "linear-gradient(90deg,var(--t-100),var(--amber))" : "linear-gradient(90deg,var(--t-100),var(--mint))" }} />
              <span className="head" style={{ left: `${Math.min(usagePercent, 100)}%` }} />
            </div>
            <div className="mono-cap mt-3 flex justify-between">
              <span>{org?.plan === "free" ? `пробные лиды · ${usagePercent}%` : `текущий период · ${usagePercent}%`}</span>
              {org?.plan === "free" ? (
                <Link href="/plans" className="t-72 underline underline-offset-4 hover:text-[var(--t-100)]">
                  выбрать тариф →
                </Link>
              ) : (
                <span className="t-72">обновится 1-го числа</span>
              )}
            </div>
          </div>
        </div>
      </motion.div>

      {/* ── Org-level stat tiles ── */}
      {projects.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.08 }}
          className="grid grid-cols-2 sm:grid-cols-4 gap-3"
        >
          <div className="stat-tile elev-1">
            <div className="stat-tile__label">Проектов</div>
            <div className="stat-tile__value tnum">{projects.length}</div>
            <div className="stat-tile__sub">из {org?.projects_limit ?? "?"}</div>
          </div>
          <div className="stat-tile elev-1">
            <div className="stat-tile__label">Лидов собрано</div>
            <div className="stat-tile__value tnum">{totalLeads.toLocaleString("ru-RU")}</div>
            <div className="stat-tile__sub">по всем проектам</div>
          </div>
          <div className="stat-tile elev-1">
            <div className="stat-tile__label">Обогащено</div>
            <div className="stat-tile__value tnum">{totalEnriched.toLocaleString("ru-RU")}</div>
            <div className="stat-tile__sub">обработано обогащением</div>
          </div>
          <div className="stat-tile elev-1">
            <div className="stat-tile__label">Активных сборов</div>
            <div className="stat-tile__value tnum">{activeJobs}</div>
            <div className="stat-tile__sub">прямо сейчас</div>
          </div>
        </motion.div>
      )}

      {/* Quota warning */}
      {usagePercent >= 80 && (
        <div className="rounded-2xl p-4 flex flex-wrap items-center justify-between gap-3 panel-flat"
             style={usagePercent >= 100 ? { borderColor: "rgba(244,63,94,0.18)", background: "rgba(40,28,28,0.65)" } : { borderColor: "rgba(251,191,36,0.18)", background: "rgba(40,32,18,0.55)" }}>
          <p className="text-sm t-84">
            {usagePercent >= 100
              ? "Квота лидов исчерпана. Обновите тариф для продолжения сбора."
              : `Использовано ${usagePercent}% квоты лидов. Рекомендуем обновить тариф.`}
          </p>
          <Link href="/plans" className="ghost rounded-full px-4 py-1.5 text-[12.5px] shrink-0">Обновить тариф</Link>
        </div>
      )}

      {/* ── Projects header ── */}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4 pt-4">
        <div>
          <div className="eyebrow mb-2">проекты</div>
          <div className="flex items-end gap-4 flex-wrap">
            <h1 className="h1" style={{ fontSize: "clamp(30px, 6vw, 44px)" }}>Ваши проекты</h1>
          </div>
        </div>
        {canManage && (
          <CreateProjectButton limitReached={projectLimitReached} onClick={() => setShowForm(true)} className="btn btn-brand">
            <Plus className="h-3.5 w-3.5" />
            Новый проект
          </CreateProjectButton>
        )}
      </div>

      {/* ── New project dialog ── */}
      <Dialog open={showForm} onOpenChange={(open) => { setShowForm(open); if (!open) { setFormStep("prompt"); setEnhanced(null); } }}>
        <DialogContent className="sm:max-w-lg">
          <AnimatePresence mode="wait">
            {formStep === "prompt" ? (
              <motion.div key="prompt-step" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.2 }}>
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <Sparkles className="h-5 w-5" style={{ color: "var(--mint)" }} />
                    Найти клиентов
                  </DialogTitle>
                  <DialogDescription>
                    Опишите ваш бизнес — что вы продаёте или какие услуги оказываете. AI проанализирует и найдёт потенциальных клиентов.
                  </DialogDescription>
                </DialogHeader>
                <div className="mt-4 grid gap-4">
                  <div className="relative">
                    <Textarea
                      placeholder={"Например:\n• Продаю кормовые добавки для животных в Томске\n• Разрабатываю сайты и мобильные приложения в Москве\n• Поставляю стройматериалы оптом по всей России"}
                      value={projectForm.prompt}
                      onChange={(e) => setProjectForm((p) => ({ ...p, prompt: e.target.value }))}
                      rows={5}
                      className="resize-none text-base pr-14"
                      maxLength={2000}
                    />
                    <div className="absolute right-2 bottom-2">
                      <VoiceInput
                        value={projectForm.prompt}
                        onChange={(next) => setProjectForm((p) => ({ ...p, prompt: next.slice(0, 2000) }))}
                      />
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    AI улучшит ваш запрос и определит, кого именно искать как потенциальных покупателей. Можно надиктовать голосом.
                  </p>
                  <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setShowForm(false)}>
                      Отмена
                    </Button>
                    <Button onClick={enhancePrompt} disabled={enhancing || !projectForm.prompt.trim()}>
                      {enhancing ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Анализирую...
                        </>
                      ) : (
                        <>
                          <Wand2 className="mr-2 h-4 w-4" />
                          Анализировать
                        </>
                      )}
                    </Button>
                  </DialogFooter>
                </div>
              </motion.div>
            ) : (
              <motion.div key="review-step" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }} transition={{ duration: 0.2 }}>
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <Search className="h-5 w-5" style={{ color: "var(--mint)" }} />
                    Стратегия поиска
                  </DialogTitle>
                  <DialogDescription>
                    AI определил целевых клиентов. Проверьте и скорректируйте при необходимости.
                  </DialogDescription>
                </DialogHeader>

                {enhanced?.explanation && (
                  <div className="mt-3 rounded-lg border border-[var(--line-2)] p-3" style={{ background: "var(--surface-1)" }}>
                    <p className="text-sm t-84">
                      <Sparkles className="mr-1.5 inline h-3.5 w-3.5" style={{ color: "var(--mint)" }} />
                      {enhanced.explanation}
                    </p>
                  </div>
                )}

                {enhanced?.target_customer_types && enhanced.target_customer_types.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {enhanced.target_customer_types.map((type) => (
                      <Badge key={type} variant="secondary" className="text-xs">
                        {type}
                      </Badge>
                    ))}
                  </div>
                )}

                {enhanced && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs t-56">Сайт у клиента:</span>
                    <Select
                      value={enhanced.website_preference ?? "any"}
                      onValueChange={(val) =>
                        setEnhanced((prev) => (prev ? { ...prev, website_preference: val ?? "any" } : prev))
                      }
                    >
                      <SelectTrigger size="sm" className="w-auto gap-1 rounded-full px-3 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="any">любые компании</SelectItem>
                        <SelectItem value="no_website">только без сайта</SelectItem>
                        <SelectItem value="with_website">только с сайтом</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {enhanced?.excluded_segments && enhanced.excluded_segments.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs t-56">Исключаем:</span>
                    {enhanced.excluded_segments.map((type) => (
                      <Badge key={type} variant="outline" className="gap-1 pr-1 text-xs opacity-70">
                        <span className="line-through">{type}</span>
                        <button
                          type="button"
                          aria-label={`Не исключать «${type}»`}
                          className="rounded-full p-0.5 transition-opacity opacity-70 hover:opacity-100"
                          onClick={() =>
                            setEnhanced((prev) =>
                              prev
                                ? { ...prev, excluded_segments: (prev.excluded_segments ?? []).filter((s) => s !== type) }
                                : prev
                            )
                          }
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}

                <form onSubmit={createProject} className="mt-4 grid gap-3">
                  <div className="grid gap-1.5">
                    <Label htmlFor="proj-name" className="text-xs text-muted-foreground">Название проекта</Label>
                    <Input
                      id="proj-name"
                      required
                      value={projectForm.name}
                      maxLength={140}
                      minLength={2}
                      onChange={(e) => setProjectForm((p) => ({ ...p, name: e.target.value }))}
                    />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="grid gap-1.5">
                      <Label htmlFor="proj-niche" className="text-xs text-muted-foreground">Кого ищем (ниша клиентов)</Label>
                      <Input
                        id="proj-niche"
                        required
                        value={projectForm.niche}
                        maxLength={120}
                        minLength={2}
                        onChange={(e) => setProjectForm((p) => ({ ...p, niche: e.target.value }))}
                      />
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor="proj-geo" className="text-xs text-muted-foreground">Регион / город</Label>
                      <Input
                        id="proj-geo"
                        required
                        value={projectForm.geography}
                        maxLength={120}
                        minLength={2}
                        onChange={(e) => setProjectForm((p) => ({ ...p, geography: e.target.value }))}
                      />
                    </div>
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="proj-segments" className="text-xs text-muted-foreground">Целевые сегменты</Label>
                    <Textarea
                      id="proj-segments"
                      value={projectForm.segments}
                      maxLength={300}
                      rows={3}
                      placeholder="Через запятую: производитель срубов, домостроитель из бруса, мебельная фабрика…"
                      onChange={(e) => setProjectForm((p) => ({ ...p, segments: e.target.value }))}
                      className="min-h-[72px] rounded-2xl px-4 py-3 leading-relaxed"
                    />
                  </div>
                  <DialogFooter className="mt-2">
                    <Button type="button" variant="outline" onClick={() => setFormStep("prompt")}>
                      Назад
                    </Button>
                    <Button type="submit" disabled={creating}>
                      {creating ? "Создаём..." : "Создать проект"}
                    </Button>
                  </DialogFooter>
                </form>
              </motion.div>
            )}
          </AnimatePresence>
        </DialogContent>
      </Dialog>

      {/* ── Delete project alert dialog ── */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogMedia className="bg-destructive/10">
              <Trash2 className="h-5 w-5 text-destructive" />
            </AlertDialogMedia>
            <AlertDialogTitle>Удалить проект?</AlertDialogTitle>
            <AlertDialogDescription>
              Проект &laquo;{deleteTarget?.name}&raquo; и все связанные данные будут удалены безвозвратно.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleting}
              onClick={deleteProject}
            >
              {deleting ? "Удаляем..." : "Удалить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── Edit project dialog ── */}
      <Dialog open={!!editTarget} onOpenChange={(open) => { if (!open) setEditTarget(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Редактировать проект</DialogTitle>
            <DialogDescription>
              Измените параметры проекта.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={updateProject} className="grid gap-4 px-1 sm:px-0">
            <div className="grid gap-2">
              <Label htmlFor="edit-proj-name">Название проекта</Label>
              <Input
                id="edit-proj-name"
                required
                value={editForm.name}
                maxLength={140}
                minLength={2}
                onChange={(e) => setEditForm((p) => ({ ...p, name: e.target.value }))}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="edit-proj-niche">Ниша</Label>
              <Input
                id="edit-proj-niche"
                required
                value={editForm.niche}
                maxLength={120}
                minLength={2}
                onChange={(e) => setEditForm((p) => ({ ...p, niche: e.target.value }))}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="edit-proj-geo">Регион / город</Label>
              <Input
                id="edit-proj-geo"
                required
                value={editForm.geography}
                maxLength={120}
                minLength={2}
                onChange={(e) => setEditForm((p) => ({ ...p, geography: e.target.value }))}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="edit-proj-segments">Сегменты</Label>
              <Textarea
                id="edit-proj-segments"
                value={editForm.segments}
                maxLength={300}
                rows={3}
                placeholder="Через запятую: производитель срубов, домостроитель из бруса, мебельная фабрика…"
                onChange={(e) => setEditForm((p) => ({ ...p, segments: e.target.value }))}
                className="min-h-[72px] rounded-2xl px-4 py-3 leading-relaxed"
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEditTarget(null)}>
                Отмена
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? "Сохраняем..." : "Сохранить"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Empty state / Onboarding ── */}
      {projects.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
          className="space-y-4"
        >
        {/* Onboarding card */}
        <div className="empty-state panel-glass elev-2">
          <div className="empty-state__icon">
            <Sparkles style={{ color: "var(--mint)", width: 28, height: 28 }} />
          </div>
          <div className="eyebrow mb-3">добро пожаловать</div>
          <h3 className="empty-state__title">Найдите клиентов за 3 шага.</h3>
          <p className="empty-state__body">
            Опишите ваш бизнес одной фразой — мы соберём базу компаний с проверенными контактами.
          </p>
          <div className="grid gap-2.5 max-w-md w-full mx-auto mb-7 text-left mt-2">
            {[
              ["01", "Опишите бизнес — что продаёте или какие услуги оказываете"],
              ["02", "AI определит целевых клиентов и найдёт их в ЕГРЮЛ, 2ГИС, Яндекс.Картах"],
              ["03", "Получите контакты с email/MX-проверкой и экспортируйте в CRM"],
            ].map(([n, t]) => (
              <div key={n} className="panel-flat px-4 py-3 flex items-center gap-3 text-[13px] t-72 rounded-xl">
                <span className="mono t-40 text-[11px] shrink-0">{n}</span>
                <span>{t}</span>
              </div>
            ))}
          </div>
          {canManage && (
            <CreateProjectButton
              limitReached={projectLimitReached}
              onClick={() => setShowForm(true)}
              className="brand rounded-full px-5 py-2.5 text-[13.5px] inline-flex items-center gap-2"
            >
              <Plus className="h-3.5 w-3.5" />
              Создать первый проект
            </CreateProjectButton>
          )}
        </div>

        {/* Sample-results preview — static demo data, zero API cost. Shows a new
            user exactly what a collected project looks like before they pay. */}
        <div className="panel-glass elev-1 p-6">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div className="eyebrow">пример результата</div>
            <span className="badge badge--source">демо-данные</span>
          </div>
          <p className="t-56 text-[13px] mb-3">
            Так выглядит собранная база. Создайте проект — и БАЗА найдёт реальные компании по вашей нише.
          </p>
          <div className="mono-cap t-40 text-[10px] mb-3 flex items-center gap-3 flex-wrap">
            <span>в колонках «Тел.?» и «Email?»:</span>
            <span><span style={{ color: "var(--mint)" }}>✓</span> — есть</span>
            <span className="sep-dot" />
            <span><span style={{ color: "var(--t-40)" }}>—</span> — нет</span>
          </div>
          <div className="overflow-x-auto -mx-1 px-1">
            <table className="w-full text-left" style={{ borderCollapse: "collapse", minWidth: 560 }}>
              <thead>
                <tr className="mono-cap text-[10px] t-40">
                  <th className="pb-2 pr-3 font-normal">Компания</th>
                  <th className="pb-2 pr-3 font-normal">Город</th>
                  <th className="pb-2 pr-3 font-normal">Тел.?</th>
                  <th className="pb-2 pr-3 font-normal">Email?</th>
                  <th className="pb-2 font-normal text-right">Score</th>
                </tr>
              </thead>
              <tbody className="text-[12.5px]">
                {(demoSamples ?? DEMO_SAMPLE_FALLBACK).slice(0, 6).map((row, i) => (
                  <tr key={`${row.company}-${i}`} className="border-t border-[var(--line)]">
                    <td className="py-2.5 pr-3 text-[var(--t-84)]">{row.company}</td>
                    <td className="py-2.5 pr-3 t-56">{row.city}</td>
                    <td className="py-2.5 pr-3 mono text-[11.5px]" style={{ color: row.has_phone ? "var(--mint)" : "var(--t-40)" }}>
                      {row.has_phone ? "✓" : "—"}
                    </td>
                    <td className="py-2.5 pr-3" style={{ color: row.has_email ? "var(--mint)" : "var(--t-40)" }}>
                      {row.has_email ? "✓" : "—"}
                    </td>
                    <td className="py-2.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="score-bar score-bar--sm" style={{ "--score": `${row.score / 100}` } as React.CSSProperties}>
                          <div className="score-bar__fill" />
                        </div>
                        <span className="mono tnum text-[11.5px]" style={{ color: row.score >= 70 ? "var(--mint)" : "var(--t-72)" }}>
                          {row.score}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mono-cap mt-4 t-40 text-[10px]">
            реальные данные из демо-проекта БАЗА · сами контакты скрыты (✓ — есть · — нет)
          </p>
        </div>
        </motion.div>
      )}

      {/* ── Project cards (v4 lead-card layout) ── */}
      <div className="flex flex-col gap-3">
        {projects.map((project, idx) => {
          const latestJob = latestJobs[project.id];
          const segmentText = project.segments.length > 0 ? project.segments.join(", ") : null;
          const okvedText = (project.okved_codes ?? [])
            .slice(0, 3)
            .map((c) => c.code)
            .join(", ");

          const status = latestJob?.status;
          const dotClass =
            status === "done" ? "dot-em dot-pulse" :
            status === "running" ? "dot-am dot-pulse" :
            status === "failed" ? "dot-rs" :
            "dot-mt";

          // Map job status to v4 badge modifier
          const badgeClass =
            status === "done" ? "badge badge--qualified" :
            status === "running" ? "badge badge--new" :
            status === "failed" ? "badge badge--rejected" :
            "badge badge--source";

          const statusLabel =
            status ? (JOB_STATUS_MAP[status] ?? status) :
            "новый";

          const sourceList = ["2ГИС", "Яндекс.Карты", "Яндекс.Поиск", "наша база"];

          // Score-bar value: enriched / added ratio, capped 0–1
          const addedCount = latestJob?.added_count ?? 0;
          const enrichedCount = latestJob?.enriched_count ?? 0;
          const enrichScore = addedCount > 0 ? Math.min(1, enrichedCount / addedCount) : 0;

          return (
            <motion.div
              key={project.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, delay: 0.05 + idx * 0.04 }}
              className="lead-card group relative"
            >
              {/* Navigation overlay — sibling of the action buttons so we never
                  nest a <button> inside an <a> (invalid HTML). */}
              <Link
                href={`/dashboard/projects/${project.id}`}
                className="absolute inset-0 z-0"
                aria-label={`Открыть проект «${project.name}»`}
                style={{ textDecoration: "none" }}
              />

              <div className="lead-card__row relative z-10 pointer-events-none">
                {/* Status dot */}
                <span className={`dot ${dotClass} shrink-0`} />

                {/* Main content */}
                <div className="min-w-0 flex-1">
                  <div className="lead-card__row" style={{ gap: 8, marginBottom: 4 }}>
                    <span className="lead-card__name truncate min-w-0">{project.name}</span>
                    <span className={`${badgeClass} shrink-0`}>{statusLabel}</span>
                  </div>

                  <div className="lead-card__meta">
                    <span>{project.niche}</span>
                    <span className="mx-1.5 t-28">·</span>
                    <span>{project.geography}</span>
                    {okvedText && (
                      <>
                        <span className="mx-1.5 t-28">·</span>
                        <span className="t-48">ОКВЭД {okvedText}</span>
                      </>
                    )}
                    {!okvedText && segmentText && (
                      <>
                        <span className="mx-1.5 t-28">·</span>
                        <span className="t-48">{segmentText}</span>
                      </>
                    )}
                  </div>

                  <div className="lead-card__sub">
                    {latestJob ? (
                      <span className="flex items-center gap-3 flex-wrap">
                        <span>
                          <span className="tnum text-[var(--t-84)]">{addedCount.toLocaleString("ru-RU")}</span>
                          <span className="ml-1 t-40">добавлено</span>
                        </span>
                        <span className="t-28">·</span>
                        <span>
                          <span className="tnum text-[var(--t-84)]">{enrichedCount.toLocaleString("ru-RU")}</span>
                          <span className="ml-1 t-40">обогащено</span>
                        </span>
                        {addedCount > 0 && (
                          <span className="flex items-center gap-1.5 shrink-0">
                            <div className="score-bar score-bar--sm" style={{ "--score": enrichScore } as React.CSSProperties}>
                              <div className="score-bar__fill" />
                            </div>
                          </span>
                        )}
                        <span className="t-28">·</span>
                        <span className="t-40 flex flex-wrap items-center gap-1">
                          {sourceList.map((s) => (
                            <span key={s} className="badge badge--source" style={{ padding: "1px 6px", fontSize: 10 }}>{s}</span>
                          ))}
                        </span>
                      </span>
                    ) : (
                      <span className="italic t-40">
                        ещё не запускали сбор · источники: {sourceList.join(", ")}
                      </span>
                    )}
                  </div>
                </div>

                {/* Action buttons — siblings of the Link overlay (z-0); the
                    edit/delete group re-enables pointer events and sits at z-10,
                    so it (including the gap BETWEEN the buttons) catches taps —
                    a near-miss on mobile no longer falls through to the project
                    link. The chevron stays pass-through: tapping it opens the
                    project, as its affordance implies. */}
                <div className="flex items-center gap-2 sm:gap-1.5 shrink-0">
                  {canManage && (
                    <div className="pointer-events-auto relative z-10 flex items-center gap-2 sm:gap-1.5">
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => openEditDialog(project)}
                        aria-label="Редактировать"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        className="btn-icon hover:!text-[var(--rose)]"
                        onClick={() => setDeleteTarget(project)}
                        aria-label="Удалить"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                  <span className="btn-icon">
                    <ChevronRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </div>
              </div>
            </motion.div>
          );
        })}

        {/* ── "+ Создать ещё проект" dashed placeholder ── */}
        {canManage && projects.length > 0 && (
          <CreateProjectButton
            limitReached={projectLimitReached}
            onClick={() => setShowForm(true)}
            className="px-5 py-4 flex items-center gap-3 t-56 hover:t-72 transition-colors animate-fade-in"
            style={{ border: "1px dashed var(--line-2)", borderRadius: 14 }}
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="text-[13px]">Создать ещё проект</span>
            <span className="mono-cap t-40 ml-auto">
              остаток квоты: {projectsN(projectsRemaining)}
            </span>
          </CreateProjectButton>
        )}
      </div>
    </motion.main>
  );
}

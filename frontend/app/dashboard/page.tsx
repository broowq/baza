"use client";

import { FormEvent, useEffect, useState } from "react";
import { Plus, ChevronRight, Trash2, Pencil, Sparkles, Search, Wand2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Loader } from "@/components/ui/loader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
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
import { Separator } from "@/components/ui/separator";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { getOrgId, setOrgId } from "@/lib/auth";
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

const JOB_STATUS_MAP: Record<
  string,
  { label: string; className: string }
> = {
  queued: { label: "В очереди", className: "bg-muted text-muted-foreground" },
  running: { label: "В работе", className: "bg-blue-500/15 text-blue-700 dark:text-blue-400" },
  done: { label: "Готово", className: "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20" },
  failed: { label: "Ошибка", className: "bg-destructive/10 text-destructive" },
};

export default function DashboardPage() {
  const authed = useAuthGuard();
  const [loading, setLoading] = useState(true);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [org, setOrg] = useState<Organization | null>(null);
  const [orgRole, setOrgRole] = useState<"owner" | "admin" | "member">("member");
  const [projects, setProjects] = useState<Project[]>([]);
  const [latestJobs, setLatestJobs] = useState<Record<string, CollectionJob | null>>({});
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

  const bootstrap = async () => {
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
            const jobEntries = await Promise.all(
              prs.map(async (p) => {
                const jobs = await api<CollectionJob[]>(`/leads/jobs/project/${p.id}`).catch(() => []);
                return [p.id, jobs[0] ?? null] as const;
              })
            );
            setLatestJobs(Object.fromEntries(jobEntries));
          }
        }
      }
    } catch {
      // Silently handle
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (authed) void bootstrap(); }, [authed]);

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

  const canManage = orgRole === "owner" || orgRole === "admin";
  const usagePercent = org ? Math.min(100, Math.round(((org.leads_used_current_month ?? 0) / (org.leads_limit_per_month || 1)) * 100)) : 0;

  const planLabel: Record<string, string> = {
    starter: "Starter",
    pro: "Pro",
    team: "Team",
  };

  const roleLabel: Record<string, string> = {
    owner: "Владелец",
    admin: "Админ",
    member: "Участник",
  };

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-[1180px] space-y-8 px-4 py-8 sm:px-6 lg:px-10 lg:py-10"
    >
      {/* ── Workspace card (v3) ── */}
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="panel" style={{ padding: 32 }}>
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10">
          {/* Left: org + chips */}
          <div className="lg:col-span-7">
            <div className="eyebrow mb-3">workspace</div>
            <div className="flex items-center gap-3 flex-wrap">
              {organizations.length > 1 ? (
                <select
                  className="rounded-full border border-[var(--line-2)] bg-white/[0.04] px-4 py-1.5 text-[26px] font-light tracking-tight text-white outline-none focus:border-white/[0.24]"
                  value={org?.id ?? ""}
                  disabled={switchingOrg}
                  onChange={async (e) => {
                    const val = e.target.value;
                    if (!val) return;
                    const selected = organizations.find((item) => item.id === val);
                    if (!selected || switchingOrg) return;
                    setSwitchingOrg(true);
                    setOrgId(selected.id);
                    setOrg(selected);
                    try {
                      const membership = await api<{ role: "owner" | "admin" | "member" }>("/organizations/membership").catch(() => null);
                      if (membership) setOrgRole(membership.role); else setOrgRole("member");
                      await refreshProjects();
                    } finally {
                      setSwitchingOrg(false);
                    }
                  }}
                >
                  {organizations.map((item) => (
                    <option key={item.id} value={item.id} className="bg-[var(--bg-2)]">{item.name}</option>
                  ))}
                </select>
              ) : (
                <h2 className="h2">{org?.name ?? "Организация"}</h2>
              )}
              {org?.plan && (
                <span className="chip chip-mint" style={{ padding: "4px 10px" }}>
                  <span className="dot dot-mt" style={{ width: 5, height: 5 }} />
                  {planLabel[org.plan] ?? org.plan}
                </span>
              )}
              <span className="chip">{roleLabel[orgRole] ?? orgRole}</span>
            </div>
            <div className="mono-cap mt-3 flex items-center flex-wrap" style={{ gap: "0 4px" }}>
              <span>{projects.length} {projects.length === 1 ? "проект" : "проектов"}</span>
              <span className="sep-dot mx-2" />
              <span>{org?.users_limit ? `${org.users_limit} мест` : "—"}</span>
              <span className="sep-dot mx-2" />
              <span>ru-RU · UTC+7</span>
            </div>
          </div>

          {/* Right: quota with v-hairline */}
          <div className="lg:col-span-5 lg:v-hairline lg:pl-10">
            <div className="eyebrow mb-3">квота · лиды</div>
            <div className="h2 tnum mono">
              {(org?.leads_used_current_month ?? 0).toLocaleString("ru-RU")}{" "}
              <span className="t-40" style={{ fontWeight: 200 }}>/ {(org?.leads_limit_per_month ?? 0).toLocaleString("ru-RU")}</span>
            </div>
            <div className="prog mt-5">
              <i style={{ width: `${usagePercent}%`, background: usagePercent >= 90 ? "var(--rose)" : usagePercent >= 70 ? "linear-gradient(90deg,#fff,var(--amber))" : "linear-gradient(90deg,#fff,var(--mint))" }} />
              <span className="head" style={{ left: `${Math.min(usagePercent, 100)}%` }} />
            </div>
            <div className="mono-cap mt-3 flex justify-between">
              <span>текущий период · {usagePercent}%</span>
              <span className="t-72">обновится 1-го числа</span>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Quota warning */}
      {usagePercent >= 80 && (
        <div className={`rounded-2xl p-4 flex items-center justify-between ${usagePercent >= 100 ? "panel-flat" : "panel-flat"}`}
             style={usagePercent >= 100 ? { borderColor: "rgba(244,63,94,0.18)", background: "rgba(40,28,28,0.65)" } : { borderColor: "rgba(251,191,36,0.18)", background: "rgba(40,32,18,0.55)" }}>
          <p className="text-sm t-84">
            {usagePercent >= 100
              ? "Квота лидов исчерпана. Обновите тариф для продолжения сбора."
              : `Использовано ${usagePercent}% квоты лидов. Рекомендуем обновить тариф.`}
          </p>
          <Link href="/plans" className="ghost rounded-full px-4 py-1.5 text-[12.5px]">Обновить тариф</Link>
        </div>
      )}

      {/* ── Projects header ── */}
      <div className="flex items-end justify-between pt-4">
        <div>
          <div className="eyebrow mb-2">проекты</div>
          <div className="flex items-end gap-4 flex-wrap">
            <h1 className="h1" style={{ fontSize: 44 }}>Ваши воронки</h1>
            <span className="mono-cap mb-2 tnum">
              {projects.length} из {org?.projects_limit ?? "?"}
            </span>
          </div>
        </div>
        {canManage && (
          <button onClick={() => setShowForm(true)} className="btn btn-brand">
            <Plus className="h-3.5 w-3.5" />
            Новый проект
          </button>
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
                    <Sparkles className="h-5 w-5 text-violet-500" />
                    Найти клиентов
                  </DialogTitle>
                  <DialogDescription>
                    Опишите ваш бизнес — что вы продаёте или какие услуги оказываете. AI проанализирует и найдёт потенциальных клиентов.
                  </DialogDescription>
                </DialogHeader>
                <div className="mt-4 grid gap-4">
                  <Textarea
                    placeholder={"Например:\n• Продаю кормовые добавки для животных в Томске\n• Разрабатываю сайты и мобильные приложения в Москве\n• Поставляю стройматериалы оптом по всей России"}
                    value={projectForm.prompt}
                    onChange={(e) => setProjectForm((p) => ({ ...p, prompt: e.target.value }))}
                    rows={5}
                    className="resize-none text-base"
                    maxLength={2000}
                  />
                  <p className="text-xs text-muted-foreground">
                    AI улучшит ваш запрос и определит, кого именно искать как потенциальных покупателей
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
                    <Search className="h-5 w-5 text-emerald-500" />
                    Стратегия поиска
                  </DialogTitle>
                  <DialogDescription>
                    AI определил целевых клиентов. Проверьте и скорректируйте при необходимости.
                  </DialogDescription>
                </DialogHeader>

                {enhanced?.explanation && (
                  <div className="mt-3 rounded-lg border border-violet-500/20 bg-violet-500/5 p-3">
                    <p className="text-sm text-violet-700 dark:text-violet-300">
                      <Sparkles className="mr-1.5 inline h-3.5 w-3.5" />
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
                  <div className="grid grid-cols-2 gap-3">
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
                    <Input
                      id="proj-segments"
                      value={projectForm.segments}
                      maxLength={300}
                      placeholder="Через запятую"
                      onChange={(e) => setProjectForm((p) => ({ ...p, segments: e.target.value }))}
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
              <Input
                id="edit-proj-segments"
                value={editForm.segments}
                maxLength={300}
                onChange={(e) => setEditForm((p) => ({ ...p, segments: e.target.value }))}
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
        <div className="panel p-10 text-center">
          <div className="mx-auto mb-6 inline-flex h-14 w-14 items-center justify-center rounded-full panel-flat">
            <Sparkles className="h-7 w-7" style={{ color: "var(--mint)" }} />
          </div>
          <div className="eyebrow mb-3">добро пожаловать</div>
          <h3 className="h2 mb-3" style={{ fontSize: 28 }}>Найдите клиентов за&nbsp;3&nbsp;шага.</h3>
          <p className="t-72 text-[14px] mb-8 max-w-md mx-auto leading-relaxed">
            Опишите ваш бизнес одной фразой — мы соберём базу компаний с проверенными контактами.
          </p>
          <div className="grid gap-2.5 max-w-md w-full mx-auto mb-7 text-left">
            {[
              ["01", "Опишите бизнес — что продаёте или какие услуги оказываете"],
              ["02", "AI определит целевых клиентов и найдёт их в ЕГРЮЛ, 2ГИС, Яндекс.Картах"],
              ["03", "Получите контакты с email/MX-проверкой и экспортируйте в CRM"],
            ].map(([n, t]) => (
              <div key={n} className="panel-flat px-4 py-3 flex items-center gap-3 text-[13px] t-72">
                <span className="mono t-40 text-[11px]">{n}</span>
                <span>{t}</span>
              </div>
            ))}
          </div>
          {canManage && (
            <button onClick={() => setShowForm(true)} className="brand rounded-full px-5 py-2.5 text-[13.5px] inline-flex items-center gap-2">
              <Plus className="h-3.5 w-3.5" />
              Создать первый проект
            </button>
          )}
        </div>
      )}

      {/* ── Project cards (v3 row layout) ── */}
      <div className="flex flex-col gap-3">
        {projects.map((project) => {
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
          const chipClass =
            status === "done" ? "chip-em" :
            status === "running" ? "chip-am" :
            status === "failed" ? "chip-rs" :
            "chip-mint";
          const statusLabel =
            status ? (JOB_STATUS_MAP[status]?.label ?? status) :
            "новый";

          const sourceList = ["2ГИС", "Yandex", "SearXNG"];

          return (
            <div
              key={project.id}
              className="panel-flat group relative transition-colors duration-200 hover:bg-white/[0.045]"
            >
              <Link
                href={`/dashboard/projects/${project.id}`}
                className="flex items-center gap-4 px-5 py-4"
              >
                <span className={`dot ${dotClass}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-[15px] truncate" style={{ fontWeight: 500 }}>
                      {project.name}
                    </span>
                    <span className={`chip ${chipClass}`}>{statusLabel}</span>
                  </div>
                  <div className="mono-cap mt-1.5 truncate">
                    {project.niche} · {project.geography}
                    {okvedText && (
                      <>
                        {" · "}
                        <span className="t-72">ОКВЭД {okvedText}</span>
                      </>
                    )}
                    {!okvedText && segmentText && (
                      <>
                        {" · "}
                        <span className="t-72">{segmentText}</span>
                      </>
                    )}
                  </div>
                  <div className="mono-cap t-48 mt-0.5 truncate">
                    {latestJob ? (
                      <>
                        <span className="t-72 tnum">{latestJob.added_count ?? 0}</span> добавлено
                        {" · "}
                        <span className="t-72 tnum">{latestJob.enriched_count ?? 0}</span> обогащено
                        {" · sources: "}
                        {sourceList.join(" · ")}
                      </>
                    ) : (
                      <span className="italic">ещё не запускали сбор · sources: {sourceList.join(" · ")}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {canManage && (
                    <>
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); openEditDialog(project); }}
                        aria-label="Редактировать"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        className="btn-icon hover:!text-[var(--rose)]"
                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setDeleteTarget(project); }}
                        aria-label="Удалить"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </>
                  )}
                  <span className="btn-icon">
                    <ChevronRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </div>
              </Link>
            </div>
          );
        })}

        {/* ── "+ Создать ещё проект" dashed placeholder (matches v3) ── */}
        {canManage && projects.length > 0 && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="px-5 py-4 flex items-center gap-3 t-56 hover:t-72 transition-colors"
            style={{ border: "1px dashed var(--line-2)", borderRadius: 14 }}
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="text-[13px]">Создать ещё проект</span>
            <span className="mono-cap t-40 ml-auto">
              остаток квоты: {Math.max(0, (org?.projects_limit ?? 0) - projects.length)} проектов
            </span>
          </button>
        )}
      </div>
    </motion.main>
  );
}

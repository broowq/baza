"use client";

import { FormEvent, useEffect, useState } from "react";
import { FolderOpen, Plus, ChevronRight, Building2, Gauge, Trash2, Pencil, Users, Sparkles, MapPin, Search, Wand2, ArrowRight, Loader2 } from "lucide-react";
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
      const [orgs] = await Promise.all([
        api<Organization[]>("/organizations/my-list").catch(() => null),
        api<{ email: string; is_admin: boolean; full_name?: string }>("/auth/me").catch(() => null),
      ]);

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
      className="mx-auto max-w-4xl space-y-8 px-4 py-8 sm:px-6 lg:pl-10"
    >
      {/* ── Org header card ── */}
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      <Card className="relative overflow-hidden bg-gradient-to-br from-white/[0.03] to-transparent border-white/[0.06] shadow-sm ring-1 ring-primary/[0.03]">
        <div className="pointer-events-none absolute inset-0 rounded-xl bg-gradient-to-br from-primary/[0.02] to-transparent" />
        <CardHeader className="relative">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center rounded-xl bg-primary/10 p-2.5 text-primary">
                <Building2 className="h-5 w-5" />
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  {organizations.length > 1 ? (
                    <select
                      className="w-full max-w-full rounded-md border border-border bg-card px-3 py-1.5 text-xl font-bold tracking-tight text-foreground sm:w-auto sm:text-2xl"
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
                        <option key={item.id} value={item.id}>{item.name}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">{org?.name ?? "Организация"}</span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {org?.plan && (
                    <Badge className="border-0 bg-primary/10 text-xs font-medium text-primary hover:bg-primary/15">
                      <Sparkles className="mr-1 h-3 w-3" />
                      {planLabel[org.plan] ?? org.plan}
                    </Badge>
                  )}
                  <Badge className="border-0 bg-accent text-xs font-medium text-accent-foreground">
                    {roleLabel[orgRole] ?? orgRole}
                  </Badge>
                </div>
              </div>
            </div>

            {/* Quota */}
            <div className="flex w-full items-center gap-3 rounded-xl bg-muted/30 px-4 py-2 sm:w-auto">
              <Gauge className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-initial">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-foreground">
                    {org?.leads_used_current_month ?? 0}
                    <span className="font-normal text-muted-foreground"> / {org?.leads_limit_per_month}</span>
                  </span>
                  <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold leading-none ${usagePercent >= 90 ? "bg-destructive/10 text-destructive" : usagePercent >= 70 ? "bg-amber-500/10 text-amber-600" : "bg-emerald-500/10 text-emerald-600"}`}>
                    {usagePercent}%
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted ring-1 ring-border/30 sm:w-32">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${usagePercent >= 90 ? "bg-gradient-to-r from-destructive to-destructive/80" : usagePercent >= 70 ? "bg-gradient-to-r from-amber-500 to-amber-400" : "bg-gradient-to-r from-emerald-500 to-emerald-400"}`}
                    style={{ width: `${usagePercent}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        </CardHeader>
      </Card>
      </motion.div>

      {/* ── Subtle section divider ── */}
      <Separator className="my-6" />

      {/* ── Projects header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-foreground sm:text-xl">
            <span className="inline-block h-2 w-2 rounded-full bg-violet-500 mr-2 align-middle" />
            Ваши проекты
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {projects.length} из {org?.projects_limit ?? "?"} проектов
          </p>
        </div>
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

      {/* ── Empty state ── */}
      {projects.length === 0 && (
        <Card className="border-dashed border-border/70">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-primary/5 ring-1 ring-primary/10">
              <FolderOpen className="h-8 w-8 text-primary/40" />
            </div>
            <CardTitle className="mb-1.5 text-lg text-foreground">Пока нет проектов</CardTitle>
            <CardDescription className="max-w-xs text-center text-sm text-muted-foreground">
              Создайте первый проект и начните собирать целевые лиды для вашего бизнеса.
            </CardDescription>
            {canManage && (
              <Button size="sm" className="mt-5" onClick={() => setShowForm(true)}>
                <Plus className="mr-1.5 h-4 w-4" />
                Создать проект
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Project cards ── */}
      <div className="grid gap-3">
        {projects.map((project, i) => {
          const latestJob = latestJobs[project.id];
          const jobInfo = latestJob ? JOB_STATUS_MAP[latestJob.status] : null;
          const segmentText = project.segments.length > 0 ? project.segments.join(", ") : null;

          return (
            <div key={project.id}>
              <Card className={`group relative overflow-hidden border-l-2 bg-gradient-to-br from-white/[0.03] to-transparent transition-all duration-300 hover:shadow-lg hover:-translate-y-0.5 ${latestJob?.status === "done" ? "border-l-emerald-500/60" : "border-l-primary/20"}`}>
                <Link
                  href={`/dashboard/projects/${project.id}`}
                  className="flex items-center justify-between px-4 py-4 sm:px-5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2.5">
                      <h3 className="truncate text-lg font-semibold text-foreground">{project.name}</h3>
                      {latestJob && jobInfo && (
                        <span className={`inline-flex h-5 items-center rounded-full px-2 text-[11px] font-semibold ${jobInfo.className}`}>
                          {latestJob.status === "running" && (
                            <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-blue-500" />
                          )}
                          {jobInfo.label}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                      <MapPin className="h-3 w-3 shrink-0" />
                      <span className="truncate">
                        {project.niche} · {project.geography}
                        {segmentText && (
                          <span className="ml-1 text-muted-foreground/60" title={segmentText}>
                            · <span className="inline-block max-w-[180px] truncate align-bottom">{segmentText}</span>
                          </span>
                        )}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-col gap-y-1 text-xs text-muted-foreground sm:flex-row sm:flex-wrap sm:gap-x-4">
                      {latestJob ? (
                        <>
                          <span className="inline-flex items-center gap-1">
                            <Users className="h-3 w-3" />
                            {latestJob.added_count ?? 0} добавлено
                          </span>
                          <span className="inline-flex items-center gap-1">
                            <Sparkles className="h-3 w-3" />
                            {latestJob.enriched_count ?? 0} обогащено
                          </span>
                          {(latestJob.found_count ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-1">
                              <Search className="h-3 w-3" />
                              {latestJob.found_count} найдено
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="italic">Ещё не запускали сбор</span>
                      )}
                    </div>
                  </div>
                  <div className="ml-3 flex shrink-0 items-center gap-2">
                    {canManage && (
                      <>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="min-h-[44px] min-w-[44px] text-muted-foreground opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 hover:text-primary"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            openEditDialog(project);
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="min-h-[44px] min-w-[44px] text-muted-foreground opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 hover:text-destructive"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setDeleteTarget(project);
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </>
                    )}
                    <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </div>
                </Link>
              </Card>
            </div>
          );
        })}

        {/* ── "+ Новый проект" placeholder card ── */}
        {canManage && projects.length > 0 && (
          <div
            transition={{ delay: projects.length * 0.04 }}
          >
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-muted-foreground/20 px-4 py-6 text-sm font-medium text-muted-foreground transition-all duration-200 hover:border-primary/40 hover:bg-primary/5 hover:text-foreground sm:px-5 sm:py-8"
            >
              <Plus className="h-5 w-5" />
              Новый проект
            </button>
          </div>
        )}
      </div>
    </motion.main>
  );
}

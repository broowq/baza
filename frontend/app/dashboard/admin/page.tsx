"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Users, Building2, FolderOpen, Database, Activity, Shield, Trash2, Clock } from "lucide-react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { api } from "@/lib/api";
import { useAuthGuard } from "@/lib/hooks";

type Stats = {
  totals: { users: number; organizations: number; projects: number; leads: number; jobs: number };
  recent: { users_today: number; users_week: number; users_month: number; jobs_today: number; jobs_week: number; leads_today: number; leads_week: number };
  revenue_monthly_rub: number;
  plan_distribution: Record<string, number>;
};

type UserRow = { id: string; email: string; full_name: string; is_admin: boolean; email_verified: boolean; created_at: string };
type OrgRow = {
  id: string; name: string; plan: string; members_count: number; projects_count: number;
  leads_count: number; projects_limit: number; users_limit: number;
  leads_limit_per_month: number; leads_used_current_month: number; created_at: string;
};
type JobRow = {
  id: string; project_name: string; org_name: string; status: string; kind: string;
  requested_limit: number; found_count: number; added_count: number; error: string | null; created_at: string;
};
type LogRow = { id: string; action: string; user_email: string; org_name: string; meta: Record<string, unknown>; created_at: string };

type TabValue = "overview" | "users" | "orgs" | "jobs" | "logs";

const STATUS_DOT: Record<string, string> = {
  queued: "dot-am",
  running: "dot-em",
  done: "dot-mt",
  failed: "",
};

function formatDate(iso: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function AdminPage() {
  const authed = useAuthGuard();
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [limits, setLimits] = useState<Record<string, { projects_limit: number; leads_limit_per_month: number }>>({});
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<UserRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [activeTab, setActiveTab] = useState<TabValue>("overview");

  const load = useCallback(async () => {
    try {
      const [s, u, o, j, l] = await Promise.all([
        api<Stats>("/admin/stats"),
        api<{ items: UserRow[] }>("/admin/users?limit=100"),
        api<{ items: OrgRow[] }>("/admin/organizations?limit=100"),
        api<{ items: JobRow[] }>("/admin/jobs?limit=50"),
        api<{ items: LogRow[] }>("/admin/logs?limit=50"),
      ]);
      setStats(s);
      setUsers(u.items);
      setOrgs(o.items);
      setJobs(j.items);
      setLogs(l.items);
      setLimits(Object.fromEntries(o.items.map((org) => [org.id, { projects_limit: org.projects_limit, leads_limit_per_month: org.leads_limit_per_month }])));
    } catch {
      toast.error("Требуются права администратора");
      router.replace("/dashboard");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  if (loading || !authed) return (
    <main className="relative mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <div className="canvas-bg" />
      <div className="grain" />
      <p className="relative z-10 t-48 text-[13px]">Загрузка...</p>
    </main>
  );

  const toggleAdmin = async (userId: string, current: boolean) => {
    try {
      await api(`/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify({ is_admin: !current }) });
      toast.success(!current ? "Назначен администратором" : "Снят с администратора");
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось изменить роль");
    }
  };

  const confirmDeleteUser = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api(`/admin/users/${deleteTarget.id}`, { method: "DELETE" });
      toast.success("Пользователь удалён");
      setDeleteTarget(null);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось удалить пользователя");
    } finally {
      setDeleting(false);
    }
  };

  const saveLimits = async (orgId: string) => {
    try {
      await api(`/admin/organizations/${orgId}/limits`, { method: "PATCH", body: JSON.stringify(limits[orgId]) });
      toast.success("Лимиты обновлены");
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось сохранить лимиты");
    }
  };

  const changePlan = async (orgId: string, plan: string | null) => {
    if (!plan) return;
    try {
      await api(`/admin/organizations/${orgId}/plan`, { method: "PATCH", body: JSON.stringify({ plan }) });
      toast.success(`Тариф изменён на ${plan}`);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось изменить тариф");
    }
  };

  const tabItems: { value: TabValue; label: string }[] = [
    { value: "overview", label: "Обзор" },
    { value: "users", label: "Пользователи" },
    { value: "orgs", label: "Организации" },
    { value: "jobs", label: "Задания" },
    { value: "logs", label: "Логи" },
  ];

  return (
    <main className="relative mx-auto max-w-6xl space-y-6 px-4 py-10 sm:px-6">
      <div className="canvas-bg" />
      <div className="grain" />

      <div className="relative z-10 space-y-8">
        {/* Header */}
        <div className="space-y-1">
          <div className="eyebrow">администрирование</div>
          <h1 className="h1 flex items-center gap-3" style={{ fontSize: 40, lineHeight: 1.05 }}>
            <Shield className="size-9 shrink-0" style={{ color: "var(--mint)" }} />
            Админ-панель
          </h1>
          <p className="caption">Управление платформой БАЗА</p>
        </div>

        {/* Tab nav */}
        <nav className="flex gap-1.5 overflow-x-auto border-b border-[var(--line)] pb-px">
          {tabItems.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setActiveTab(tab.value)}
              className={`nav-item shrink-0 ${activeTab === tab.value ? "active" : ""}`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* ── Overview ── */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { label: "Пользователи", value: stats?.totals.users ?? 0, sub: `+${stats?.recent.users_week ?? 0} за неделю`, icon: Users },
                { label: "Организации", value: stats?.totals.organizations ?? 0, sub: Object.entries(stats?.plan_distribution ?? {}).filter(([, v]) => v > 0).map(([k, v]) => `${k}: ${v}`).join(", "), icon: Building2 },
                { label: "Проекты", value: stats?.totals.projects ?? 0, sub: `${stats?.totals.jobs ?? 0} сборов всего`, icon: FolderOpen },
                { label: "Лиды", value: stats?.totals.leads ?? 0, sub: `+${stats?.recent.leads_week ?? 0} за неделю`, icon: Database },
              ].map((s) => (
                <div key={s.label} className="panel p-5">
                  <div className="flex items-center justify-between mb-3">
                    <div className="eyebrow">{s.label}</div>
                    <s.icon className="size-4 t-40" />
                  </div>
                  <div className="tnum text-[var(--t-100)]" style={{ fontSize: 28, fontWeight: 300 }}>
                    {s.value.toLocaleString("ru-RU")}
                  </div>
                  <p className="text-[11px] mono t-48 mt-1 truncate" title={s.sub}>{s.sub}</p>
                </div>
              ))}
            </div>

            <div className="panel p-5">
              <div className="eyebrow mb-3">выручка · активные подписки</div>
              <div className="tnum text-[var(--t-100)]" style={{ fontSize: 36, fontWeight: 300 }}>
                {(stats?.revenue_monthly_rub ?? 0).toLocaleString("ru-RU")} ₽
                <span className="text-[16px] t-48 ml-2">/мес</span>
              </div>
              <p className="text-[11px] mono t-48 mt-2">
                MRR по оплаченным активным подпискам. Демо и неоплаченные тарифы не учитываются.
              </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="panel p-5">
                <div className="eyebrow mb-4">последние регистрации</div>
                <div className="space-y-2.5">
                  {users.slice(0, 5).map((u) => (
                    <div key={u.id} className="flex items-center justify-between">
                      <span className="text-[13px] text-[var(--t-100)] truncate">{u.full_name || u.email}</span>
                      <span className="text-[11px] mono t-48 shrink-0 ml-4">{formatDate(u.created_at)}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel p-5">
                <div className="eyebrow mb-4">последние сборы</div>
                <div className="space-y-2.5">
                  {jobs.slice(0, 5).map((j) => (
                    <div key={j.id} className="flex items-center justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className={`dot ${STATUS_DOT[j.status] ?? ""}`} style={!STATUS_DOT[j.status] ? { background: "var(--rose)" } : undefined} />
                        <span className="text-[13px] text-[var(--t-100)] truncate">{j.project_name}</span>
                      </div>
                      <span className="text-[11px] mono t-48 shrink-0 ml-4">{j.found_count} найдено</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Users ── */}
        {activeTab === "users" && (
          <section className="panel p-6">
            <div className="eyebrow mb-1">пользователи</div>
            <p className="text-[12px] t-56 mb-5">Всего: {users.length}</p>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[var(--line)]">
                    <th className="eyebrow text-left py-2.5">Email</th>
                    <th className="eyebrow text-left py-2.5">Имя</th>
                    <th className="eyebrow text-left py-2.5">Роль</th>
                    <th className="eyebrow text-left py-2.5">Дата</th>
                    <th className="eyebrow text-right py-2.5">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-b border-[var(--line)] last:border-0">
                      <td className="py-3 text-[13px] text-[var(--t-100)]">
                        <span className="block max-w-[240px] truncate" title={u.email}>{u.email}</span>
                      </td>
                      <td className="py-3 text-[13px] t-84">
                        <span className="block max-w-[180px] truncate">{u.full_name || "—"}</span>
                      </td>
                      <td className="py-3">
                        <span className="inline-flex items-center gap-1.5 rounded-full panel-thin px-2.5 py-1 text-[11px] mono">
                          <span className={`dot ${u.is_admin ? "dot-mt" : "dot-am"}`} />
                          {u.is_admin ? "Админ" : "Пользователь"}
                        </span>
                      </td>
                      <td className="py-3 text-[11px] mono t-48">{formatDate(u.created_at)}</td>
                      <td className="text-right py-3">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => toggleAdmin(u.id, u.is_admin)}
                            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] mono t-72 hover:bg-[var(--surface-hover)] hover:t-100 transition-colors"
                          >
                            {u.is_admin ? "Снять админа" : "Сделать админом"}
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(u)}
                            className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] mono hover:bg-[var(--surface-hover)] transition-colors"
                            style={{ color: "var(--rose)" }}
                          >
                            <Trash2 className="size-3" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* ── Organizations ── */}
        {activeTab === "orgs" && (
          <section className="panel p-6">
            <div className="eyebrow mb-1">организации</div>
            <p className="text-[12px] t-56 mb-5">Всего: {orgs.length}</p>
            <div className="space-y-4">
              {orgs.map((org) => (
                <div key={org.id} className="panel-flat p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="min-w-0">
                      <p className="text-[14px] text-[var(--t-100)] font-medium truncate">{org.name}</p>
                      <p className="text-[11px] mono t-48 mt-0.5">
                        {org.members_count} участников · {org.projects_count} проектов · {org.leads_count} лидов
                      </p>
                    </div>
                    <Select value={org.plan ?? "free"} onValueChange={(v) => changePlan(org.id, v)}>
                      <SelectTrigger className="w-32 bg-[var(--surface-input)] border-[var(--line-2)]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="free">Free</SelectItem>
                        <SelectItem value="starter">Starter</SelectItem>
                        <SelectItem value="growth">Team</SelectItem>
                        <SelectItem value="pro">Pro</SelectItem>
                        <SelectItem value="team">Business</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <p className="text-[11px] mono t-48">
                    Лиды: {org.leads_used_current_month} / {org.leads_limit_per_month} · Создана: {formatDate(org.created_at)}
                  </p>
                  <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                    <input
                      className="input"
                      type="number"
                      min={1}
                      placeholder="Лимит проектов"
                      value={limits[org.id]?.projects_limit ?? org.projects_limit}
                      onChange={(e) => setLimits((p) => ({ ...p, [org.id]: { ...p[org.id], projects_limit: Math.max(1, +e.target.value) } }))}
                    />
                    <input
                      className="input"
                      type="number"
                      min={1}
                      placeholder="Лимит лидов/мес"
                      value={limits[org.id]?.leads_limit_per_month ?? org.leads_limit_per_month}
                      onChange={(e) => setLimits((p) => ({ ...p, [org.id]: { ...p[org.id], leads_limit_per_month: Math.max(1, +e.target.value) } }))}
                    />
                    <button
                      type="button"
                      onClick={() => saveLimits(org.id)}
                      className="btn btn-brand rounded-full px-4 py-2 text-[13px]"
                    >
                      Сохранить
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── Jobs ── */}
        {activeTab === "jobs" && (
          <section className="panel p-6">
            <div className="eyebrow mb-1">задания</div>
            <p className="text-[12px] t-56 mb-5">Всего: {jobs.length}</p>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[var(--line)]">
                    <th className="eyebrow text-left py-2.5">Проект</th>
                    <th className="eyebrow text-left py-2.5">Организация</th>
                    <th className="eyebrow text-left py-2.5">Статус</th>
                    <th className="eyebrow text-left py-2.5">Найдено</th>
                    <th className="eyebrow text-left py-2.5">Добавлено</th>
                    <th className="eyebrow text-right py-2.5">Дата</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j.id} className="border-b border-[var(--line)] last:border-0">
                      <td className="py-3 text-[13px] text-[var(--t-100)]">
                        <span className="block max-w-[180px] truncate" title={j.project_name}>{j.project_name}</span>
                      </td>
                      <td className="py-3 text-[13px] t-56">
                        <span className="block max-w-[160px] truncate" title={j.org_name}>{j.org_name}</span>
                      </td>
                      <td className="py-3">
                        <span className="inline-flex items-center gap-1.5 rounded-full panel-thin px-2.5 py-1 text-[11px] mono">
                          <span
                            className={`dot ${STATUS_DOT[j.status] ?? ""}`}
                            style={!STATUS_DOT[j.status] ? { background: "var(--rose)" } : undefined}
                          />
                          {j.status}
                        </span>
                      </td>
                      <td className="py-3 text-[13px] t-84">{j.found_count}</td>
                      <td className="py-3 text-[13px] t-84">{j.added_count}</td>
                      <td className="text-right py-3 text-[11px] mono t-48">{formatDate(j.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* ── Logs ── */}
        {activeTab === "logs" && (
          <section className="panel p-6">
            <div className="eyebrow mb-1 flex items-center gap-2">
              <Activity className="size-3" />
              логи активности
            </div>
            <p className="text-[12px] t-56 mb-5">Всего: {logs.length}</p>
            <div className="space-y-2">
              {logs.map((l) => (
                <div key={l.id} className="panel-flat p-3 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="inline-flex items-center rounded-md panel-thin px-2 py-0.5 text-[11px] mono">
                        {l.action}
                      </span>
                      <span className="text-[12px] t-56 truncate">{l.user_email}</span>
                      {l.org_name !== "—" && (
                        <span className="text-[12px] t-48">· {l.org_name}</span>
                      )}
                    </div>
                    {l.meta && Object.keys(l.meta).length > 0 && (
                      <div className="mt-1 text-[11px] mono t-40">
                        {JSON.stringify(l.meta).slice(0, 120)}
                      </div>
                    )}
                  </div>
                  <span className="shrink-0 text-[11px] mono t-48 flex items-center gap-1">
                    <Clock className="size-3" /> {formatDate(l.created_at)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      {/* Delete user confirmation dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить пользователя?</AlertDialogTitle>
            <AlertDialogDescription>
              Пользователь &laquo;{deleteTarget?.email}&raquo; будет удалён безвозвратно.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleting}
              onClick={() => void confirmDeleteUser()}
            >
              {deleting ? "Удаляем..." : "Удалить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}

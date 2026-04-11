"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Users, Building2, FolderOpen, Database, Activity, Shield, Trash2, Clock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";

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

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-muted text-muted-foreground",
  running: "bg-blue-500/15 text-blue-500",
  done: "bg-emerald-500/15 text-emerald-500",
  failed: "bg-destructive/15 text-destructive",
};

function formatDate(iso: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function AdminPage() {
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [limits, setLimits] = useState<Record<string, { projects_limit: number; leads_limit_per_month: number }>>({});
  const [loading, setLoading] = useState(true);

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

  if (loading) return <main className="mx-auto max-w-6xl px-6 py-12"><p className="text-muted-foreground">Загрузка...</p></main>;

  const toggleAdmin = async (userId: string, current: boolean) => {
    await api(`/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify({ is_admin: !current }) });
    toast.success(!current ? "Назначен администратором" : "Снят с администратора");
    await load();
  };

  const deleteUser = async (userId: string, email: string) => {
    if (!confirm(`Удалить пользователя ${email}?`)) return;
    await api(`/admin/users/${userId}`, { method: "DELETE" });
    toast.success("Пользователь удалён");
    await load();
  };

  const saveLimits = async (orgId: string) => {
    await api(`/admin/organizations/${orgId}/limits`, { method: "PATCH", body: JSON.stringify(limits[orgId]) });
    toast.success("Лимиты обновлены");
    await load();
  };

  const changePlan = async (orgId: string, plan: string | null) => {
    if (!plan) return;
    await api(`/admin/organizations/${orgId}/plan`, { method: "PATCH", body: JSON.stringify({ plan }) });
    toast.success(`Тариф изменён на ${plan}`);
    await load();
  };

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <Shield className="h-6 w-6" /> Админ-панель
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">Управление платформой БАЗА</p>
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="overview">Обзор</TabsTrigger>
          <TabsTrigger value="users">Пользователи</TabsTrigger>
          <TabsTrigger value="orgs">Организации</TabsTrigger>
          <TabsTrigger value="jobs">Задания</TabsTrigger>
          <TabsTrigger value="logs">Логи</TabsTrigger>
        </TabsList>

        {/* ── Overview ── */}
        <TabsContent value="overview" className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: "Пользователи", value: stats?.totals.users ?? 0, sub: `+${stats?.recent.users_week ?? 0} за неделю`, icon: Users },
              { label: "Организации", value: stats?.totals.organizations ?? 0, sub: `${Object.entries(stats?.plan_distribution ?? {}).filter(([, v]) => v > 0).map(([k, v]) => `${k}: ${v}`).join(", ")}`, icon: Building2 },
              { label: "Проекты", value: stats?.totals.projects ?? 0, sub: `${stats?.totals.jobs ?? 0} сборов всего`, icon: FolderOpen },
              { label: "Лиды", value: stats?.totals.leads ?? 0, sub: `+${stats?.recent.leads_week ?? 0} за неделю`, icon: Database },
            ].map((s) => (
              <Card key={s.label}>
                <CardHeader className="flex flex-row items-center justify-between pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">{s.label}</CardTitle>
                  <s.icon className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{s.value.toLocaleString("ru-RU")}</div>
                  <p className="text-xs text-muted-foreground mt-1">{s.sub}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader><CardTitle className="text-base">Выручка (оценка)</CardTitle></CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{(stats?.revenue_monthly_rub ?? 0).toLocaleString("ru-RU")} ₽<span className="text-base font-normal text-muted-foreground">/мес</span></div>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-base">Последние регистрации</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {users.slice(0, 5).map((u) => (
                    <div key={u.id} className="flex items-center justify-between text-sm">
                      <span className="font-medium">{u.full_name || u.email}</span>
                      <span className="text-muted-foreground text-xs">{formatDate(u.created_at)}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Последние сборы</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {jobs.slice(0, 5).map((j) => (
                    <div key={j.id} className="flex items-center justify-between text-sm">
                      <div>
                        <span className="font-medium">{j.project_name}</span>
                        <Badge variant="outline" className={`ml-2 text-[10px] ${STATUS_COLORS[j.status] ?? ""}`}>{j.status}</Badge>
                      </div>
                      <span className="text-muted-foreground text-xs">{j.found_count} найдено</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── Users ── */}
        <TabsContent value="users">
          <Card>
            <CardHeader><CardTitle>Пользователи ({users.length})</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-2 font-medium">Email</th>
                      <th className="pb-2 font-medium">Имя</th>
                      <th className="pb-2 font-medium">Роль</th>
                      <th className="pb-2 font-medium">Дата</th>
                      <th className="pb-2 font-medium">Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id} className="border-b last:border-0">
                        <td className="py-3">{u.email}</td>
                        <td className="py-3">{u.full_name || "—"}</td>
                        <td className="py-3">
                          {u.is_admin ? <Badge>Админ</Badge> : <Badge variant="outline">Пользователь</Badge>}
                        </td>
                        <td className="py-3 text-muted-foreground text-xs">{formatDate(u.created_at)}</td>
                        <td className="py-3">
                          <div className="flex gap-1">
                            <Button size="sm" variant="ghost" onClick={() => toggleAdmin(u.id, u.is_admin)}>
                              {u.is_admin ? "Снять админа" : "Сделать админом"}
                            </Button>
                            <Button size="sm" variant="ghost" className="text-destructive" onClick={() => deleteUser(u.id, u.email)}>
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Organizations ── */}
        <TabsContent value="orgs">
          <Card>
            <CardHeader><CardTitle>Организации ({orgs.length})</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-4">
                {orgs.map((org) => (
                  <div key={org.id} className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-semibold">{org.name}</span>
                        <span className="ml-2 text-sm text-muted-foreground">{org.members_count} участников · {org.projects_count} проектов · {org.leads_count} лидов</span>
                      </div>
                      <Select value={org.plan ?? "free"} onValueChange={(v) => changePlan(org.id, v)}>
                        <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="free">Free</SelectItem>
                          <SelectItem value="starter">Starter</SelectItem>
                          <SelectItem value="pro">Pro</SelectItem>
                          <SelectItem value="team">Business</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <span>Лиды: {org.leads_used_current_month} / {org.leads_limit_per_month}</span>
                      <span>·</span>
                      <span>Создана: {formatDate(org.created_at)}</span>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                      <Input
                        type="number" min={1} placeholder="Лимит проектов"
                        value={limits[org.id]?.projects_limit ?? org.projects_limit}
                        onChange={(e) => setLimits((p) => ({ ...p, [org.id]: { ...p[org.id], projects_limit: Math.max(1, +e.target.value) } }))}
                      />
                      <Input
                        type="number" min={1} placeholder="Лимит лидов/мес"
                        value={limits[org.id]?.leads_limit_per_month ?? org.leads_limit_per_month}
                        onChange={(e) => setLimits((p) => ({ ...p, [org.id]: { ...p[org.id], leads_limit_per_month: Math.max(1, +e.target.value) } }))}
                      />
                      <Button onClick={() => saveLimits(org.id)}>Сохранить</Button>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Jobs ── */}
        <TabsContent value="jobs">
          <Card>
            <CardHeader><CardTitle>Задания ({jobs.length})</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-2 font-medium">Проект</th>
                      <th className="pb-2 font-medium">Организация</th>
                      <th className="pb-2 font-medium">Статус</th>
                      <th className="pb-2 font-medium">Найдено</th>
                      <th className="pb-2 font-medium">Добавлено</th>
                      <th className="pb-2 font-medium">Дата</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((j) => (
                      <tr key={j.id} className="border-b last:border-0">
                        <td className="py-3 font-medium">{j.project_name}</td>
                        <td className="py-3 text-muted-foreground">{j.org_name}</td>
                        <td className="py-3">
                          <Badge variant="outline" className={STATUS_COLORS[j.status] ?? ""}>{j.status}</Badge>
                        </td>
                        <td className="py-3">{j.found_count}</td>
                        <td className="py-3">{j.added_count}</td>
                        <td className="py-3 text-muted-foreground text-xs">{formatDate(j.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Logs ── */}
        <TabsContent value="logs">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="h-4 w-4" /> Логи активности ({logs.length})</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {logs.map((l) => (
                  <div key={l.id} className="flex items-start justify-between rounded-lg border p-3 text-sm">
                    <div>
                      <Badge variant="outline" className="mr-2 text-xs">{l.action}</Badge>
                      <span className="text-muted-foreground">{l.user_email}</span>
                      {l.org_name !== "—" && <span className="text-muted-foreground"> · {l.org_name}</span>}
                      {l.meta && Object.keys(l.meta).length > 0 && (
                        <div className="mt-1 text-xs text-muted-foreground/70 font-mono">
                          {JSON.stringify(l.meta).slice(0, 120)}
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3" /> {formatDate(l.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </main>
  );
}

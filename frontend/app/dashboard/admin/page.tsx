"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type UserRow = { id: string; email: string; full_name: string; is_admin: boolean };
type OrgRow = {
  id: string;
  name: string;
  plan: string;
  projects_limit: number;
  leads_limit_per_month: number;
  leads_used_current_month: number;
};

export default function AdminPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [limits, setLimits] = useState<Record<string, { projects_limit: number; leads_limit_per_month: number }>>({});
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);

  const load = useCallback(async () => {
    try {
      const [userRows, orgRows] = await Promise.all([api<UserRow[]>("/admin/users"), api<OrgRow[]>("/admin/organizations")]);
      setUsers(userRows);
      setOrgs(orgRows);
      setLimits(
        Object.fromEntries(orgRows.map((org) => [org.id, { projects_limit: org.projects_limit, leads_limit_per_month: org.leads_limit_per_month }]))
      );
    } catch (error) {
      setAccessDenied(true);
      toast.error(error instanceof Error ? error.message : "Требуются права администратора");
      router.replace("/dashboard");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-12">
        <section className="card">Проверяем доступ...</section>
      </main>
    );
  }

  if (accessDenied) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-12">
        <section className="card">Недостаточно прав. Перенаправляем в дашборд...</section>
      </main>
    );
  }

  const save = async (orgId: string) => {
    try {
      await api(`/admin/organizations/${orgId}/limits`, {
        method: "PATCH",
        body: JSON.stringify(limits[orgId])
      });
      toast.success("Лимиты обновлены");
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить лимиты");
    }
  };

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-12">
      <section className="card">
        <h1 className="text-2xl font-bold">Админ-панель</h1>
        <p className="text-sm text-slate-500">Управление пользователями, организациями и лимитами.</p>
      </section>

      <section className="card">
        <h2 className="mb-3 text-xl font-semibold">Пользователи</h2>
        <div className="space-y-2 text-sm">
          {users.map((user) => (
            <div key={user.id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
              <span className="font-medium">{user.full_name}</span> - {user.email} - {user.is_admin ? "админ" : "участник"}
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h2 className="mb-3 text-xl font-semibold">Организации</h2>
        <div className="space-y-3">
          {orgs.map((org) => (
            <div key={org.id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-700">
              <p className="font-semibold">
                {org.name} ({org.plan})
              </p>
              <p className="text-sm text-slate-500">Использовано {org.leads_used_current_month} лидов за месяц</p>
              <div className="mt-3 grid gap-2 md:grid-cols-[1fr_1fr_auto]">
                <Input
                  type="number"
                  min={1}
                  value={limits[org.id]?.projects_limit ?? org.projects_limit}
                  aria-label="Лимит проектов"
                  onChange={(e) =>
                    setLimits((prev) => ({
                      ...prev,
                      [org.id]: {
                        ...prev[org.id],
                        projects_limit: Math.max(1, Number(e.target.value))
                      }
                    }))
                  }
                />
                <Input
                  type="number"
                  min={1}
                  value={limits[org.id]?.leads_limit_per_month ?? org.leads_limit_per_month}
                  aria-label="Лимит лидов в месяц"
                  onChange={(e) =>
                    setLimits((prev) => ({
                      ...prev,
                      [org.id]: {
                        ...prev[org.id],
                        leads_limit_per_month: Math.max(1, Number(e.target.value))
                      }
                    }))
                  }
                />
                <Button onClick={() => save(org.id)}>Сохранить</Button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

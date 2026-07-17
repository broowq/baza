"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ArrowLeftIcon,
  CheckIcon,
  ClipboardListIcon,
  CopyIcon,
  DownloadIcon,
  MailIcon,
  PlusIcon,
  ShieldIcon,
  Trash2Icon,
  UserIcon,
  UsersIcon,
  ShieldCheckIcon,
  ZapIcon,
  SendIcon,
} from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { clearToken, setOrgId } from "@/lib/auth";
import { formatPlan } from "@/lib/plans";
import { useAuthGuard } from "@/lib/hooks";
import type { Organization, OutreachSettings } from "@/lib/types";

type Invite = {
  id: string;
  email: string;
  role: string;
  // Токен есть не во всех версиях API-ответа — без него ссылку не собрать,
  // и кнопка «скопировать» не показывается (ссылка уходит получателю письмом).
  token?: string;
  accepted: boolean;
  expires_at?: string;
  created_at?: string;
};

function isInviteExpired(invite: Invite): boolean {
  if (invite.accepted || !invite.expires_at) return false;
  const ts = new Date(invite.expires_at).getTime();
  return !Number.isNaN(ts) && ts < Date.now();
}

type Member = {
  user_id: string;
  email: string;
  full_name: string;
  role: "owner" | "admin" | "member";
};

type ActionLog = {
  id: string;
  action: string;
  meta: Record<string, unknown>;
  created_at: string;
};

type TabValue = "profile" | "organization" | "members" | "invites" | "outreach" | "activity" | "privacy";

function getInitials(name: string | undefined): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}


function CopyButton({ onClick }: { onClick: () => Promise<void> }) {
  const [copied, setCopied] = useState(false);
  const handleClick = async () => {
    await onClick();
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] mono t-72 hover:t-100 hover:bg-[var(--surface-hover)] transition-colors [@media(pointer:coarse)]:min-h-10 [@media(pointer:coarse)]:px-4"
    >
      {copied ? <CheckIcon className="size-3" style={{ color: "var(--green)" }} /> : <CopyIcon className="size-3" />}
      {copied ? "скопировано" : "скопировать"}
    </button>
  );
}

const ROLE_LABELS: Record<string, string> = {
  owner: "владелец",
  admin: "админ",
  member: "участник",
};

const ROLE_DOTS: Record<string, string> = {
  owner: "dot-mt",
  admin: "dot-em",
  member: "dot-am",
};

// Слаги журнала действий (backend log_action) → человеческие подписи.
// Неизвестные слаги показываем как есть.
const ACTION_LABELS: Record<string, string> = {
  "auth.password_changed": "Пароль изменён",
  "billing.auto_renew.enabled": "Автопродление включено",
  "billing.auto_renew.disabled": "Автопродление отключено",
  "billing.checkout.created": "Начато оформление оплаты",
  "invite.created": "Приглашение отправлено",
  "invite.accepted": "Приглашение принято",
  "leads.collect.queued": "Запущен сбор лидов",
  "leads.enrich.queued": "Запущено обогащение лидов",
  "leads.enrich_selected.queued": "Запущено обогащение выбранных лидов",
  "member.removed": "Участник удалён",
  "member.role.updated": "Роль участника изменена",
  "organization.plan.updated": "Тариф изменён",
  "pd.exported": "Экспорт персональных данных",
  "pd.delete_requested": "Запрос на удаление данных",
  "project.created": "Проект создан",
  "project.updated": "Проект изменён",
  "project.deleted": "Проект удалён",
  "search.companies.saved": "Сохранены компании из поиска",
};

const actionLabel = (slug: string) => ACTION_LABELS[slug] ?? slug;

export default function SettingsPage() {
  const authed = useAuthGuard();
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<{ email: string; full_name: string; is_admin: boolean } | null>(null);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [orgRole, setOrgRole] = useState<"owner" | "admin" | "member">("member");
  const [actions, setActions] = useState<ActionLog[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [appOrigin, setAppOrigin] = useState(() =>
    typeof window !== "undefined" ? window.location.origin : ""
  );
  const [savingPassword, setSavingPassword] = useState(false);
  const [activeTab, setActiveTab] = useState<TabValue>("profile");
  // Биллинг: последняя подписка (для блока автопродления в «Организации»).
  const [subscription, setSubscription] = useState<{
    status: string;
    plan_id?: string;
    current_period_end?: string | null;
    auto_renew?: boolean;
    payment_method_saved?: boolean;
  } | null>(null);
  const [togglingRenew, setTogglingRenew] = useState(false);

  const load = useCallback(async () => {
    try {
      const [me, org, membership, sub] = await Promise.all([
        api<{ email: string; full_name: string; is_admin: boolean }>("/auth/me").catch(() => null),
        api<Organization>("/organizations/me").catch(() => null),
        api<{ role: "owner" | "admin" | "member" }>("/organizations/membership").catch(() => null),
        api<{
          status: string; plan_id?: string; current_period_end?: string | null;
          auto_renew?: boolean; payment_method_saved?: boolean;
        }>("/billing/subscription").catch(() => null),
      ]);
      if (me) setProfile(me);
      if (org) setOrganization(org);
      if (membership) setOrgRole(membership.role);
      setSubscription(sub && sub.status !== "none" ? sub : null);

      if (!me && !org) {
        toast.error("Не удалось загрузить настройки. Проверьте соединение с сервером.");
      }

      // Use the freshly-fetched role only. Falling back to the stale orgRole
      // state here was unreliable (if the membership fetch failed, the admin
      // sub-fetches below would fail too) and made `load` depend on orgRole.
      const role = membership?.role;
      if (role === "owner" || role === "admin") {
        const [orgInvites, orgMembers, orgActions] = await Promise.all([
          api<Invite[]>("/organizations/invites").catch(() => [] as Invite[]),
          api<Member[]>("/organizations/members").catch(() => [] as Member[]),
          api<ActionLog[]>("/organizations/actions?limit=20").catch(() => [] as ActionLog[]),
        ]);
        setInvites(orgInvites);
        setMembers(orgMembers);
        setActions(orgActions);
      } else {
        setInvites([]);
        setMembers([]);
        setActions([]);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось загрузить настройки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed) void load();
  }, [authed, load]);

  const toggleAutoRenew = async () => {
    if (!subscription) return;
    setTogglingRenew(true);
    try {
      const next = !subscription.auto_renew;
      await api("/billing/auto-renew", {
        method: "POST",
        body: JSON.stringify({ enabled: next }),
      });
      setSubscription({ ...subscription, auto_renew: next });
      toast.success(next ? "Автопродление включено" : "Автопродление отключено");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось изменить автопродление");
    } finally {
      setTogglingRenew(false);
    }
  };

  const createInvite = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/organizations/invites", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: "member" }),
      });
      setInviteEmail("");
      await load();
      toast.success("Приглашение создано");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось создать приглашение");
    }
  };

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    setSavingPassword(true);
    try {
      await api<{ message: string }>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      setCurrentPassword("");
      setNewPassword("");
      toast.success("Пароль обновлён");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить пароль");
    } finally {
      setSavingPassword(false);
    }
  };

  const updateMemberRole = async (memberId: string, role: Member["role"]) => {
    try {
      await api(`/organizations/members/${memberId}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      await load();
      toast.success("Роль участника обновлена");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить роль");
    }
  };

  const removeMember = async (memberId: string) => {
    try {
      await api(`/organizations/members/${memberId}`, { method: "DELETE" });
      await load();
      toast.success("Участник удалён");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось удалить участника");
    }
  };

  const acceptInvite = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const joined = await api<Organization>("/organizations/invites/accept", {
        method: "POST",
        body: JSON.stringify({ token: inviteToken }),
      });
      setInviteToken("");
      setOrgId(joined.id);
      await load();
      toast.success(`Вы присоединились к организации ${joined.name}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось принять приглашение");
    }
  };

  const buildInviteLink = (invite: Invite, token: string) => {
    const params = new URLSearchParams({
      invite_token: token,
      email: invite.email,
    });
    const base = appOrigin;
    return `${base}/login?${params.toString()}`;
  };

  const copyInviteLink = async (invite: Invite) => {
    if (!invite.token) {
      toast.error("Ссылка недоступна — она отправлена получателю на почту");
      return;
    }
    try {
      await navigator.clipboard.writeText(buildInviteLink(invite, invite.token));
      toast.success("Ссылка приглашения скопирована");
    } catch {
      toast.error("Не удалось скопировать ссылку");
    }
  };

  if (!authed || loading) {
    return (
      <main className="relative mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <div className="space-y-6">
          <div className="space-y-2">
            <div className="h-3 w-40 rounded bg-[var(--surface-hover)] animate-pulse" />
            <div className="h-8 w-56 rounded bg-[var(--surface-hover)] animate-pulse" />
            <div className="h-3 w-72 rounded bg-[var(--surface-hover)] animate-pulse" />
          </div>
          <div className="hairline" />
          <div className="grid gap-4 md:grid-cols-[200px_1fr]">
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-9 rounded-lg bg-[var(--surface-1)] animate-pulse" />
              ))}
            </div>
            <div className="space-y-4">
              {[1, 2].map((i) => (
                <div key={i} className="h-48 rounded-2xl bg-[var(--surface-1)] animate-pulse" />
              ))}
            </div>
          </div>
        </div>
      </main>
    );
  }

  const isAdmin = orgRole === "owner" || orgRole === "admin";

  const tabItems: { value: TabValue; label: string; icon: typeof UserIcon }[] = [
    { value: "profile", label: "Профиль", icon: UserIcon },
    { value: "organization", label: "Организация", icon: ZapIcon },
    ...(isAdmin
      ? [{ value: "members" as TabValue, label: "Участники", icon: UsersIcon }]
      : []),
    { value: "invites", label: "Приглашения", icon: MailIcon },
    { value: "outreach", label: "Email-рассылка", icon: SendIcon },
    ...(isAdmin
      ? [{ value: "activity" as TabValue, label: "Журнал", icon: ClipboardListIcon }]
      : []),
    // 152-ФЗ subject rights — выгрузка и удаление ПД. Видна всем
    // пользователям (любому субъекту персональных данных).
    { value: "privacy", label: "Конфиденциальность", icon: ShieldIcon },
  ];

  return (
    <main className="relative mx-auto max-w-[1200px] px-4 py-10 sm:px-6 lg:px-10">
      <div className="space-y-8">
        {/* Layout: tabrail + content */}
        <div className="flex flex-col md:flex-row gap-6 md:gap-10">
          {/* Tabrail */}
          <nav className="flex md:flex-col md:w-[220px] shrink-0 gap-1.5 overflow-x-auto md:overflow-visible">
            <Link
              href="/dashboard"
              className="hidden md:inline-flex items-center gap-1.5 text-[12px] t-48 hover:text-[var(--t-100)] transition-colors mb-2"
            >
              <ArrowLeftIcon className="size-3.5" />
              Назад
            </Link>
            <div className="eyebrow hidden md:block mb-2">настройки</div>
            {tabItems.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.value;
              return (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => setActiveTab(tab.value)}
                  className={`nav-item w-auto md:w-full shrink-0 whitespace-nowrap ${isActive ? "active" : ""}`}
                  style={{ justifyContent: "flex-start" }}
                >
                  <Icon className="ic" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Content */}
          <div className="flex-1 min-w-0 max-w-3xl space-y-6">
            {/* Page header */}
            <div className="space-y-1 mb-2">
              <div className="eyebrow md:hidden">настройки</div>
              <h1 className="h1" style={{ fontSize: 40, lineHeight: 1.05 }}>
                Управление аккаунтом.
              </h1>
              <p className="caption">
                Профиль, организация, участники и журнал действий.
              </p>
            </div>
            {/* Profile */}
            {activeTab === "profile" && (
              <>
                <section className="panel p-6">
                  <div className="eyebrow mb-4">профиль пользователя</div>
                  <div className="flex items-center gap-4">
                    <div
                      className="relative flex size-14 shrink-0 items-center justify-center rounded-full text-[15px] font-medium text-[var(--on-accent)]"
                      style={{ background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)" }}
                    >
                      {getInitials(profile?.full_name)}
                    </div>
                    <div className="space-y-0.5 min-w-0">
                      <p className="text-[15px] text-[var(--t-100)] truncate">
                        {profile?.full_name}
                      </p>
                      <p className="text-[12px] mono t-56 truncate">{profile?.email}</p>
                    </div>
                  </div>
                </section>

                <section className="panel p-6">
                  <div className="eyebrow mb-1">смена пароля</div>
                  <p className="text-[12px] t-56 mb-5">
                    Обновите пароль для вашего аккаунта.
                  </p>
                  <form onSubmit={changePassword} className="space-y-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <label htmlFor="current-password" className="eyebrow">
                          текущий пароль
                        </label>
                        <input
                          className="input"
                          id="current-password"
                          type="password"
                          value={currentPassword}
                          placeholder="Введите текущий пароль"
                          onChange={(e) => setCurrentPassword(e.target.value)}
                          required
                          minLength={8}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label htmlFor="new-password" className="eyebrow">
                          новый пароль
                        </label>
                        <input
                          className="input"
                          id="new-password"
                          type="password"
                          value={newPassword}
                          placeholder="Минимум 8 символов"
                          onChange={(e) => setNewPassword(e.target.value)}
                          required
                          minLength={8}
                        />
                      </div>
                    </div>
                    <div className="flex justify-end">
                      <button
                        type="submit"
                        disabled={savingPassword}
                        className="brand rounded-full px-5 py-2.5 text-[13px] disabled:opacity-50 disabled:pointer-events-none"
                      >
                        {savingPassword ? "Сохранение…" : "Сменить пароль"}
                      </button>
                    </div>
                  </form>
                </section>
              </>
            )}

            {/* Organization */}
            {activeTab === "organization" && (
              <section className="panel p-6">
                <div className="eyebrow mb-1">организация</div>
                <h2 className="h2 mb-1" style={{ fontSize: 22 }}>
                  {organization?.name ?? "—"}
                </h2>
                <p className="text-[12px] t-56 mb-5">
                  Настройки и лимиты вашей организации.
                </p>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="panel-flat p-4">
                    <div className="eyebrow mb-1">тариф</div>
                    <div className="flex items-center gap-2">
                      <span className="dot dot-mt" />
                      <span
                        className="text-[var(--t-100)]"
                        style={{ fontSize: 18, fontWeight: 300 }}
                      >
                        {formatPlan(organization?.plan) || "---"}
                      </span>
                    </div>
                    {(organization?.ai_cost_limit_kopecks_per_month ?? 0) > 0 && (
                      <p className="tnum t-72 text-[11px] mt-2">
                        AI-бюджет:{" "}
                        <span className="text-[var(--t-100)]">
                          {((organization?.ai_cost_used_kopecks_current_month ?? 0) / 100).toLocaleString("ru-RU")} ₽
                        </span>
                        <span className="t-48">
                          {" "}из {((organization?.ai_cost_limit_kopecks_per_month ?? 0) / 100).toLocaleString("ru-RU")} ₽
                        </span>
                      </p>
                    )}
                  </div>
                  <div className="panel-flat p-4">
                    {/* Free-триал разовый: лиды не возобновляются, поэтому без «в месяце». */}
                    <div className="eyebrow mb-1">
                      {organization?.plan === "free" ? "пробные лиды" : "лиды в месяце"}
                    </div>
                    <p
                      className="tnum text-[var(--t-100)]"
                      style={{ fontSize: 18, fontWeight: 300 }}
                    >
                      {(organization?.leads_used_current_month ?? 0).toLocaleString("ru-RU")}
                      <span className="t-48 ml-1 text-[13px]">
                        {organization?.plan === "free" ? "из" : "/"}{" "}
                        {(organization?.leads_limit_per_month ?? 0).toLocaleString("ru-RU")}
                      </span>
                    </p>
                  </div>
                  <div className="panel-flat p-4">
                    <div className="eyebrow mb-1">пользователей</div>
                    <p
                      className="tnum text-[var(--t-100)]"
                      style={{ fontSize: 18, fontWeight: 300 }}
                    >
                      {organization?.users_limit ?? "---"}
                    </p>
                  </div>
                </div>

                <div className="hairline my-6" />

                {/* Автопродление — только для активной платной подписки */}
                {subscription?.status === "active" && (orgRole === "owner" || orgRole === "admin") && (
                  <>
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <div className="eyebrow mb-1">автопродление</div>
                        <p className="text-[12px] t-72">
                          {subscription.auto_renew
                            ? subscription.payment_method_saved
                              ? `Включено — спишем автоматически${subscription.current_period_end ? ` ${new Date(subscription.current_period_end).toLocaleDateString("ru-RU")}` : ""}.`
                              : "Включено, но карта не сохранена — оплатите тариф заново с галочкой «Автопродление»."
                            : "Отключено — после конца оплаченного периода организация перейдёт на Free."}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={toggleAutoRenew}
                        disabled={togglingRenew || (!subscription.auto_renew && !subscription.payment_method_saved)}
                        className="ghost rounded-full px-4 py-2 text-[13px] shrink-0 disabled:opacity-45"
                      >
                        {togglingRenew
                          ? "Сохраняю..."
                          : subscription.auto_renew
                            ? "Отключить"
                            : "Включить"}
                      </button>
                    </div>
                    <div className="hairline my-6" />
                  </>
                )}

                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-[12px] t-72">
                    Смена тарифа выполняется через оформление оплаты на странице тарифов.
                  </p>
                  <Link
                    href="/plans"
                    className="brand rounded-full px-4 py-2 text-[13px] inline-flex items-center gap-2 shrink-0"
                  >
                    <ZapIcon className="size-3.5" />
                    Открыть тарифы
                  </Link>
                </div>

                {isAdmin && (
                  <>
                    <div className="hairline my-6" />
                    <div className="space-y-3">
                      <div>
                        <div className="eyebrow mb-1">crm-интеграция (webhook)</div>
                        <p className="text-[12px] t-56">
                          URL вашего Bitrix24 / AmoCRM / любого webhook-приёмника.
                          Каждый новый лид (после обогащения) будет POST-иться сюда
                          как JSON. Оставьте пустым чтобы отключить.
                        </p>
                      </div>
                      <WebhookEditor
                        currentUrl={
                          (organization as Organization & { lead_webhook_url?: string } | null)
                            ?.lead_webhook_url ?? ""
                        }
                        onSaved={(url) =>
                          setOrganization((o) =>
                            o
                              ? ({ ...o, lead_webhook_url: url } as Organization & { lead_webhook_url: string })
                              : o
                          )
                        }
                      />
                    </div>
                  </>
                )}
              </section>
            )}

            {/* Members */}
            {activeTab === "members" && isAdmin && (
              <section className="panel p-6">
                <div className="eyebrow mb-1">участники</div>
                <p className="text-[12px] t-56 mb-5">
                  Управление участниками и ролями организации.
                </p>

                {members.length === 0 ? (
                  <EmptyState
                    icon={<UsersIcon className="size-5 t-48" />}
                    text="Участников пока нет."
                  />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b border-[var(--line)]">
                          <th className="eyebrow text-left py-2.5">участник</th>
                          <th className="eyebrow text-left py-2.5">роль</th>
                          <th className="eyebrow text-right py-2.5">действия</th>
                        </tr>
                      </thead>
                      <tbody>
                        {members.map((member) => (
                          <tr
                            key={member.user_id}
                            className="border-b border-[var(--line)] last:border-0"
                          >
                            <td className="py-3">
                              <div className="flex items-center gap-3">
                                <div
                                  className="flex size-8 shrink-0 items-center justify-center rounded-full text-[10px] mono text-[var(--on-accent)]"
                                  style={{
                                    background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)",
                                  }}
                                >
                                  {getInitials(member.full_name)}
                                </div>
                                <div className="min-w-0 max-w-[240px]">
                                  <p className="text-[13px] text-[var(--t-100)] truncate" title={member.full_name}>
                                    {member.full_name}
                                  </p>
                                  <p className="text-[11px] mono t-48 truncate" title={member.email}>
                                    {member.email}
                                  </p>
                                </div>
                              </div>
                            </td>
                            <td className="py-3">
                              {orgRole === "owner" && member.email !== profile?.email ? (
                                <Select
                                  value={member.role}
                                  onValueChange={(val) =>
                                    updateMemberRole(member.user_id, val as Member["role"])
                                  }
                                >
                                  <SelectTrigger size="sm" className="bg-[var(--surface-input)] border-[var(--line-2)]">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="member">Участник</SelectItem>
                                    <SelectItem value="admin">Админ</SelectItem>
                                    <SelectItem value="owner">Владелец</SelectItem>
                                  </SelectContent>
                                </Select>
                              ) : (
                                <span className="inline-flex items-center gap-1.5 rounded-full panel-thin px-2.5 py-1 text-[11px] mono">
                                  <span className={`dot ${ROLE_DOTS[member.role] ?? "dot-am"}`} />
                                  {member.role === "owner" && (
                                    <ShieldCheckIcon className="size-3" />
                                  )}
                                  {ROLE_LABELS[member.role] ?? member.role}
                                </span>
                              )}
                            </td>
                            <td className="text-right py-3">
                              {member.email !== profile?.email && orgRole === "owner" && (
                                <AlertDialog>
                                  <AlertDialogTrigger
                                    render={
                                      <button
                                        type="button"
                                        className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] mono t-72 hover:bg-[var(--surface-hover)] hover:t-100 transition-colors [@media(pointer:coarse)]:min-h-10 [@media(pointer:coarse)]:px-4"
                                      >
                                        <Trash2Icon className="size-3" />
                                        удалить
                                      </button>
                                    }
                                  />
                                  <AlertDialogContent>
                                    <AlertDialogHeader>
                                      <AlertDialogTitle>Удалить участника?</AlertDialogTitle>
                                      <AlertDialogDescription>
                                        {member.full_name} ({member.email}) будет удалён
                                        из организации. Это действие нельзя отменить.
                                      </AlertDialogDescription>
                                    </AlertDialogHeader>
                                    <AlertDialogFooter>
                                      <AlertDialogCancel>Отмена</AlertDialogCancel>
                                      <AlertDialogAction
                                        variant="destructive"
                                        onClick={() => removeMember(member.user_id)}
                                      >
                                        Удалить
                                      </AlertDialogAction>
                                    </AlertDialogFooter>
                                  </AlertDialogContent>
                                </AlertDialog>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {/* Invites */}
            {activeTab === "invites" && (
              <>
                {isAdmin && (
                  <section className="panel p-6">
                    <div className="flex flex-col sm:flex-row items-start justify-between gap-3 mb-5">
                      <div>
                        <div className="eyebrow mb-1">приглашения</div>
                        <p className="text-[12px] t-56">
                          Управление приглашениями в организацию.
                        </p>
                      </div>
                      <Dialog>
                        <DialogTrigger
                          render={
                            <button
                              type="button"
                              className="brand rounded-full px-4 py-2 text-[13px] inline-flex items-center gap-2 shrink-0"
                            >
                              <PlusIcon className="size-3.5" />
                              Пригласить
                            </button>
                          }
                        />
                        <DialogContent>
                          <DialogHeader>
                            <DialogTitle>Новое приглашение</DialogTitle>
                            <DialogDescription>
                              Введите email коллеги для отправки приглашения.
                            </DialogDescription>
                          </DialogHeader>
                          <form
                            onSubmit={(e) => {
                              void createInvite(e);
                            }}
                            className="space-y-4"
                          >
                            <div className="space-y-1.5">
                              <label htmlFor="invite-email" className="eyebrow">
                                email
                              </label>
                              <input
                                className="input"
                                id="invite-email"
                                type="email"
                                value={inviteEmail}
                                placeholder="коллега@company.com"
                                onChange={(e) => setInviteEmail(e.target.value)}
                                required
                              />
                            </div>
                            <DialogFooter>
                              <DialogClose
                                render={
                                  <button
                                    type="button"
                                    className="ghost rounded-full px-4 py-2 text-[13px]"
                                  >
                                    Отмена
                                  </button>
                                }
                              />
                              <button
                                type="submit"
                                className="brand rounded-full px-4 py-2 text-[13px]"
                              >
                                Создать приглашение
                              </button>
                            </DialogFooter>
                          </form>
                        </DialogContent>
                      </Dialog>
                    </div>

                    {invites.length === 0 ? (
                      <EmptyState
                        icon={<MailIcon className="size-5 t-48" />}
                        text="Приглашений пока нет."
                      />
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full">
                          <thead>
                            <tr className="border-b border-[var(--line)]">
                              <th className="eyebrow text-left py-2.5">email</th>
                              <th className="eyebrow text-left py-2.5">статус</th>
                              <th className="eyebrow text-right py-2.5">действия</th>
                            </tr>
                          </thead>
                          <tbody>
                            {invites.map((invite) => {
                              const expired = isInviteExpired(invite);
                              return (
                                <tr
                                  key={invite.id}
                                  className="border-b border-[var(--line)] last:border-0"
                                >
                                  <td className="py-3 text-[13px] text-[var(--t-100)]">
                                    <span className="block max-w-[240px] truncate" title={invite.email}>
                                      {invite.email}
                                    </span>
                                  </td>
                                  <td className="py-3">
                                    <span className="inline-flex items-center gap-1.5 rounded-full panel-thin px-2.5 py-1 text-[11px] mono">
                                      <span
                                        className={`dot ${invite.accepted ? "dot-em" : expired ? "dot-rs" : "dot-am"}`}
                                      />
                                      {invite.accepted ? "принято" : expired ? "истекло" : "ожидает"}
                                    </span>
                                    {!invite.accepted && !expired && invite.expires_at && (
                                      <span className="block text-[10.5px] mono t-48 mt-1">
                                        до {new Date(invite.expires_at).toLocaleDateString("ru-RU")}
                                      </span>
                                    )}
                                  </td>
                                  <td className="text-right py-3">
                                    {!invite.accepted && !expired && (
                                      invite.token ? (
                                        <CopyButton onClick={() => copyInviteLink(invite)} />
                                      ) : (
                                        <span className="text-[10.5px] mono t-48">
                                          ссылка отправлена письмом
                                        </span>
                                      )
                                    )}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                )}

                {!isAdmin && (
                  <section className="panel p-6">
                    <div className="eyebrow mb-1">приглашения</div>
                    <p className="text-[12px] t-56">
                      Список приглашений доступен только owner / admin.
                    </p>
                  </section>
                )}

                <section className="panel p-6">
                  <div className="eyebrow mb-1">принять приглашение</div>
                  <p className="text-[12px] t-56 mb-5">
                    Введите токен, чтобы присоединиться к организации.
                  </p>
                  <form
                    onSubmit={acceptInvite}
                    className="flex flex-col gap-3 sm:flex-row"
                  >
                    <input
                      className="input sm:flex-1"
                      placeholder="Токен приглашения"
                      value={inviteToken}
                      onChange={(e) => setInviteToken(e.target.value)}
                      required
                    />
                    <button
                      type="submit"
                      className="ghost rounded-full px-4 py-2 text-[13px] inline-flex items-center gap-2 shrink-0"
                    >
                      <UserIcon className="size-3.5" />
                      Принять
                    </button>
                  </form>
                </section>
              </>
            )}

            {/* Email outreach */}
            {activeTab === "outreach" && (
              <OutreachTab canEdit={isAdmin} userEmail={profile?.email ?? ""} />
            )}

            {/* Activity */}
            {activeTab === "activity" && isAdmin && (
              <section className="panel p-6">
                <div className="eyebrow mb-1">журнал действий</div>
                <p className="text-[12px] t-56 mb-5">
                  Последние действия в организации.
                </p>

                {actions.length === 0 ? (
                  <EmptyState
                    icon={<ClipboardListIcon className="size-5 t-48" />}
                    text="Записей пока нет."
                  />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b border-[var(--line)]">
                          <th className="eyebrow text-left py-2.5">действие</th>
                          <th className="eyebrow text-right py-2.5">дата</th>
                        </tr>
                      </thead>
                      <tbody>
                        {actions.map((item) => (
                          <tr
                            key={item.id}
                            className="border-b border-[var(--line)] last:border-0"
                          >
                            <td className="py-3">
                              <span
                                className={`inline-flex items-center rounded-md panel-flat px-2 py-0.5 text-[11px] ${
                                  ACTION_LABELS[item.action] ? "" : "mono"
                                }`}
                                title={item.action}
                              >
                                {actionLabel(item.action)}
                              </span>
                            </td>
                            <td className="text-right py-3">
                              <span className="text-[11px] mono t-48">
                                {new Date(item.created_at).toLocaleString("ru-RU")}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {/* ── Privacy / Subject Rights tab — 152-ФЗ compliance ───── */}
            {activeTab === "privacy" && (
              <PrivacyTab profileEmail={profile?.email ?? ""} />
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

function EmptyState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-[var(--surface-1)] border border-[var(--line)] mb-3">
        {icon}
      </div>
      <p className="text-[12px] t-56">{text}</p>
    </div>
  );
}

function WebhookEditor({
  currentUrl,
  onSaved,
}: {
  currentUrl: string;
  onSaved: (url: string) => void;
}) {
  const [value, setValue] = useState(currentUrl);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api("/organizations/me/webhook", {
        method: "PATCH",
        body: JSON.stringify({ lead_webhook_url: value.trim() }),
      });
      onSaved(value.trim());
      toast.success(value.trim() ? "Webhook сохранён" : "Webhook отключён");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const dirty = value.trim() !== (currentUrl ?? "").trim();

  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <input
        className="input sm:flex-1"
        type="url"
        placeholder="https://your-domain.bitrix24.ru/rest/1/xxx..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button
        type="button"
        onClick={save}
        disabled={saving || !dirty}
        className="brand rounded-full px-4 py-2 text-[13px] disabled:opacity-50 disabled:pointer-events-none shrink-0"
      >
        {saving ? "Сохранение…" : "Сохранить"}
      </button>
    </div>
  );
}


/* ───────────────────────────────────────────────────────────────────
   Privacy tab — реализация прав субъекта ПД по 152-ФЗ.
   Доступ ко всем своим ПД (ст. 14 ч. 7) + удаление аккаунта (ст. 21).
   Видна каждому пользователю независимо от роли.
   ─────────────────────────────────────────────────────────────────── */

function PrivacyTab({ profileEmail }: { profileEmail: string }) {
  const [exporting, setExporting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteReason, setDeleteReason] = useState("");
  const [deleting, setDeleting] = useState(false);

  const onExport = async () => {
    setExporting(true);
    try {
      const data = await api<Record<string, unknown>>("/auth/me/export");
      // Sanitize filename — выгружаем под уникальным именем
      // с email + timestamp, чтобы потом легко разобраться в нескольких файлах.
      const slug = profileEmail.replace(/[^a-z0-9]+/gi, "_").toLowerCase().slice(0, 40) || "user";
      const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
      const filename = `baza-pd-export-${slug}-${stamp}.json`;
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success("Экспорт ПД скачан. Дополнительно факт обращения зафиксирован в журнале.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось выгрузить ПД");
    } finally {
      setExporting(false);
    }
  };

  const onDelete = async () => {
    if (deletePassword.length < 1) {
      toast.error("Введите ваш пароль для подтверждения");
      return;
    }
    setDeleting(true);
    try {
      await api<{ message: string }>("/auth/me", {
        method: "DELETE",
        body: JSON.stringify({
          password: deletePassword,
          reason: deleteReason || "",
        }),
      });
      // После DELETE серверный access-токен ещё в localStorage — чистим,
      // чтобы не показывать «зомби»-состояние UI авторизованным.
      if (typeof window !== "undefined") {
        clearToken();
        window.location.href = "/?deleted=1";
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось удалить аккаунт");
      setDeleting(false);
    }
  };

  return (
    <>
      <section className="panel p-6">
        <div className="eyebrow mb-1">персональные данные</div>
        <p className="text-[12px] t-56 mb-5">
          В соответствии с 152-ФЗ вы можете в любой момент получить копию своих
          персональных данных или потребовать их удаления. Все обращения
          фиксируются в журнале обработки.
        </p>

        <div className="space-y-4">
          {/* Экспорт ПД — на мобиле текст сверху, кнопка снизу во всю ширину */}
          <div className="panel-flat p-5 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="min-w-0 flex-1 break-words">
              <div className="eyebrow mb-1">право на доступ · ст. 14 ч. 7</div>
              <p className="text-[13px] t-84">
                Скачать все ваши персональные данные одним JSON-файлом — профиль,
                членство, организации, проекты, журнал ваших действий.
              </p>
              <p className="text-[11px] mono t-48 mt-1.5">
                лимит: 1 запрос в минуту
              </p>
            </div>
            <button
              type="button"
              onClick={onExport}
              disabled={exporting}
              className="btn btn-ghost shrink-0 w-full sm:w-auto"
            >
              <DownloadIcon className="size-3.5" />
              {exporting ? "Готовим…" : "Скачать ПД"}
            </button>
          </div>

          {/* Удаление */}
          <div
            className="panel-flat p-5 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4"
            style={{ borderColor: "rgba(244,63,94,0.18)" }}
          >
            <div className="min-w-0 flex-1 break-words">
              <div className="eyebrow mb-1" style={{ color: "var(--rose)" }}>
                право на уничтожение · ст. 21
              </div>
              <p className="text-[13px] t-84">
                Полное и необратимое удаление аккаунта и связанных данных. Если
                вы — единственный владелец организации, она удаляется целиком
                со всеми проектами и лидами.
              </p>
              <p className="text-[11px] mono t-48 mt-1.5">
                действие невозможно отменить
              </p>
            </div>
            <button
              type="button"
              onClick={() => setDeleteOpen(true)}
              className="btn btn-ghost shrink-0 w-full sm:w-auto"
              style={{ color: "var(--rose)", borderColor: "rgba(244,63,94,0.30)" }}
            >
              <Trash2Icon className="size-3.5" />
              Удалить аккаунт
            </button>
          </div>
        </div>
      </section>

      {/* Контакт оператора */}
      <section className="panel p-6">
        <div className="eyebrow mb-1">контакты оператора ПД</div>
        <p className="text-[12px] t-56 mb-4">
          Оператор: <span className="t-84">ООО «ПРО ЛЕС», ОГРН 1215400050117, ИНН 5406817586</span>,
          usebaza.ru. Полный текст Политики обработки персональных данных —{" "}
          <Link href={"/privacy" as never} className="text-[var(--t-100)] underline underline-offset-2">
            на странице /privacy
          </Link>.
        </p>
        <div className="flex flex-wrap gap-x-8 gap-y-2 text-[12.5px]">
          <span className="t-84">
            <span className="t-48 mono">email DPO:</span>{" "}
            <a href="mailto:dpo@usebaza.ru" className="text-[var(--t-100)]">dpo@usebaza.ru</a>
          </span>
          <span className="t-84">
            <span className="t-48 mono">общие вопросы:</span>{" "}
            <a href="mailto:support@usebaza.ru" className="text-[var(--t-100)]">support@usebaza.ru</a>
          </span>
        </div>
      </section>

      {/* Confirm-dialog для удаления */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить аккаунт?</DialogTitle>
            <DialogDescription>
              Это действие необратимо. Будут удалены ваш профиль, ваши данные в
              продукте и (если вы — единственный владелец) ваша организация со
              всеми её проектами и лидами. Введите пароль для подтверждения.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 mt-1">
            <div>
              <div className="eyebrow mb-2" style={{ fontSize: 10 }}>пароль</div>
              <input
                type="password"
                value={deletePassword}
                onChange={(e) => setDeletePassword(e.target.value)}
                placeholder="••••••••"
                className="input"
                autoFocus
              />
            </div>
            <div>
              <div className="eyebrow mb-2" style={{ fontSize: 10 }}>причина (необязательно)</div>
              <input
                type="text"
                value={deleteReason}
                onChange={(e) => setDeleteReason(e.target.value.slice(0, 500))}
                placeholder="Отзыв согласия / закрытие бизнеса / иное"
                className="input"
              />
              <p className="mono-cap mt-1.5 t-48" style={{ fontSize: 11 }}>
                фиксируется в журнале обращений субъектов ПД
              </p>
            </div>
          </div>
          <DialogFooter className="mt-4">
            <button
              type="button"
              onClick={() => setDeleteOpen(false)}
              className="ghost rounded-full px-4 py-2 text-[13px]"
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting || deletePassword.length < 1}
              className="rounded-full px-4 py-2 text-[13px] text-white disabled:opacity-50 disabled:pointer-events-none"
              style={{ background: "var(--rose)" }}
            >
              {deleting ? "Удаляем…" : "Удалить навсегда"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}


/* ───────────────────────────────────────────────────────────────────
   Email-рассылка — настройки SMTP/IMAP клиента.
   Письма уходят ЧЕРЕЗ ПОЧТУ КЛИЕНТА (его сервер, его адрес/домен).
   Редактирование доступно owner / admin; остальные видят статус read-only.
   ─────────────────────────────────────────────────────────────────── */

const OUTREACH_HINTS = [
  { name: "Яндекс 360", host: "smtp.yandex.ru", port: 465, note: "SSL" },
  { name: "Mail.ru", host: "smtp.mail.ru", port: 465, note: "SSL" },
];

type OutreachForm = {
  from_name: string;
  from_email: string;
  smtp_host: string;
  smtp_port: string;
  smtp_user: string;
  smtp_password: string;
  smtp_use_tls: boolean;
  imap_host: string;
  imap_port: string;
  imap_user: string;
  imap_password: string;
  daily_limit: string;
};

function settingsToForm(s: OutreachSettings): OutreachForm {
  return {
    from_name: s.from_name ?? "",
    from_email: s.from_email ?? "",
    smtp_host: s.smtp_host ?? "",
    smtp_port: String(s.smtp_port || 587),
    smtp_user: s.smtp_user ?? "",
    smtp_password: "",
    smtp_use_tls: s.smtp_use_tls ?? true,
    imap_host: s.imap_host ?? "",
    imap_port: String(s.imap_port || 993),
    imap_user: s.imap_user ?? "",
    imap_password: "",
    daily_limit: String(s.daily_limit || 50),
  };
}

function OutreachTab({ canEdit, userEmail }: { canEdit: boolean; userEmail: string }) {
  const [settings, setSettings] = useState<OutreachSettings | null>(null);
  const [form, setForm] = useState<OutreachForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [imapOpen, setImapOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api<OutreachSettings>("/outreach/settings");
      setSettings(s);
      setForm(settingsToForm(s));
      // Раскрыть IMAP-блок, если он уже заполнен.
      if (s.imap_host || s.imap_user || s.imap_password_set) setImapOpen(true);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось загрузить настройки рассылки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const set = <K extends keyof OutreachForm>(key: K, value: OutreachForm[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  const onSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        from_name: form.from_name.trim(),
        from_email: form.from_email.trim(),
        smtp_host: form.smtp_host.trim(),
        smtp_port: Number(form.smtp_port) || 587,
        smtp_user: form.smtp_user.trim(),
        smtp_use_tls: form.smtp_use_tls,
        imap_host: form.imap_host.trim(),
        imap_port: Number(form.imap_port) || 993,
        imap_user: form.imap_user.trim(),
        daily_limit: Number(form.daily_limit) || 0,
      };
      // Пароли write-only: шлём только если пользователь ввёл новый.
      if (form.smtp_password) body.smtp_password = form.smtp_password;
      if (form.imap_password) body.imap_password = form.imap_password;

      await api("/outreach/settings", { method: "PUT", body: JSON.stringify(body) });
      toast.success("Настройки рассылки сохранены");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось сохранить настройки");
    } finally {
      setSaving(false);
    }
  };

  const onTest = async () => {
    const to = window.prompt("Куда отправить тестовое письмо?", userEmail || "");
    if (!to) return;
    setTesting(true);
    try {
      const res = await api<{ ok: boolean; error: string }>("/outreach/settings/test", {
        method: "POST",
        body: JSON.stringify({ to_email: to.trim() }),
      });
      if (res.ok) {
        toast.success(`Тестовое письмо отправлено на ${to.trim()}`);
        await load();
      } else {
        toast.error(res.error || "Не удалось отправить тестовое письмо");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось отправить тестовое письмо");
    } finally {
      setTesting(false);
    }
  };

  if (loading || !form || !settings) {
    return (
      <section className="panel p-6">
        <div className="eyebrow mb-4">email-рассылка</div>
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-10 rounded-lg bg-[var(--surface-1)] animate-pulse" />
          ))}
        </div>
      </section>
    );
  }

  // Три честных состояния: настроек нет / SMTP заполнен, но тест не пройден /
  // подключено и проверено тестовым письмом.
  const status = !settings.configured
    ? { label: "Не настроено", dot: "dot-am", dim: true }
    : settings.verified
      ? { label: "Подключено и проверено", dot: "dot-em", dim: false }
      : { label: "Настроено, ждёт проверки", dot: "dot-am", dim: false };

  return (
    <>
      <section className="panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-1">
          <div className="eyebrow">email-рассылка</div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full panel-thin px-2.5 py-1 text-[11px] mono ${
              status.dim ? "t-56" : ""
            }`}
          >
            <span className={`dot ${status.dot}`} />
            {status.label}
          </span>
        </div>
        <p className="text-[12px] t-56 mb-3">
          Рассылка идёт через вашу почту (ваш SMTP): письма уходят с вашего адреса и домена.
          Перед отправкой убедитесь, что у вас есть согласие получателей — это ваша ответственность.
        </p>

        <div className="flex flex-wrap items-center gap-2 mb-5">
          <span className="inline-flex items-center rounded-md panel-flat px-2 py-0.5 text-[11px] mono t-72">
            Отправлено сегодня:{" "}
            <span className="text-[var(--t-100)] ml-1 tnum">
              {settings.sent_today}
            </span>
            <span className="t-48 ml-1">/ {settings.daily_limit}</span>
          </span>
        </div>

        <form onSubmit={onSave} className="space-y-4">
          {/* Отправитель */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="o-from-name" className="eyebrow">имя отправителя</label>
              <input
                id="o-from-name"
                className="input"
                type="text"
                value={form.from_name}
                placeholder="Например, Иван из ПРО ЛЕС"
                onChange={(e) => set("from_name", e.target.value)}
                disabled={!canEdit}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="o-from-email" className="eyebrow">email отправителя *</label>
              <input
                id="o-from-email"
                className="input"
                type="email"
                value={form.from_email}
                placeholder="you@company.ru"
                onChange={(e) => set("from_email", e.target.value)}
                disabled={!canEdit}
                required
              />
            </div>
          </div>

          {/* SMTP */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="o-smtp-host" className="eyebrow">smtp-хост</label>
              <input
                id="o-smtp-host"
                className="input"
                type="text"
                value={form.smtp_host}
                placeholder="smtp.yandex.ru"
                onChange={(e) => set("smtp_host", e.target.value)}
                disabled={!canEdit}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="o-smtp-port" className="eyebrow">smtp-порт</label>
              <input
                id="o-smtp-port"
                className="input"
                type="number"
                value={form.smtp_port}
                placeholder="587"
                onChange={(e) => set("smtp_port", e.target.value)}
                disabled={!canEdit}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="o-smtp-user" className="eyebrow">smtp-логин</label>
              <input
                id="o-smtp-user"
                className="input"
                type="text"
                value={form.smtp_user}
                placeholder="you@company.ru"
                onChange={(e) => set("smtp_user", e.target.value)}
                disabled={!canEdit}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="o-smtp-pass" className="eyebrow">smtp-пароль</label>
              <input
                id="o-smtp-pass"
                className="input"
                type="password"
                value={form.smtp_password}
                placeholder={settings.smtp_password_set ? "••• сохранён" : "Пароль приложения"}
                onChange={(e) => set("smtp_password", e.target.value)}
                disabled={!canEdit}
                autoComplete="new-password"
              />
            </div>
          </div>

          {/* TLS + лимит */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <span className="eyebrow">шифрование</span>
              <button
                type="button"
                onClick={() => canEdit && set("smtp_use_tls", !form.smtp_use_tls)}
                disabled={!canEdit}
                aria-pressed={form.smtp_use_tls}
                className="focus-ring flex items-center gap-2.5 rounded-full panel-thin px-3 py-2 text-[12px] disabled:opacity-50 disabled:pointer-events-none w-full"
              >
                <span
                  className="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors"
                  style={{
                    background: form.smtp_use_tls ? "var(--mint)" : "var(--surface-3)",
                  }}
                >
                  <span
                    className="inline-block size-4 rounded-full bg-[var(--on-accent)] transition-transform"
                    style={{ transform: form.smtp_use_tls ? "translateX(18px)" : "translateX(2px)" }}
                  />
                </span>
                <span className="t-84">TLS</span>
                <span className="t-48 mono text-[11px] ml-auto">
                  {form.smtp_use_tls ? "вкл" : "выкл"}
                </span>
              </button>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="o-daily" className="eyebrow">лимит писем в день</label>
              <input
                id="o-daily"
                className="input"
                type="number"
                min={0}
                value={form.daily_limit}
                placeholder="50"
                onChange={(e) => set("daily_limit", e.target.value)}
                disabled={!canEdit}
              />
            </div>
          </div>

          {/* Подсказки провайдеров */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <span className="text-[11px] t-48 mono">подсказки:</span>
            {OUTREACH_HINTS.map((h) => (
              <span key={h.name} className="text-[11px] t-56">
                <span className="t-84">{h.name}:</span>{" "}
                <span className="mono t-72">{h.host}:{h.port}</span>{" "}
                <span className="t-48">{h.note}</span>
              </span>
            ))}
          </div>

          {/* IMAP — collapsible */}
          <div className="panel-flat p-4">
            <button
              type="button"
              onClick={() => setImapOpen((v) => !v)}
              className="focus-ring flex w-full items-center justify-between gap-2 text-left"
            >
              <span>
                <span className="eyebrow block">IMAP — авто-остановка при ответе</span>
                <span className="text-[11px] t-48">
                  Необязательно. Если получатель ответил — последовательность для него остановится автоматически.
                </span>
              </span>
              <span className="text-[12px] mono t-56 shrink-0">{imapOpen ? "скрыть" : "показать"}</span>
            </button>

            {imapOpen && (
              <div className="grid gap-4 sm:grid-cols-2 mt-4">
                <div className="space-y-1.5">
                  <label htmlFor="o-imap-host" className="eyebrow">imap-хост</label>
                  <input
                    id="o-imap-host"
                    className="input"
                    type="text"
                    value={form.imap_host}
                    placeholder="imap.yandex.ru"
                    onChange={(e) => set("imap_host", e.target.value)}
                    disabled={!canEdit}
                  />
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="o-imap-port" className="eyebrow">imap-порт</label>
                  <input
                    id="o-imap-port"
                    className="input"
                    type="number"
                    value={form.imap_port}
                    placeholder="993"
                    onChange={(e) => set("imap_port", e.target.value)}
                    disabled={!canEdit}
                  />
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="o-imap-user" className="eyebrow">imap-логин</label>
                  <input
                    id="o-imap-user"
                    className="input"
                    type="text"
                    value={form.imap_user}
                    placeholder="you@company.ru"
                    onChange={(e) => set("imap_user", e.target.value)}
                    disabled={!canEdit}
                  />
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="o-imap-pass" className="eyebrow">imap-пароль</label>
                  <input
                    id="o-imap-pass"
                    className="input"
                    type="password"
                    value={form.imap_password}
                    placeholder={settings.imap_password_set ? "••• сохранён" : "Пароль приложения"}
                    onChange={(e) => set("imap_password", e.target.value)}
                    disabled={!canEdit}
                    autoComplete="new-password"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          {canEdit ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:justify-end pt-1">
              <button
                type="button"
                onClick={onTest}
                disabled={testing || saving}
                className="btn btn-ghost shrink-0"
              >
                <SendIcon className="size-3.5" />
                {testing ? "Отправляем…" : "Отправить тест"}
              </button>
              <button
                type="submit"
                disabled={saving || testing}
                className="brand rounded-full px-5 py-2.5 text-[13px] disabled:opacity-50 disabled:pointer-events-none shrink-0"
              >
                {saving ? "Сохранение…" : "Сохранить"}
              </button>
            </div>
          ) : (
            <p className="text-[12px] t-48 pt-1">
              Изменять настройки рассылки могут только владелец и админ.
            </p>
          )}
        </form>
      </section>
    </>
  );
}

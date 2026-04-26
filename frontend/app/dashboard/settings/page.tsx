"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  ArrowLeftIcon,
  CheckIcon,
  ClipboardListIcon,
  CopyIcon,
  MailIcon,
  PlusIcon,
  Trash2Icon,
  UserIcon,
  UsersIcon,
  ShieldCheckIcon,
  ZapIcon,
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
import { setOrgId } from "@/lib/auth";
import { useAuthGuard } from "@/lib/hooks";
import type { Organization } from "@/lib/types";

type Invite = {
  id: string;
  email: string;
  role: string;
  token: string;
  accepted: boolean;
};

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

type TabValue = "profile" | "organization" | "members" | "invites" | "activity";

function getInitials(name: string | undefined): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

function GlassInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={
        "w-full h-10 rounded-xl border border-[var(--line-2)] bg-white/[0.04] px-3 text-[13px] text-white placeholder:text-white/40 outline-none focus:border-white/[0.24] focus:bg-white/[0.07] transition-colors " +
        (props.className ?? "")
      }
    />
  );
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
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] mono t-72 hover:t-100 hover:bg-white/[0.06] transition-colors"
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
  const [appOrigin, setAppOrigin] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [activeTab, setActiveTab] = useState<TabValue>("profile");

  const load = async () => {
    try {
      const [me, org, membership] = await Promise.all([
        api<{ email: string; full_name: string; is_admin: boolean }>("/auth/me").catch(() => null),
        api<Organization>("/organizations/me").catch(() => null),
        api<{ role: "owner" | "admin" | "member" }>("/organizations/membership").catch(() => null),
      ]);
      if (me) setProfile(me);
      if (org) setOrganization(org);
      if (membership) setOrgRole(membership.role);

      if (!me && !org) {
        toast.error("Не удалось загрузить настройки. Проверьте соединение с сервером.");
      }

      const role = membership?.role ?? orgRole;
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
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      setAppOrigin(window.location.origin);
    }
    if (authed) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed]);

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

  const buildInviteLink = (invite: Invite) => {
    const params = new URLSearchParams({
      invite_token: invite.token,
      email: invite.email,
    });
    const base = appOrigin || "http://localhost:3000";
    return `${base}/login?${params.toString()}`;
  };

  const copyInviteLink = async (invite: Invite) => {
    try {
      await navigator.clipboard.writeText(buildInviteLink(invite));
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
            <div className="h-3 w-40 rounded bg-white/[0.06] animate-pulse" />
            <div className="h-8 w-56 rounded bg-white/[0.06] animate-pulse" />
            <div className="h-3 w-72 rounded bg-white/[0.06] animate-pulse" />
          </div>
          <div className="hairline" />
          <div className="grid gap-4 md:grid-cols-[200px_1fr]">
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-9 rounded-lg bg-white/[0.04] animate-pulse" />
              ))}
            </div>
            <div className="space-y-4">
              {[1, 2].map((i) => (
                <div key={i} className="h-48 rounded-2xl bg-white/[0.04] animate-pulse" />
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
    ...(isAdmin
      ? [{ value: "activity" as TabValue, label: "Журнал", icon: ClipboardListIcon }]
      : []),
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
              className="hidden md:inline-flex items-center gap-1.5 text-[12px] t-48 hover:text-white transition-colors mb-2"
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
                  className={`nav-item ${isActive ? "active" : ""}`}
                  style={{ width: "100%", justifyContent: "flex-start" }}
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
                      className="relative flex size-14 shrink-0 items-center justify-center rounded-full text-[15px] font-medium text-black"
                      style={{ background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)" }}
                    >
                      {getInitials(profile?.full_name)}
                    </div>
                    <div className="space-y-0.5 min-w-0">
                      <p className="text-[15px] text-white truncate">
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
                        <GlassInput
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
                        <GlassInput
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
                        className="text-white capitalize"
                        style={{ fontSize: 18, fontWeight: 300 }}
                      >
                        {organization?.plan ?? "---"}
                      </span>
                    </div>
                  </div>
                  <div className="panel-flat p-4">
                    <div className="eyebrow mb-1">лиды в месяце</div>
                    <p
                      className="tnum text-white"
                      style={{ fontSize: 18, fontWeight: 300 }}
                    >
                      {organization?.leads_used_current_month ?? 0}
                      <span className="t-48 ml-1 text-[13px]">
                        / {organization?.leads_limit_per_month ?? 0}
                      </span>
                    </p>
                  </div>
                  <div className="panel-flat p-4">
                    <div className="eyebrow mb-1">пользователей</div>
                    <p
                      className="tnum text-white"
                      style={{ fontSize: 18, fontWeight: 300 }}
                    >
                      {organization?.users_limit ?? "---"}
                    </p>
                  </div>
                </div>

                <div className="hairline my-6" />

                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-[12px] t-72">
                    Смена тарифа выполняется через checkout на странице тарифов.
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
                                  className="flex size-8 shrink-0 items-center justify-center rounded-full text-[10px] mono text-black"
                                  style={{
                                    background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)",
                                  }}
                                >
                                  {getInitials(member.full_name)}
                                </div>
                                <div className="min-w-0">
                                  <p className="text-[13px] text-white truncate">
                                    {member.full_name}
                                  </p>
                                  <p className="text-[11px] mono t-48 truncate">
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
                                  <SelectTrigger size="sm" className="bg-white/[0.04] border-[var(--line-2)]">
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
                                        className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] mono t-72 hover:bg-white/[0.06] hover:t-100 transition-colors"
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
                              <GlassInput
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
                            {invites.map((invite) => (
                              <tr
                                key={invite.id}
                                className="border-b border-[var(--line)] last:border-0"
                              >
                                <td className="py-3 text-[13px] text-white">
                                  {invite.email}
                                </td>
                                <td className="py-3">
                                  <span className="inline-flex items-center gap-1.5 rounded-full panel-thin px-2.5 py-1 text-[11px] mono">
                                    <span
                                      className={`dot ${invite.accepted ? "dot-em" : "dot-am"}`}
                                    />
                                    {invite.accepted ? "принято" : "ожидает"}
                                  </span>
                                </td>
                                <td className="text-right py-3">
                                  <CopyButton onClick={() => copyInviteLink(invite)} />
                                </td>
                              </tr>
                            ))}
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
                    <GlassInput
                      placeholder="Токен приглашения"
                      value={inviteToken}
                      onChange={(e) => setInviteToken(e.target.value)}
                      required
                      className="sm:flex-1"
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
                              <span className="inline-flex items-center rounded-md panel-flat px-2 py-0.5 text-[11px] mono">
                                {item.action}
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
          </div>
        </div>
      </div>
    </main>
  );
}

function EmptyState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-white/[0.04] border border-[var(--line)] mb-3">
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
      <GlassInput
        type="url"
        placeholder="https://your-domain.bitrix24.ru/rest/1/xxx..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="sm:flex-1"
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

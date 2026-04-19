"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  ArrowLeftIcon,
  Building2Icon,
  CheckIcon,
  ClipboardListIcon,
  CopyIcon,
  MailIcon,
  PlusIcon,
  Trash2Icon,
  UserIcon,
  UsersIcon,
  CrownIcon,
  ShieldCheckIcon,
  ZapIcon,
  BarChart3Icon,
  UsersRoundIcon,
} from "lucide-react";
import { toast } from "sonner";
import { motion } from "framer-motion";

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
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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

const roleBadgeClasses: Record<string, string> = {
  owner: "bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-900/30 dark:text-purple-300 dark:border-purple-800",
  admin: "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800",
  member: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800/50 dark:text-gray-300 dark:border-gray-700",
};

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
    <Button
      variant="ghost"
      size="xs"
      onClick={() => void handleClick()}
      className="gap-1.5"
    >
      {copied ? (
        <CheckIcon className="size-3 text-emerald-500" />
      ) : (
        <CopyIcon className="size-3" />
      )}
      {copied ? "Скопировано" : "Скопировать"}
    </Button>
  );
}

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
  }, [authed]);

  const createInvite = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/organizations/invites", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: "member" })
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
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
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
        body: JSON.stringify({ role })
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
        body: JSON.stringify({ token: inviteToken })
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
      <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <div className="space-y-6">
          <div className="space-y-2">
            <div className="h-4 w-40 animate-pulse rounded-md bg-muted" />
            <div className="h-8 w-56 animate-pulse rounded-md bg-muted" />
            <div className="h-4 w-72 animate-pulse rounded-md bg-muted" />
          </div>
          <Separator />
          <div className="flex gap-8">
            <div className="hidden md:block w-[200px] space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-10 animate-pulse rounded-lg bg-muted" />
              ))}
            </div>
            <div className="flex-1 space-y-4">
              {[1, 2].map((i) => (
                <div key={i} className="h-48 animate-pulse rounded-xl bg-muted" />
              ))}
            </div>
          </div>
        </div>
      </main>
    );
  }

  const isAdmin = orgRole === "owner" || orgRole === "admin";

  const tabItems = [
    { value: "profile", label: "Профиль", icon: UserIcon },
    { value: "organization", label: "Организация", icon: Building2Icon },
    ...(isAdmin ? [{ value: "members", label: "Участники", icon: UsersIcon }] : []),
    { value: "invites", label: "Приглашения", icon: MailIcon },
    ...(isAdmin ? [{ value: "activity", label: "Журнал", icon: ClipboardListIcon }] : []),
  ];

  return (
    <motion.main
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8"
    >
      <div className="space-y-6">
        {/* ── Page Header ── */}
        <div className="space-y-4">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeftIcon className="size-4" />
            Назад на дашборд
          </Link>

          <div className="space-y-1">
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Настройки</h1>
            <p className="text-muted-foreground">
              Управление профилем, организацией и участниками
            </p>
          </div>
        </div>

        <Separator />

        {/* ── Tabs Layout ── */}
        <Tabs defaultValue="profile" orientation="vertical">
          <div className="flex flex-col md:flex-row gap-6 md:gap-8">
            {/* Sidebar tab list on desktop, horizontal scroll on mobile */}
            <TabsList
              variant="line"
              className="flex-row md:flex-col md:w-[200px] shrink-0 gap-0.5 overflow-x-auto md:overflow-visible pb-1 md:pb-0"
            >
              {tabItems.map((tab) => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  className="justify-start gap-2.5 px-3 py-2.5 rounded-md whitespace-nowrap"
                >
                  <tab.icon className="size-4 shrink-0 opacity-60" />
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>

            {/* Tab content area */}
            <div className="flex-1 min-w-0 max-w-3xl">
              {/* ── Profile ── */}
              <TabsContent value="profile" className="mt-0 space-y-6">
                <Card>
                  <CardHeader className="p-4 sm:p-6">
                    <CardTitle className="text-lg">Профиль пользователя</CardTitle>
                    <CardDescription>Информация о вашем аккаунте</CardDescription>
                  </CardHeader>
                  <CardContent className="p-4 sm:p-6 pt-0 space-y-6">
                    <div className="flex items-center gap-4">
                      <div className="relative flex size-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary/80 to-primary text-primary-foreground text-lg font-semibold shadow-sm">
                        {getInitials(profile?.full_name)}
                      </div>
                      <div className="space-y-0.5 min-w-0">
                        <p className="text-base font-semibold truncate">{profile?.full_name}</p>
                        <p className="text-sm text-muted-foreground truncate">{profile?.email}</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="p-4 sm:p-6">
                    <CardTitle className="text-lg">Смена пароля</CardTitle>
                    <CardDescription>Обновите пароль для вашего аккаунта</CardDescription>
                  </CardHeader>
                  <CardContent className="p-4 sm:p-6 pt-0">
                    <form onSubmit={changePassword} className="space-y-4">
                      <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-2">
                          <Label htmlFor="current-password">Текущий пароль</Label>
                          <Input
                            id="current-password"
                            type="password"
                            value={currentPassword}
                            placeholder="Введите текущий пароль"
                            onChange={(e) => setCurrentPassword(e.target.value)}
                            required
                            minLength={8}
                            aria-label="Текущий пароль"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="new-password">Новый пароль</Label>
                          <Input
                            id="new-password"
                            type="password"
                            value={newPassword}
                            placeholder="Минимум 8 символов"
                            onChange={(e) => setNewPassword(e.target.value)}
                            required
                            minLength={8}
                            aria-label="Новый пароль"
                          />
                        </div>
                      </div>
                      <div className="flex justify-end">
                        <Button type="submit" disabled={savingPassword}>
                          {savingPassword ? "Сохранение..." : "Сменить пароль"}
                        </Button>
                      </div>
                    </form>
                  </CardContent>
                </Card>
              </TabsContent>

              {/* ── Organization ── */}
              <TabsContent value="organization" className="mt-0 space-y-6">
                <Card>
                  <CardHeader className="p-4 sm:p-6">
                    <CardTitle className="text-lg">{organization?.name ?? "Организация"}</CardTitle>
                    <CardDescription>Настройки и лимиты вашей организации</CardDescription>
                  </CardHeader>
                  <CardContent className="p-4 sm:p-6 pt-0 space-y-6">
                    <div className="grid gap-4 sm:grid-cols-3">
                      <div className="flex items-start gap-3 rounded-xl border bg-muted/40 p-4">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <CrownIcon className="size-4" />
                        </div>
                        <div className="space-y-0.5 min-w-0">
                          <p className="text-xs font-medium text-muted-foreground">Тариф</p>
                          <p className="text-sm font-semibold capitalize">{organization?.plan ?? "---"}</p>
                        </div>
                      </div>
                      <div className="flex items-start gap-3 rounded-xl border bg-muted/40 p-4">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <BarChart3Icon className="size-4" />
                        </div>
                        <div className="space-y-0.5 min-w-0">
                          <p className="text-xs font-medium text-muted-foreground">Лиды в месяце</p>
                          <p className="text-sm font-semibold">
                            {organization?.leads_used_current_month ?? 0}
                            <span className="text-muted-foreground font-normal">
                              /{organization?.leads_limit_per_month ?? 0}
                            </span>
                          </p>
                        </div>
                      </div>
                      <div className="flex items-start gap-3 rounded-xl border bg-muted/40 p-4">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <UsersRoundIcon className="size-4" />
                        </div>
                        <div className="space-y-0.5 min-w-0">
                          <p className="text-xs font-medium text-muted-foreground">Лимит пользователей</p>
                          <p className="text-sm font-semibold">{organization?.users_limit ?? "---"}</p>
                        </div>
                      </div>
                    </div>

                    <Separator />

                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-sm text-muted-foreground">
                        Смена тарифа выполняется через checkout на странице тарифов.
                      </p>
                      <Link href="/plans" className="inline-flex shrink-0">
                        <Button>
                          <ZapIcon className="size-4" />
                          Открыть тарифы
                        </Button>
                      </Link>
                    </div>

                    <Separator />

                    {/* CRM webhook URL */}
                    {isAdmin && (
                      <div className="space-y-3">
                        <div>
                          <h3 className="text-sm font-semibold">CRM-интеграция (webhook)</h3>
                          <p className="mt-1 text-xs text-muted-foreground">
                            URL вашего Bitrix24 / AmoCRM / любого webhook-приёмника. Каждый новый лид (после обогащения) будет POST-иться сюда как JSON. Оставьте пустым чтобы отключить.
                          </p>
                        </div>
                        <WebhookEditor
                          currentUrl={(organization as Organization & { lead_webhook_url?: string } | null)?.lead_webhook_url ?? ""}
                          onSaved={(url) => setOrganization((o) => o ? { ...o, lead_webhook_url: url } as Organization & { lead_webhook_url: string } : o)}
                        />
                      </div>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>

              {/* ── Members ── */}
              {isAdmin && (
                <TabsContent value="members" className="mt-0 space-y-6">
                  <Card>
                    <CardHeader className="p-4 sm:p-6">
                      <CardTitle className="text-lg">Участники</CardTitle>
                      <CardDescription>Управление участниками и ролями организации</CardDescription>
                    </CardHeader>
                    <CardContent className="p-4 sm:p-6 pt-0">
                      {members.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-12 text-center">
                          <div className="flex size-12 items-center justify-center rounded-full bg-muted mb-3">
                            <UsersIcon className="size-5 text-muted-foreground" />
                          </div>
                          <p className="text-sm font-medium text-muted-foreground">
                            Участников пока нет.
                          </p>
                        </div>
                      ) : (
                        <div className="overflow-x-auto -mx-4 sm:-mx-6">
                          <div className="px-4 sm:px-6">
                            <Table>
                              <TableHeader>
                                <TableRow className="hover:bg-transparent">
                                  <TableHead className="font-semibold">Участник</TableHead>
                                  <TableHead className="font-semibold">Роль</TableHead>
                                  <TableHead className="text-right font-semibold">Действия</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {members.map((member) => (
                                  <TableRow key={member.user_id} className="group">
                                    <TableCell className="py-3">
                                      <div className="flex items-center gap-3">
                                        <Avatar size="sm">
                                          <AvatarFallback className="text-[10px]">
                                            {getInitials(member.full_name)}
                                          </AvatarFallback>
                                        </Avatar>
                                        <div className="min-w-0">
                                          <p className="font-medium text-sm truncate">{member.full_name}</p>
                                          <p className="text-xs text-muted-foreground truncate">
                                            {member.email}
                                          </p>
                                        </div>
                                      </div>
                                    </TableCell>
                                    <TableCell className="py-3">
                                      {orgRole === "owner" && member.email !== profile?.email ? (
                                        <Select
                                          value={member.role}
                                          onValueChange={(val) =>
                                            updateMemberRole(member.user_id, val as Member["role"])
                                          }
                                        >
                                          <SelectTrigger size="sm">
                                            <SelectValue />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="member">member</SelectItem>
                                            <SelectItem value="admin">admin</SelectItem>
                                            <SelectItem value="owner">owner</SelectItem>
                                          </SelectContent>
                                        </Select>
                                      ) : (
                                        <Badge
                                          className={roleBadgeClasses[member.role] ?? roleBadgeClasses.member}
                                        >
                                          {member.role === "owner" && <ShieldCheckIcon className="size-3" />}
                                          {member.role}
                                        </Badge>
                                      )}
                                    </TableCell>
                                    <TableCell className="text-right py-3">
                                      {member.email !== profile?.email && orgRole === "owner" && (
                                        <AlertDialog>
                                          <AlertDialogTrigger
                                            render={
                                              <Button
                                                variant="ghost"
                                                size="xs"
                                                className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                              >
                                                <Trash2Icon className="size-3" />
                                                Удалить
                                              </Button>
                                            }
                                          />
                                          <AlertDialogContent>
                                            <AlertDialogHeader>
                                              <AlertDialogTitle>Удалить участника?</AlertDialogTitle>
                                              <AlertDialogDescription>
                                                {member.full_name} ({member.email}) будет удалён из
                                                организации. Это действие нельзя отменить.
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
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>
              )}

              {/* ── Invites ── */}
              <TabsContent value="invites" className="mt-0 space-y-6">
                {isAdmin && (
                  <Card>
                    <CardHeader className="p-4 sm:p-6 flex flex-col sm:flex-row items-start justify-between gap-4">
                      <div className="space-y-1">
                        <CardTitle className="text-lg">Приглашения</CardTitle>
                        <CardDescription>Управление приглашениями в организацию</CardDescription>
                      </div>
                      <Dialog>
                        <DialogTrigger
                          render={
                            <Button size="sm" className="shrink-0">
                              <PlusIcon className="size-4" />
                              Пригласить
                            </Button>
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
                            <div className="space-y-2">
                              <Label htmlFor="invite-email">Email</Label>
                              <Input
                                id="invite-email"
                                type="email"
                                value={inviteEmail}
                                placeholder="коллега@company.com"
                                onChange={(e) => setInviteEmail(e.target.value)}
                                required
                              />
                            </div>
                            <DialogFooter>
                              <DialogClose render={<Button variant="outline" />}>
                                Отмена
                              </DialogClose>
                              <Button type="submit">Создать приглашение</Button>
                            </DialogFooter>
                          </form>
                        </DialogContent>
                      </Dialog>
                    </CardHeader>
                    <CardContent className="p-4 sm:p-6 pt-0">
                      {invites.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-12 text-center">
                          <div className="flex size-12 items-center justify-center rounded-full bg-muted mb-3">
                            <MailIcon className="size-5 text-muted-foreground" />
                          </div>
                          <p className="text-sm font-medium text-muted-foreground">
                            Приглашений пока нет.
                          </p>
                        </div>
                      ) : (
                        <div className="overflow-x-auto -mx-4 sm:-mx-6">
                          <div className="px-4 sm:px-6">
                            <Table>
                              <TableHeader>
                                <TableRow className="hover:bg-transparent">
                                  <TableHead className="font-semibold">Email</TableHead>
                                  <TableHead className="font-semibold">Статус</TableHead>
                                  <TableHead className="text-right font-semibold">Действия</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {invites.map((invite) => (
                                  <TableRow key={invite.id}>
                                    <TableCell className="py-3">
                                      <span className="font-medium text-sm">{invite.email}</span>
                                    </TableCell>
                                    <TableCell className="py-3">
                                      <Badge
                                        variant={invite.accepted ? "default" : "outline"}
                                        className={
                                          invite.accepted
                                            ? "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800"
                                            : ""
                                        }
                                      >
                                        {invite.accepted ? "Принято" : "Ожидает"}
                                      </Badge>
                                    </TableCell>
                                    <TableCell className="text-right py-3">
                                      <CopyButton onClick={() => copyInviteLink(invite)} />
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}

                {!isAdmin && (
                  <Card>
                    <CardHeader className="p-4 sm:p-6">
                      <CardTitle className="text-lg">Приглашения</CardTitle>
                      <CardDescription>Список приглашений доступен только owner/admin.</CardDescription>
                    </CardHeader>
                  </Card>
                )}

                <Card>
                  <CardHeader className="p-4 sm:p-6">
                    <CardTitle className="text-lg">Принять приглашение</CardTitle>
                    <CardDescription>Введите токен, чтобы присоединиться к организации</CardDescription>
                  </CardHeader>
                  <CardContent className="p-4 sm:p-6 pt-0">
                    <form onSubmit={acceptInvite} className="flex flex-col gap-3 sm:flex-row">
                      <Input
                        placeholder="Токен приглашения"
                        value={inviteToken}
                        onChange={(e) => setInviteToken(e.target.value)}
                        required
                        className="flex-1"
                      />
                      <Button variant="secondary" type="submit" className="shrink-0">
                        <UserIcon className="size-4" />
                        Принять приглашение
                      </Button>
                    </form>
                  </CardContent>
                </Card>
              </TabsContent>

              {/* ── Activity Log ── */}
              {isAdmin && (
                <TabsContent value="activity" className="mt-0 space-y-6">
                  <Card>
                    <CardHeader className="p-4 sm:p-6">
                      <CardTitle className="text-lg">Журнал действий</CardTitle>
                      <CardDescription>Последние действия в организации</CardDescription>
                    </CardHeader>
                    <CardContent className="p-4 sm:p-6 pt-0">
                      {actions.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-12 text-center">
                          <div className="flex size-12 items-center justify-center rounded-full bg-muted mb-3">
                            <ClipboardListIcon className="size-5 text-muted-foreground" />
                          </div>
                          <p className="text-sm font-medium text-muted-foreground">
                            Записей пока нет.
                          </p>
                        </div>
                      ) : (
                        <div className="overflow-x-auto -mx-4 sm:-mx-6">
                          <div className="px-4 sm:px-6">
                            <Table>
                              <TableHeader>
                                <TableRow className="hover:bg-transparent">
                                  <TableHead className="font-semibold">Действие</TableHead>
                                  <TableHead className="text-right font-semibold">Дата</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {actions.map((item, idx) => (
                                  <TableRow
                                    key={item.id}
                                    className={idx % 2 === 0 ? "bg-muted/30" : ""}
                                  >
                                    <TableCell className="py-3">
                                      <Badge variant="secondary" className="font-mono text-xs">
                                        {item.action}
                                      </Badge>
                                    </TableCell>
                                    <TableCell className="text-right py-3">
                                      <span className="text-xs text-muted-foreground">
                                        {new Date(item.created_at).toLocaleString("ru-RU")}
                                      </span>
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>
              )}
            </div>
          </div>
        </Tabs>
      </div>
    </motion.main>
  );
}


function WebhookEditor({ currentUrl, onSaved }: { currentUrl: string; onSaved: (url: string) => void }) {
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
      <Input
        type="url"
        placeholder="https://your-domain.bitrix24.ru/rest/1/xxx..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="sm:flex-1"
      />
      <Button onClick={save} disabled={saving || !dirty}>
        {saving ? "Сохранение…" : "Сохранить"}
      </Button>
    </div>
  );
}

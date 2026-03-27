"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";
import { setOrgId, setToken } from "@/lib/auth";
import type { Organization } from "@/lib/types";

type RegisterResponse = {
  access_token: string;
  refresh_token: string;
  message?: string | null;
  email_verification_required?: boolean;
};

function RegisterContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteToken = searchParams.get("invite_token") ?? "";
  const invitedEmail = searchParams.get("email") ?? "";
  const loginHref = useMemo(() => {
    const raw = searchParams.toString();
    return (raw ? `/login?${raw}` : "/login") as "/login";
  }, [searchParams]);
  const querySuffix = useMemo(() => {
    const raw = searchParams.toString();
    return raw ? `?${raw}` : "";
  }, [searchParams]);

  const [form, setForm] = useState({
    full_name: "",
    organization_name: "",
    email: "",
    password: "",
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (invitedEmail) {
      setForm((current) => ({ ...current, email: current.email || invitedEmail }));
    }
  }, [invitedEmail]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await api<RegisterResponse>("/auth/register", {
        method: "POST",
        body: JSON.stringify(form),
      });

      if (data.email_verification_required) {
        toast.success(data.message ?? "Аккаунт создан. Подтвердите email, затем войдите.");
        if (typeof window !== "undefined") {
          window.location.assign(`/login${querySuffix}`);
        } else {
          router.push("/login");
        }
        return;
      }

      setToken(data.access_token);
      if (inviteToken) {
        try {
          const joined = await api<Organization>("/organizations/invites/accept", {
            method: "POST",
            body: JSON.stringify({ token: inviteToken }),
          });
          setOrgId(joined.id);
          toast.success(`Аккаунт создан. Вы присоединились к организации ${joined.name}`);
        } catch (error) {
          toast.error(error instanceof Error ? error.message : "Аккаунт создан, но приглашение не применилось");
        }
      } else {
        toast.success(data.message ?? "Аккаунт создан");
      }

      router.push("/dashboard");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось зарегистрироваться");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 px-4 py-12">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mb-2 text-3xl font-bold tracking-tight">БАЗА</div>
          <CardTitle className="text-xl">Создание аккаунта</CardTitle>
          <CardDescription>
            Заполните форму для регистрации в системе
          </CardDescription>
        </CardHeader>

        {inviteToken && (
          <CardContent>
            <p className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark:border-blue-900/40 dark:bg-blue-900/20 dark:text-blue-200">
              Создайте аккаунт, и приглашение в организацию применится автоматически.
            </p>
          </CardContent>
        )}

        <CardContent>
          <form id="register-form" onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="full_name">Полное имя</Label>
              <Input
                id="full_name"
                placeholder="Иван Иванов"
                value={form.full_name}
                onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
                required
                minLength={2}
                maxLength={120}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="organization_name">Организация</Label>
              <Input
                id="organization_name"
                placeholder="Название организации"
                value={form.organization_name}
                onChange={(e) => setForm((p) => ({ ...p, organization_name: e.target.value }))}
                required
                minLength={2}
                maxLength={120}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                placeholder="name@example.com"
                type="email"
                value={form.email}
                onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Пароль</Label>
              <Input
                id="password"
                placeholder="Минимум 8 символов"
                type="password"
                minLength={8}
                maxLength={128}
                value={form.password}
                onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
                required
              />
              {form.password.length > 0 && form.password.length < 8 && (
                <p className="text-xs text-destructive">
                  Минимум 8 символов ({8 - form.password.length} ещё)
                </p>
              )}
            </div>

            <Button type="submit" className="w-full" size="lg" disabled={loading}>
              {loading ? "Создаём..." : "Зарегистрироваться"}
            </Button>
          </form>
        </CardContent>

        <CardFooter className="flex-col gap-3">
          <Separator />
          <p className="text-sm text-muted-foreground">
            Уже есть аккаунт?{" "}
            <Link
              href={loginHref}
              className="font-medium text-foreground underline underline-offset-4 hover:text-primary"
            >
              Войти
            </Link>
          </p>
        </CardFooter>
      </Card>
    </main>
  );
}

export default function RegisterPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-muted/40 px-4 py-12">
          <Card className="w-full max-w-md">
            <CardContent className="py-12 text-center text-muted-foreground">
              Загрузка...
            </CardContent>
          </Card>
        </main>
      }
    >
      <RegisterContent />
    </Suspense>
  );
}

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

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteToken = searchParams.get("invite_token") ?? "";
  const invitedEmail = searchParams.get("email") ?? "";
  const registerHref = useMemo(() => {
    const raw = searchParams.toString();
    return (raw ? `/register?${raw}` : "/register") as "/register";
  }, [searchParams]);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (invitedEmail) {
      setEmail((current) => current || invitedEmail);
    }
  }, [invitedEmail]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(data.access_token);

      if (inviteToken) {
        try {
          const joined = await api<Organization>("/organizations/invites/accept", {
            method: "POST",
            body: JSON.stringify({ token: inviteToken }),
          });
          setOrgId(joined.id);
          toast.success(`Вы вошли и присоединились к организации ${joined.name}`);
        } catch (error) {
          toast.error(error instanceof Error ? error.message : "Войти удалось, но принять приглашение не получилось");
        }
      } else {
        toast.success("Вы успешно вошли");
      }

      router.push("/dashboard");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось войти");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      {/* Animated gradient mesh */}
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden="true">
        <div className="absolute inset-0 bg-gradient-to-br from-violet-50 via-background to-sky-50 dark:from-violet-950/20 dark:via-background dark:to-sky-950/20" />
        <div className="absolute top-0 left-1/4 h-[500px] w-[500px] rounded-full bg-violet-200/30 blur-[100px] dark:bg-violet-800/10 animate-[aurora-1_15s_ease-in-out_infinite]" />
        <div className="absolute bottom-0 right-1/4 h-[400px] w-[400px] rounded-full bg-sky-200/30 blur-[100px] dark:bg-sky-800/10 animate-[aurora-2_20s_ease-in-out_infinite]" />
      </div>
      <Card className="w-full max-w-md p-4 sm:p-6 shadow-2xl shadow-black/20">
        <CardHeader className="text-center">
          <div className="mb-2 text-2xl sm:text-3xl font-bold tracking-tight"><span className="bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">БАЗА</span></div>
          <CardTitle className="text-lg sm:text-xl">Вход в аккаунт</CardTitle>
          <CardDescription>
            Введите свои данные для входа в систему
          </CardDescription>
        </CardHeader>

        {inviteToken && (
          <CardContent>
            <p className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark:border-blue-900/40 dark:bg-blue-900/20 dark:text-blue-200">
              После входа приглашение в организацию применится автоматически.
            </p>
          </CardContent>
        )}

        <CardContent>
          <form id="login-form" onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                placeholder="name@example.com"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Пароль</Label>
                <Link
                  href="/forgot-password"
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  Забыли пароль?
                </Link>
              </div>
              <Input
                id="password"
                placeholder="Введите пароль"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            <Button type="submit" className="w-full bg-violet-600 hover:bg-violet-500 text-white" size="lg" disabled={loading}>
              {loading ? "Входим..." : "Войти"}
            </Button>
          </form>
        </CardContent>

        <CardFooter className="flex-col gap-3">
          <Separator />
          <p className="text-sm text-muted-foreground">
            Нет аккаунта?{" "}
            <Link
              href={registerHref}
              className="font-medium text-foreground underline underline-offset-4 hover:text-primary"
            >
              Зарегистрироваться
            </Link>
          </p>
        </CardFooter>
      </Card>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
          {/* Animated gradient mesh */}
          <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden="true">
            <div className="absolute inset-0 bg-gradient-to-br from-violet-50 via-background to-sky-50 dark:from-violet-950/20 dark:via-background dark:to-sky-950/20" />
            <div className="absolute top-0 left-1/4 h-[500px] w-[500px] rounded-full bg-violet-200/30 blur-[100px] dark:bg-violet-800/10 animate-[aurora-1_15s_ease-in-out_infinite]" />
            <div className="absolute bottom-0 right-1/4 h-[400px] w-[400px] rounded-full bg-sky-200/30 blur-[100px] dark:bg-sky-800/10 animate-[aurora-2_20s_ease-in-out_infinite]" />
          </div>
          <Card className="w-full max-w-md p-4 sm:p-6">
            <CardContent className="py-12 text-center text-muted-foreground">
              Загрузка...
            </CardContent>
          </Card>
        </main>
      }
    >
      <LoginContent />
    </Suspense>
  );
}

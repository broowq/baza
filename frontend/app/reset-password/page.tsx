"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
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

function ResetPasswordContent() {
  const search = useSearchParams();
  const router = useRouter();
  const token = search.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api<{ message: string }>("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password })
      });
      toast.success("Пароль обновлён, войдите с новым паролем");
      setPassword("");
      setTimeout(() => router.push("/login"), 2000);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить пароль");
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
      <Card className="w-full max-w-md p-4 sm:p-6">
        <CardHeader className="text-center">
          <div className="mb-2 text-2xl sm:text-3xl font-bold tracking-tight">БАЗА</div>
          <CardTitle className="text-lg sm:text-xl">Сброс пароля</CardTitle>
          <CardDescription>
            Придумайте новый надёжный пароль для вашего аккаунта
          </CardDescription>
        </CardHeader>

        <CardContent>
          <form id="reset-password-form" onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="password">Новый пароль</Label>
              <Input
                id="password"
                placeholder="Минимум 8 символов"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={8}
                required
              />
            </div>

            <Button className="w-full" size="lg" disabled={!token || loading}>
              {loading ? "Сохраняем..." : "Сменить пароль"}
            </Button>
          </form>
        </CardContent>

        <CardFooter className="flex-col gap-3">
          <Separator />
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            &larr; Вернуться к входу
          </Link>
        </CardFooter>
      </Card>
    </main>
  );
}

export default function ResetPasswordPage() {
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
      <ResetPasswordContent />
    </Suspense>
  );
}

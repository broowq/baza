"use client";

import { FormEvent, useState } from "react";
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

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const response = await api<{ message: string; preview_url?: string | null }>("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email })
      });
      toast.success(response.message);
      setPreviewUrl(response.preview_url ?? "");
      setSent(true);
      setEmail("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось отправить ссылку");
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
          <CardTitle className="text-lg sm:text-xl">Восстановление пароля</CardTitle>
          <CardDescription>
            Введите email и мы отправим ссылку для сброса пароля
          </CardDescription>
        </CardHeader>

        <CardContent>
          <form id="forgot-password-form" onSubmit={submit} className="space-y-4">
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

            <Button className="w-full" size="lg" disabled={loading}>
              {loading ? "Отправляем..." : "Отправить ссылку"}
            </Button>

            {sent && (
              <p className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark:border-green-900/40 dark:bg-green-900/20 dark:text-green-200">
                Если аккаунт существует, мы отправили ссылку для сброса.
              </p>
            )}

            {previewUrl ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200">
                Тестовая ссылка для dev:{" "}
                <a href={previewUrl} className="font-medium underline underline-offset-2">
                  открыть сброс пароля
                </a>
              </div>
            ) : null}
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

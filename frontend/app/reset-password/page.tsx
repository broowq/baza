"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { EyeIcon } from "@/components/ui/eye-icon";

function ResetPasswordContent() {
  const search = useSearchParams();
  const router = useRouter();
  const token = search.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!done) return;
    const id = setTimeout(() => router.push("/login"), 2000);
    return () => clearTimeout(id);
  }, [done, router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api<{ message: string }>("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password }),
      });
      toast.success("Пароль обновлён, войдите с новым паролем");
      setDone(true);
      setPassword("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось обновить пароль");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      <div className="canvas-bg" />
      <div className="grain" />

      <div className="relative z-10 w-full max-w-[460px]">
        <Link href="/" className="mb-10 flex items-center justify-center gap-2.5">
          <span className="avatar" style={{ width: 32, height: 32, fontSize: 14, borderRadius: 9 }}>Б</span>
          <span className="text-[16px]" style={{ fontWeight: 500 }}>база</span>
        </Link>

        <div className="panel" style={{ padding: 40 }}>
          <div className="eyebrow mb-3">сброс пароля</div>
          <h2 className="h2">Новый пароль.</h2>
          <p className="caption mt-2">Придумайте новый надёжный пароль для вашего аккаунта.</p>

          {!token ? (
            <div className="mt-7 flex flex-col gap-4">
              <div className="panel-flat px-3 py-2.5 text-[13px] t-72">
                Ссылка для сброса недействительна или истекла.
              </div>
              <Link
                href="/forgot-password"
                className="btn btn-ghost w-full text-center"
                style={{ height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}
              >
                Запросить новую ссылку
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="mt-7 flex flex-col gap-4">
              <div>
                <label htmlFor="password" className="eyebrow mb-2" style={{ fontSize: 10, display: "block" }}>новый пароль</label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="минимум 8 символов"
                    minLength={8}
                    maxLength={128}
                    required
                    autoComplete="new-password"
                    className="input"
                    style={{ paddingRight: 40 }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 t-56 hover:text-white"
                    aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                  >
                    <EyeIcon open={showPassword} />
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading || done || !token}
                className="btn btn-brand w-full mt-2"
                style={{ height: 44 }}
              >
                {loading ? "Сохраняем…" : "Сменить пароль"}
                {!loading && (
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <path d="M5 12h14M13 5l7 7-7 7" />
                  </svg>
                )}
              </button>
            </form>
          )}

          <div className="hairline my-7" />

          <div className="text-center caption">
            <Link href="/login" className="text-white underline underline-offset-4" style={{ textDecorationColor: "var(--t-40)" }}>
              ← Вернуться к входу
            </Link>
          </div>
        </div>

        <p className="mt-6 text-center mono-cap" style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--t-40)" }}>
          © 2026 БАЗА · USEBAZA.RU · ХРАНЕНИЕ ДАННЫХ В РФ
        </p>
      </div>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
          <div className="canvas-bg" />
          <div className="panel p-7 w-full max-w-[460px] text-center t-48 text-[13px]">
            Загрузка…
          </div>
        </main>
      }
    >
      <ResetPasswordContent />
    </Suspense>
  );
}

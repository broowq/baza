"use client";

import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { setOrgId, setToken } from "@/lib/auth";
import type { Organization } from "@/lib/types";
import { EyeIcon } from "@/components/ui/eye-icon";

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteToken = searchParams.get("invite_token") ?? "";
  const invitedEmail = searchParams.get("email") ?? "";
  // Пришёл с /plans с выбранным тарифом → после входа вернём на оплату.
  const pendingPlan = searchParams.get("plan") ?? "";
  const registerHref = useMemo(() => {
    const raw = searchParams.toString();
    return (raw ? `/register?${raw}` : "/register") as "/register";
  }, [searchParams]);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState("");
  const [needsVerification, setNeedsVerification] = useState(false);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (invitedEmail) setEmail((current) => current || invitedEmail);
  }, [invitedEmail]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    setNeedsVerification(false);
    setLoading(true);
    try {
      const data = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, remember_me: rememberMe }),
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

      router.push(pendingPlan ? (`/plans?plan=${encodeURIComponent(pendingPlan)}` as Route) : "/dashboard");
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Не удалось войти";
      setFormError(msg);
      setNeedsVerification(msg.includes("Подтвердите email"));
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const resendVerification = async () => {
    setResending(true);
    try {
      const response = await api<{ message: string }>("/auth/resend-verification", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      toast.success(response.message ?? "Письмо отправлено, проверьте почту");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось отправить письмо");
    } finally {
      setResending(false);
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

        <div className="panel p-6 sm:p-10">
          <div className="eyebrow mb-3">вход в аккаунт</div>
          <h2 className="h2">С возвращением.</h2>
          <p className="caption mt-2">Введите свои данные для входа в систему.</p>

          {inviteToken && (
            <div className="mt-5 panel-flat px-3 py-2.5 text-[12px] t-72">
              После входа приглашение в организацию применится автоматически.
            </div>
          )}

          <form onSubmit={onSubmit} className="mt-7 flex flex-col gap-4" noValidate>
            <div>
              <label htmlFor="email" className="eyebrow mb-2" style={{ fontSize: 10, display: "block" }}>email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.ru"
                required
                autoComplete="email"
                className="input"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <label htmlFor="password" className="eyebrow" style={{ fontSize: 10, display: "block" }}>пароль</label>
                <Link href="/forgot-password" className="mono-cap t-56 hover:text-[var(--t-100)]" style={{ fontSize: "10.5px" }}>
                  забыли пароль?
                </Link>
              </div>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••"
                  required
                  autoComplete="current-password"
                  className="input"
                  style={{ paddingRight: 44 }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-0.5 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center t-56 hover:text-[var(--t-100)]"
                  aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                >
                  <EyeIcon open={showPassword} />
                </button>
              </div>
            </div>

            <label className="flex min-h-10 sm:min-h-0 items-center gap-2.5 cursor-pointer select-none -mt-1">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="size-[18px] sm:size-4 shrink-0 accent-[var(--mint)]"
              />
              <span className="text-[12.5px] t-72">
                Запомнить меня
                <span className="t-40"> — не выходить 30 дней</span>
              </span>
            </label>

            {formError && (
              <div role="alert" aria-live="assertive" className="panel-flat px-3 py-2.5 text-[12px]" style={{ color: "var(--rose)" }}>
                {formError}
              </div>
            )}

            {needsVerification && (
              <button
                type="button"
                onClick={resendVerification}
                disabled={resending}
                className="btn btn-ghost w-full"
                style={{ height: 40 }}
              >
                {resending ? "Отправляем…" : "Отправить письмо ещё раз"}
              </button>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn btn-brand w-full mt-2"
              style={{ height: 44 }}
            >
              {loading ? "Входим…" : "Войти"}
              {!loading && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M5 12h14M13 5l7 7-7 7" />
                </svg>
              )}
            </button>
          </form>

          <div className="hairline my-7" />

          <div className="text-center caption">
            Нет аккаунта?{" "}
            <Link href={registerHref} className="text-[var(--t-100)] underline underline-offset-4" style={{ textDecorationColor: "var(--t-40)" }}>
              Зарегистрироваться
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

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
          <div className="canvas-bg" />
          <div className="panel p-7 w-full max-w-[420px] text-center t-48 text-[13px]">
            Загрузка…
          </div>
        </main>
      }
    >
      <LoginContent />
    </Suspense>
  );
}

"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

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
    if (invitedEmail) setEmail((current) => current || invitedEmail);
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
      <div className="canvas-bg" />
      <div className="grain" />

      <div className="relative z-10 w-full max-w-[460px]">
        <Link href="/" className="mb-10 flex items-center justify-center gap-2.5">
          <span className="avatar" style={{ width: 32, height: 32, fontSize: 14, borderRadius: 9 }}>Б</span>
          <span className="text-[16px]" style={{ fontWeight: 500 }}>база</span>
        </Link>

        <div className="panel" style={{ padding: 40 }}>
          <div className="eyebrow mb-3">вход в аккаунт</div>
          <h2 className="h2">С возвращением.</h2>
          <p className="caption mt-2">Введите свои данные для входа в систему.</p>

          {inviteToken && (
            <div className="mt-5 panel-flat px-3 py-2.5 text-[12px] t-72">
              После входа приглашение в организацию применится автоматически.
            </div>
          )}

          <form onSubmit={onSubmit} className="mt-7 flex flex-col gap-4">
            <div>
              <div className="eyebrow mb-2" style={{ fontSize: 10 }}>email</div>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.ru"
                required
                className="input"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="eyebrow" style={{ fontSize: 10 }}>пароль</div>
                <Link href="/forgot-password" className="mono-cap t-56 hover:text-white" style={{ fontSize: "10.5px" }}>
                  забыли пароль?
                </Link>
              </div>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••"
                required
                className="input"
              />
            </div>

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
            <Link href={registerHref} className="text-white underline underline-offset-4" style={{ textDecorationColor: "var(--t-40)" }}>
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

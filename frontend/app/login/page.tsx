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
      <div className="field" />
      <div className="grid-lines" />
      <div className="grain" />

      <div className="relative z-10 w-full max-w-[420px]">
        <Link href="/" className="mb-8 flex items-center justify-center gap-2">
          <span
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M4 6 L12 3 L20 6 L20 18 L12 21 L4 18 Z" stroke="black" strokeWidth="1.6" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="text-[15px]" style={{ fontWeight: 500 }}>база</span>
        </Link>

        <div className="panel p-7">
          <div className="eyebrow mb-2">вход в аккаунт</div>
          <h1 className="h2 mb-1" style={{ fontSize: 32 }}>С возвращением.</h1>
          <p className="text-[13px] t-72 mb-6">
            Введите свои данные для входа в систему.
          </p>

          {inviteToken && (
            <div className="mb-5 panel-flat p-3 text-[12px] t-72">
              После входа приглашение в организацию применится автоматически.
            </div>
          )}

          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="email" className="eyebrow">email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                required
                className="w-full h-11 rounded-2xl border border-[var(--line-2)] bg-white/[0.04] px-4 text-[14px] text-white placeholder:text-white/40 outline-none focus:border-white/[0.24] focus:bg-white/[0.07] backdrop-blur-xl transition-colors"
              />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="password" className="eyebrow">пароль</label>
                <Link href="/forgot-password" className="text-[11px] t-48 hover:text-white">
                  забыли пароль?
                </Link>
              </div>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Введите пароль"
                required
                className="w-full h-11 rounded-2xl border border-[var(--line-2)] bg-white/[0.04] px-4 text-[14px] text-white placeholder:text-white/40 outline-none focus:border-white/[0.24] focus:bg-white/[0.07] backdrop-blur-xl transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="brand w-full rounded-full px-5 py-3 text-[13.5px] flex items-center justify-center gap-2 disabled:opacity-60 disabled:pointer-events-none"
            >
              {loading ? "Входим…" : "Войти"}
              {!loading && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              )}
            </button>
          </form>

          <div className="hairline mt-7 pt-5 text-center">
            <p className="text-[13px] t-72">
              Нет аккаунта?{" "}
              <Link href={registerHref} className="text-white underline underline-offset-4">
                Зарегистрироваться
              </Link>
            </p>
          </div>
        </div>

        <p className="mt-6 text-center text-[11px] t-40">
          © 2026 База · usebaza.ru
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
          <div className="field" />
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

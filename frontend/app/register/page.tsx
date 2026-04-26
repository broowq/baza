"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { setOrgId, setToken } from "@/lib/auth";
import type { Organization } from "@/lib/types";

type RegisterResponse = {
  access_token: string;
  refresh_token: string;
  message?: string | null;
  email_verification_required?: boolean;
};

function GlassInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={
        "w-full h-11 rounded-2xl border border-[var(--line-2)] bg-white/[0.04] px-4 text-[14px] text-white placeholder:text-white/40 outline-none focus:border-white/[0.24] focus:bg-white/[0.07] backdrop-blur-xl transition-colors " +
        (props.className ?? "")
      }
    />
  );
}

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
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [acceptedPrivacy, setAcceptedPrivacy] = useState(false);

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
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      <div className="field" />
      <div className="grid-lines" />
      <div className="grain" />

      <div className="relative z-10 w-full max-w-[460px]">
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
          <div className="eyebrow mb-2">создание аккаунта</div>
          <h1 className="h2 mb-1" style={{ fontSize: 32 }}>Начнём с первых лидов.</h1>
          <p className="text-[13px] t-72 mb-6">
            Бесплатные первые 100 — без карты.
          </p>

          {inviteToken && (
            <div className="mb-5 panel-flat p-3 text-[12px] t-72">
              Создайте аккаунт, и приглашение в организацию применится автоматически.
            </div>
          )}

          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="full_name" className="eyebrow">полное имя</label>
              <GlassInput
                id="full_name"
                placeholder="Иван Иванов"
                value={form.full_name}
                onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
                required minLength={2} maxLength={120}
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="organization_name" className="eyebrow">организация</label>
              <GlassInput
                id="organization_name"
                placeholder="Название организации"
                value={form.organization_name}
                onChange={(e) => setForm((p) => ({ ...p, organization_name: e.target.value }))}
                required minLength={2} maxLength={120}
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="email" className="eyebrow">email</label>
              <GlassInput
                id="email"
                type="email"
                placeholder="name@example.com"
                value={form.email}
                onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className="eyebrow">пароль</label>
              <GlassInput
                id="password"
                type="password"
                placeholder="Минимум 8 символов"
                minLength={8} maxLength={128}
                value={form.password}
                onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
                required
              />
              {form.password.length > 0 && form.password.length < 8 && (
                <p className="text-[11px] mono" style={{ color: "var(--rose)" }}>
                  Минимум 8 символов ({8 - form.password.length} ещё)
                </p>
              )}
            </div>

            <div className="space-y-3 panel-flat p-4">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={acceptedTerms}
                  onChange={(e) => setAcceptedTerms(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded accent-white"
                  style={{ accentColor: "#fff" }}
                  required
                />
                <span className="text-[12px] leading-[1.5] t-72">
                  Я принимаю{" "}
                  <Link href="/terms" target="_blank" className="text-white underline underline-offset-2">
                    Условия использования
                  </Link>{" "}
                  и{" "}
                  <Link href="/privacy" target="_blank" className="text-white underline underline-offset-2">
                    Политику конфиденциальности
                  </Link>
                </span>
              </label>
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={acceptedPrivacy}
                  onChange={(e) => setAcceptedPrivacy(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded accent-white"
                  style={{ accentColor: "#fff" }}
                  required
                />
                <span className="text-[12px] leading-[1.5] t-72">
                  Даю согласие на обработку персональных данных в соответствии с{" "}
                  <Link href="/privacy" target="_blank" className="text-white underline underline-offset-2">
                    152-ФЗ
                  </Link>
                </span>
              </label>
            </div>

            <button
              type="submit"
              disabled={loading || !acceptedTerms || !acceptedPrivacy}
              className="brand w-full rounded-full px-5 py-3 text-[13.5px] flex items-center justify-center gap-2 disabled:opacity-50 disabled:pointer-events-none"
            >
              {loading ? "Создаём…" : "Зарегистрироваться"}
              {!loading && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              )}
            </button>
          </form>

          <div className="hairline mt-7 pt-5 text-center">
            <p className="text-[13px] t-72">
              Уже есть аккаунт?{" "}
              <Link href={loginHref} className="text-white underline underline-offset-4">
                Войти
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

export default function RegisterPage() {
  return (
    <Suspense
      fallback={
        <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
          <div className="field" />
          <div className="panel p-7 w-full max-w-[460px] text-center t-48 text-[13px]">
            Загрузка…
          </div>
        </main>
      }
    >
      <RegisterContent />
    </Suspense>
  );
}

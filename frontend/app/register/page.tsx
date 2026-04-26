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
  return <input {...props} className={"input " + (props.className ?? "")} />;
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
      <div className="canvas-bg" />
      <div className="grain" />

      <div className="relative z-10 w-full max-w-[460px]">
        <Link href="/" className="mb-10 flex items-center justify-center gap-2.5">
          <span className="avatar" style={{ width: 32, height: 32, fontSize: 14, borderRadius: 9 }}>Б</span>
          <span className="text-[16px]" style={{ fontWeight: 500 }}>база</span>
        </Link>

        <div className="panel" style={{ padding: 40 }}>
          <div className="eyebrow mb-3">создание аккаунта</div>
          <h2 className="h2">Начнём с первых лидов.</h2>
          <p className="caption mt-2">
            Бесплатные первые 100 — без карты, без обязательств.
          </p>

          {inviteToken && (
            <div className="mb-5 panel-flat p-3 text-[12px] t-72">
              Создайте аккаунт, и приглашение в организацию применится автоматически.
            </div>
          )}

          <form onSubmit={onSubmit} className="mt-7 flex flex-col gap-3.5">
            <div>
              <div className="eyebrow mb-2" style={{ fontSize: 10 }}>имя</div>
              <GlassInput
                id="full_name"
                placeholder="Михаил Кудрявцев"
                value={form.full_name}
                onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
                required minLength={2} maxLength={120}
              />
            </div>

            <div>
              <div className="eyebrow mb-2" style={{ fontSize: 10 }}>организация</div>
              <GlassInput
                id="organization_name"
                placeholder="ООО «Кедр-Сибирь»"
                value={form.organization_name}
                onChange={(e) => setForm((p) => ({ ...p, organization_name: e.target.value }))}
                required minLength={2} maxLength={120}
              />
            </div>

            <div>
              <div className="eyebrow mb-2" style={{ fontSize: 10 }}>email</div>
              <GlassInput
                id="email"
                type="email"
                placeholder="you@company.ru"
                value={form.email}
                onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
                required
              />
            </div>

            <div>
              <div className="eyebrow mb-2" style={{ fontSize: 10 }}>пароль</div>
              <GlassInput
                id="password"
                type="password"
                placeholder="минимум 10 символов"
                minLength={8} maxLength={128}
                value={form.password}
                onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
                required
              />
              {form.password.length > 0 && form.password.length < 8 && (
                <p className="mt-1.5 mono" style={{ fontSize: 11, color: "var(--rose)" }}>
                  Минимум 8 символов ({8 - form.password.length} ещё)
                </p>
              )}
            </div>

            {/* Consent block */}
            <div className="panel-flat p-4 mt-2 flex flex-col gap-3">
              <label className="flex items-start gap-3 cursor-pointer">
                <span
                  className={`cbox mt-[2px] ${acceptedTerms ? "checked" : ""}`}
                  onClick={() => setAcceptedTerms((v) => !v)}
                >
                  {acceptedTerms && (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <path d="M5 12l5 5L20 7" />
                    </svg>
                  )}
                </span>
                <input
                  type="checkbox"
                  checked={acceptedTerms}
                  onChange={(e) => setAcceptedTerms(e.target.checked)}
                  required
                  className="sr-only"
                />
                <span className="text-[12.5px] t-72">
                  Принимаю{" "}
                  <Link href="/terms" target="_blank" className="text-white underline underline-offset-2" style={{ textDecorationColor: "var(--t-40)" }}>
                    условия использования
                  </Link>
                  {" "}и{" "}
                  <Link href="/privacy" target="_blank" className="text-white underline underline-offset-2" style={{ textDecorationColor: "var(--t-40)" }}>
                    оферту
                  </Link>.
                </span>
              </label>
              <label className="flex items-start gap-3 cursor-pointer">
                <span
                  className={`cbox mt-[2px] ${acceptedPrivacy ? "checked" : ""}`}
                  onClick={() => setAcceptedPrivacy((v) => !v)}
                >
                  {acceptedPrivacy && (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <path d="M5 12l5 5L20 7" />
                    </svg>
                  )}
                </span>
                <input
                  type="checkbox"
                  checked={acceptedPrivacy}
                  onChange={(e) => setAcceptedPrivacy(e.target.checked)}
                  required
                  className="sr-only"
                />
                <span className="text-[12.5px] t-72">
                  Согласен на обработку персональных данных по{" "}
                  <Link href="/privacy" target="_blank" className="text-white underline underline-offset-2" style={{ textDecorationColor: "var(--t-40)" }}>
                    152-ФЗ
                  </Link>.
                </span>
              </label>
            </div>

            <button
              type="submit"
              disabled={loading || !acceptedTerms || !acceptedPrivacy}
              className="btn btn-brand w-full mt-1"
              style={{ height: 44 }}
            >
              {loading ? "Создаём…" : "Зарегистрироваться"}
              {!loading && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M5 12h14M13 5l7 7-7 7" />
                </svg>
              )}
            </button>
          </form>

          <div className="hairline my-7" />

          <div className="text-center caption">
            Уже есть аккаунт?{" "}
            <Link href={loginHref} className="text-white underline underline-offset-4" style={{ textDecorationColor: "var(--t-40)" }}>
              Войти
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

export default function RegisterPage() {
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
      <RegisterContent />
    </Suspense>
  );
}

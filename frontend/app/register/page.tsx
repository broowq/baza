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

type RegisterResponse = {
  access_token: string;
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
  // Пришёл с /plans с выбранным тарифом → после регистрации вернём на оплату.
  const pendingPlan = searchParams.get("plan") ?? "";
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
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [acceptedPrivacy, setAcceptedPrivacy] = useState(false);

  useEffect(() => {
    if (invitedEmail) {
      setForm((current) => ({ ...current, email: current.email || invitedEmail }));
    }
  }, [invitedEmail]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    setLoading(true);
    try {
      const data = await api<RegisterResponse>("/auth/register", {
        method: "POST",
        body: JSON.stringify(form),
      });

      if (data.email_verification_required) {
        toast.success(data.message ?? "Аккаунт создан. Подтвердите email, затем войдите.");
        router.push(`/login${querySuffix}` as Route);
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

      router.push(pendingPlan ? "/plans" : "/dashboard");
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Не удалось зарегистрироваться";
      setFormError(msg);
      toast.error(msg);
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

        <div className="panel p-6 sm:p-10">
          <div className="eyebrow mb-3">создание аккаунта</div>
          <h2 className="h2">Начнём с первых лидов.</h2>
          <p className="caption mt-2">
            Регистрация займёт минуту, карта не нужна. Первые 10 лидов — бесплатно.
          </p>

          {inviteToken && (
            <div className="mb-5 panel-flat p-3 text-[12px] t-72">
              Создайте аккаунт, и приглашение в организацию применится автоматически.
            </div>
          )}

          <form onSubmit={onSubmit} className="mt-7 flex flex-col gap-3.5">
            <div>
              <label htmlFor="full_name" className="eyebrow mb-2" style={{ fontSize: 10, display: "block" }}>имя</label>
              <GlassInput
                id="full_name"
                placeholder="Михаил Кудрявцев"
                value={form.full_name}
                onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
                required minLength={2} maxLength={120}
                autoComplete="name"
              />
            </div>

            <div>
              <label htmlFor="organization_name" className="eyebrow mb-2" style={{ fontSize: 10, display: "block" }}>организация</label>
              <GlassInput
                id="organization_name"
                placeholder="ООО «Кедр-Сибирь»"
                value={form.organization_name}
                onChange={(e) => setForm((p) => ({ ...p, organization_name: e.target.value }))}
                required minLength={2} maxLength={120}
                autoComplete="organization"
              />
            </div>

            <div>
              <label htmlFor="email" className="eyebrow mb-2" style={{ fontSize: 10, display: "block" }}>email</label>
              <GlassInput
                id="email"
                type="email"
                placeholder="you@company.ru"
                value={form.email}
                onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
                required
                autoComplete="email"
              />
            </div>

            <div>
              <label htmlFor="password" className="eyebrow mb-2" style={{ fontSize: 10, display: "block" }}>пароль</label>
              <div className="relative">
                <GlassInput
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="минимум 8 символов"
                  minLength={8} maxLength={128}
                  value={form.password}
                  onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
                  required
                  autoComplete="new-password"
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
              {form.password.length > 0 && form.password.length < 8 && (
                <p className="mt-1.5 mono" style={{ fontSize: 11, color: "var(--rose)" }}>
                  Минимум 8 символов ({8 - form.password.length} ещё)
                </p>
              )}
            </div>

            {/* Consent block */}
            <div className="panel-flat p-4 mt-2 flex flex-col gap-3">
              <label className="flex items-start gap-3 cursor-pointer py-1.5 -my-1.5 sm:py-0 sm:my-0">
                <span
                  className={`cbox mt-[2px] !size-[18px] sm:!size-4 ${acceptedTerms ? "checked" : ""}`}
                  aria-hidden="true"
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
                  className="sr-only"
                  required
                />
                <span className="text-[12.5px] t-72">
                  Принимаю{" "}
                  <Link href="/terms" target="_blank" className="text-[var(--t-100)] underline underline-offset-2" style={{ textDecorationColor: "var(--t-40)" }}>
                    условия использования
                  </Link>
                  {/* Оферта = договорные условия (/terms), как в футере лендинга.
                      Раньше вела на /privacy — акцептовался не тот документ. */}
                  {" "}и{" "}
                  <Link href="/terms" target="_blank" className="text-[var(--t-100)] underline underline-offset-2" style={{ textDecorationColor: "var(--t-40)" }}>
                    оферту
                  </Link>.
                </span>
              </label>
              <label className="flex items-start gap-3 cursor-pointer py-1.5 -my-1.5 sm:py-0 sm:my-0">
                <span
                  className={`cbox mt-[2px] !size-[18px] sm:!size-4 ${acceptedPrivacy ? "checked" : ""}`}
                  aria-hidden="true"
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
                  className="sr-only"
                  required
                />
                <span className="text-[12.5px] t-72">
                  Согласен на обработку персональных данных по{" "}
                  <Link href="/privacy" target="_blank" className="text-[var(--t-100)] underline underline-offset-2" style={{ textDecorationColor: "var(--t-40)" }}>
                    152-ФЗ
                  </Link>.
                </span>
              </label>
            </div>

            {formError && (
              <div role="alert" aria-live="assertive" className="panel-flat px-3 py-2.5 text-[12px]" style={{ color: "var(--rose)" }}>
                {formError}
              </div>
            )}

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
            <Link href={loginHref} className="text-[var(--t-100)] underline underline-offset-4" style={{ textDecorationColor: "var(--t-40)" }}>
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

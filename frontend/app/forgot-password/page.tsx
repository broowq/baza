"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";

import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    setLoading(true);
    try {
      const response = await api<{ message: string }>("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      toast.success(response.message);
      setSent(true);
      setEmail("");
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Не удалось отправить ссылку";
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
          <div className="eyebrow mb-3">восстановление пароля</div>
          <h2 className="h2">Сбросим пароль.</h2>
          <p className="caption mt-2">Введите email — мы отправим ссылку для сброса пароля.</p>

          <form onSubmit={submit} className="mt-7 flex flex-col gap-4">
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

            {sent && (
              <div className="panel-flat px-3 py-2.5 text-[12px] t-72">
                Если аккаунт существует, мы отправили ссылку для сброса.
              </div>
            )}

            {formError && (
              <div role="alert" aria-live="assertive" className="panel-flat px-3 py-2.5 text-[12px]" style={{ color: "var(--rose)" }}>
                {formError}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || sent}
              className="btn btn-brand w-full mt-2"
              style={{ height: 44 }}
            >
              {loading ? "Отправляем…" : sent ? "Письмо отправлено" : "Отправить ссылку"}
              {!loading && !sent && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M5 12h14M13 5l7 7-7 7" />
                </svg>
              )}
            </button>
          </form>

          <div className="hairline my-7" />

          <div className="text-center caption">
            <Link href="/login" className="text-[var(--t-100)] underline underline-offset-4" style={{ textDecorationColor: "var(--t-40)" }}>
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

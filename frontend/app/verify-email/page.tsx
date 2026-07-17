"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";

import { api } from "@/lib/api";

function VerifyEmailContent() {
  const search = useSearchParams();
  const router = useRouter();
  const token = search.get("token") ?? "";
  const [status, setStatus] = useState<"verifying" | "success" | "error">("verifying");
  const [errorMsg, setErrorMsg] = useState("");
  // Переотправка письма: токен истекает за 24 ч, без resend аккаунт
  // оставался бы навсегда неподтверждённым.
  const [resendEmail, setResendEmail] = useState("");
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  const resend = async () => {
    if (!resendEmail.trim()) {
      toast.error("Укажите email, на который регистрировались");
      return;
    }
    setResending(true);
    try {
      const r = await api<{ message: string }>("/auth/resend-verification", {
        method: "POST",
        body: JSON.stringify({ email: resendEmail.trim() }),
      });
      setResent(true);
      toast.success(r.message || "Письмо отправлено");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось отправить письмо");
    } finally {
      setResending(false);
    }
  };

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setErrorMsg("Токен подтверждения отсутствует.");
      return;
    }
    let timerId: ReturnType<typeof setTimeout>;
    api<{ message: string }>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    })
      .then(() => {
        setStatus("success");
        toast.success("Email подтверждён. Перенаправляем на вход...");
        timerId = setTimeout(() => router.push("/login"), 2000);
      })
      .catch((error: Error) => {
        setStatus("error");
        setErrorMsg(error.message);
        toast.error(error.message);
      });
    return () => clearTimeout(timerId);
  }, [token, router]);

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
          <div className="eyebrow mb-3">подтверждение email</div>
          <h2 className="h2">Проверяем адрес.</h2>

          <div className="mt-7">
            {status === "verifying" && (
              <p className="caption">Проверяем токен подтверждения…</p>
            )}
            {status === "success" && (
              <div className="flex flex-col gap-4">
                <p className="caption" style={{ color: "var(--mint)" }}>
                  Email подтверждён! Перенаправляем на вход…
                </p>
                <Link
                  href="/login"
                  className="btn btn-ghost w-full text-center"
                  style={{ height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}
                >
                  Перейти ко входу
                </Link>
              </div>
            )}
            {status === "error" && (
              <div className="flex flex-col gap-4">
                <div className="panel-flat px-3 py-2.5 text-[13px] t-72">
                  {errorMsg || "Не удалось подтвердить email."}
                </div>
                {resent ? (
                  <p className="caption" style={{ color: "var(--mint)" }}>
                    Если аккаунт существует и не подтверждён — новое письмо уже в пути.
                    Проверьте почту (и папку «Спам»).
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    <label className="eyebrow" htmlFor="resend-email">
                      отправить письмо ещё раз
                    </label>
                    <input
                      id="resend-email"
                      type="email"
                      className="input"
                      placeholder="email, на который регистрировались"
                      value={resendEmail}
                      onChange={(e) => setResendEmail(e.target.value)}
                      autoComplete="email"
                    />
                    <button
                      type="button"
                      onClick={resend}
                      disabled={resending}
                      className="btn btn-brand w-full disabled:opacity-45"
                      style={{ height: 44 }}
                    >
                      {resending ? "Отправляю…" : "Отправить письмо ещё раз"}
                    </button>
                  </div>
                )}
                <Link
                  href="/login"
                  className="btn btn-ghost w-full text-center"
                  style={{ height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}
                >
                  Перейти ко входу
                </Link>
              </div>
            )}
          </div>
        </div>

        <p className="mt-6 text-center mono-cap" style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--t-40)" }}>
          © 2026 БАЗА · USEBAZA.RU · ХРАНЕНИЕ ДАННЫХ В РФ
        </p>
      </div>
    </main>
  );
}

export default function VerifyEmailPage() {
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
      <VerifyEmailContent />
    </Suspense>
  );
}

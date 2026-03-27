"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { api } from "@/lib/api";

function VerifyEmailContent() {
  const search = useSearchParams();
  const router = useRouter();
  const token = search.get("token") ?? "";
  const [status, setStatus] = useState<"verifying" | "success" | "error">("verifying");
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setErrorMsg("Токен подтверждения отсутствует.");
      return;
    }
    api<{ message: string }>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token })
    })
      .then(() => {
        setStatus("success");
        toast.success("Email подтверждён. Перенаправляем на вход...");
        setTimeout(() => router.push("/login"), 2000);
      })
      .catch((error: Error) => {
        setStatus("error");
        setErrorMsg(error.message);
        toast.error(error.message);
      });
  }, [token, router]);

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <section className="card space-y-3">
        <h1 className="text-2xl font-bold">Подтверждение email</h1>
        {status === "verifying" && (
          <p className="text-sm text-slate-500">Проверяем токен подтверждения...</p>
        )}
        {status === "success" && (
          <p className="text-sm text-green-600 dark:text-green-400">Email подтверждён! Перенаправляем на вход...</p>
        )}
        {status === "error" && (
          <p className="text-sm text-red-600 dark:text-red-400">{errorMsg || "Не удалось подтвердить email."}</p>
        )}
      </section>
    </main>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-md px-6 py-16"><section className="card">Загрузка...</section></main>}>
      <VerifyEmailContent />
    </Suspense>
  );
}

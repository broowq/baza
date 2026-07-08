"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { clearToken, getToken, getTokenExpirySeconds, setToken } from "@/lib/auth";

// Рефрешим access-токен, как только до его конца остаётся ≤ этого порога
// (или он уже истёк — например, пока вкладка спала и интервал не тикал).
const REFRESH_WHEN_REMAINING_SEC = 5 * 60; // 5 минут
const CHECK_INTERVAL_MS = 30_000; // проверка каждые 30с
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export function SessionWarning() {
  const refreshing = useRef(false);
  const router = useRouter();

  useEffect(() => {
    const check = async () => {
      const token = getToken();
      if (!token) return; // не залогинен — нечего продлевать

      const remaining = getTokenExpirySeconds();
      if (remaining === null) return;

      // Ещё далеко до конца — ничего не делаем.
      if (remaining > REFRESH_WHEN_REMAINING_SEC || refreshing.current) return;

      // Токен близок к истечению ИЛИ уже истёк (вкладка была в фоне/ноут спал).
      // ТИХО продлеваем по httpOnly refresh-cookie. На /login кидаем ТОЛЬКО
      // если refresh реально отвергнут (cookie истёк/отозван) — раньше здесь
      // был баг: истёкший 30-мин access сразу выбрасывал на логин, хотя рядом
      // лежал живой refresh на 7–30 дней.
      refreshing.current = true;
      try {
        const res = await fetch(`${API_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({}),
        });
        if (res.ok) {
          const data = (await res.json()) as { access_token: string };
          setToken(data.access_token);
        } else if (res.status === 401) {
          // Refresh недействителен — сессия действительно закончилась.
          clearToken();
          toast.error("Сессия истекла. Войдите снова.", {
            duration: 6000,
            action: { label: "Войти", onClick: () => router.push("/login") },
          });
          router.push("/login");
        }
        // Прочие коды (5xx/сеть) — НЕ разлогиниваем, повторим на след. тике.
      } catch {
        // Сетевая ошибка — молчим, попробуем снова через 30с.
      } finally {
        refreshing.current = false;
      }
    };

    void check();
    const interval = setInterval(() => void check(), CHECK_INTERVAL_MS);
    // Возврат на вкладку/пробуждение ноута — сразу проверить и продлить, не
    // дожидаясь следующего 30-секундного тика.
    const onVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [router]);

  return null; // Невидимый компонент, общается тостами
}

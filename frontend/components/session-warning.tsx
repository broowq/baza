"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { getToken, getTokenExpirySeconds, setToken } from "@/lib/auth";

const WARNING_BEFORE_EXPIRY_SEC = 5 * 60; // 5 minutes
const CHECK_INTERVAL_MS = 30_000; // check every 30s
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export function SessionWarning() {
  const warningShown = useRef(false);
  const refreshing = useRef(false);

  useEffect(() => {
    const check = async () => {
      const token = getToken();
      if (!token) {
        warningShown.current = false;
        return;
      }

      const remaining = getTokenExpirySeconds();
      if (remaining === null) return;

      // Token already expired
      if (remaining <= 0) {
        warningShown.current = false;
        return;
      }

      // Show warning and auto-refresh when approaching expiry
      if (remaining <= WARNING_BEFORE_EXPIRY_SEC && !warningShown.current && !refreshing.current) {
        warningShown.current = true;
        refreshing.current = true;

        toast.warning("Сессия скоро истечёт. Обновляем токен...", { duration: 4000 });

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
            warningShown.current = false;
            toast.success("Сессия продлена", { duration: 3000 });
          } else {
            toast.error("Не удалось продлить сессию. Войдите снова.", { duration: 5000 });
          }
        } catch {
          toast.error("Ошибка при обновлении сессии", { duration: 5000 });
        } finally {
          refreshing.current = false;
        }
      }
    };

    // Initial check
    void check();
    const interval = setInterval(() => void check(), CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  return null; // Invisible component, communicates via toasts
}

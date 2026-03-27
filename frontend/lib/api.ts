"use client";

import { clearToken, getOrgId, getToken, setToken } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let token = getToken();
  const orgId = getOrgId();

  const request = async (authToken: string | null) => {
    const headers = new Headers(init?.headers ?? {});
    headers.set("Content-Type", "application/json");
    if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
    if (orgId) headers.set("X-Org-Id", orgId);
    return fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store", credentials: "include" });
  };

  let res: Response;
  try {
    res = await request(token);
  } catch {
    throw new Error("Нет соединения с сервером");
  }

  if (res.status === 401) {
    if (token) {
      // Try token refresh
      try {
        const refreshRes = await fetch(`${API_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({}),
        });
        if (refreshRes.ok) {
          const refreshed = (await refreshRes.json()) as { access_token: string };
          setToken(refreshed.access_token);
          token = refreshed.access_token;
          res = await request(token);
        } else {
          // Refresh failed — session expired, redirect to login
          clearToken();
          if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
            window.location.href = "/login";
          }
          throw new Error("Сессия истекла. Войдите снова.");
        }
      } catch (e) {
        if (e instanceof Error && e.message === "Сессия истекла. Войдите снова.") throw e;
        clearToken();
        throw new Error("Нет соединения с сервером");
      }
    } else {
      // No token at all — redirect to login
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
      throw new Error("Требуется авторизация. Войдите в систему.");
    }
  }

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => ({ detail: undefined })) as { detail?: string };
    throw new Error(errorPayload.detail ?? `Ошибка запроса (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get("content-type");
  if (contentType?.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as T;
}

/** Raw fetch with token refresh for non-JSON responses (e.g. CSV blobs). */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  let token = getToken();
  const orgId = getOrgId();

  const request = (authToken: string | null) => {
    const headers = new Headers(init?.headers ?? {});
    if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
    if (orgId) headers.set("X-Org-Id", orgId);
    return fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
  };

  let res = await request(token);

  if (res.status === 401 && token) {
    try {
      const refreshRes = await fetch(`${API_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({}),
      });
      if (refreshRes.ok) {
        const refreshed = (await refreshRes.json()) as { access_token: string };
        setToken(refreshed.access_token);
        res = await request(refreshed.access_token);
      } else {
        clearToken();
        if (typeof window !== "undefined") window.location.href = "/login";
      }
    } catch {
      clearToken();
    }
  }

  if (!res.ok) {
    throw new Error(`Ошибка запроса (${res.status})`);
  }
  return res;
}

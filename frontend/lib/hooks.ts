"use client";

import { useEffect, useState } from "react";
import { getToken, getTokenExpirySeconds } from "@/lib/auth";

/**
 * Debounces a value by the given delay.
 * Returns the debounced value that only updates after `delay` ms of inactivity.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

/**
 * Redirects to /login if the user has no access token in localStorage.
 * Returns `true` once the token check passes so the page can render.
 */
export function useAuthGuard(): boolean {
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const remaining = getTokenExpirySeconds();
    if (!getToken() || (remaining !== null && remaining <= 0)) {
      window.location.href = "/login";
    } else {
      setAuthed(true);
    }
  }, []);

  return authed;
}

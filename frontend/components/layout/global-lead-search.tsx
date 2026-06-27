"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";

import { api } from "@/lib/api";
import { useDebounce } from "@/lib/hooks";
import type { Lead } from "@/lib/types";

type PaginatedLeads = {
  items: Lead[];
  total: number;
  page: number;
  per_page: number;
};

const STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  proposal: "КП отправлено",
  won: "Сделка",
  rejected: "Отклонён",
};

/**
 * Compact global lead search, mounted near the top of the sidebar.
 * - Debounced (>=2 chars) hits GET /leads/all?search=&per_page=8.
 * - Clicking a result jumps to the hub with that lead's drawer open.
 * - Enter opens the hub pre-filtered by the query.
 * - Escape / blur closes the dropdown; ⌘K / Ctrl+K focuses the box.
 */
export function GlobalLeadSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const debounced = useDebounce(query, 250);
  const [results, setResults] = useState<Lead[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(-1);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Guards against a slow response from a stale query overwriting a newer one.
  const reqIdRef = useRef(0);

  // ⌘K / Ctrl+K focuses the search box from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Click outside closes the dropdown.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  useEffect(() => {
    const term = debounced.trim();
    if (term.length < 2) {
      setResults([]);
      setLoading(false);
      setActive(-1);
      return;
    }
    const reqId = ++reqIdRef.current;
    setLoading(true);
    const params = new URLSearchParams({ search: term, per_page: "8" });
    api<PaginatedLeads>(`/leads/all?${params.toString()}`)
      .then((data) => {
        if (reqId !== reqIdRef.current) return; // a newer request superseded this one
        setResults(Array.isArray(data.items) ? data.items : []);
        setOpen(true);
        setActive(-1);
      })
      .catch(() => {
        if (reqId !== reqIdRef.current) return;
        setResults([]);
      })
      .finally(() => {
        if (reqId === reqIdRef.current) setLoading(false);
      });
  }, [debounced]);

  const goToLead = (id: string) => {
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
    router.push(`/dashboard/leads?open=${id}` as Route);
  };

  const goToHub = () => {
    const term = query.trim();
    if (!term) return;
    setOpen(false);
    inputRef.current?.blur();
    router.push(`/dashboard/leads?q=${encodeURIComponent(term)}` as Route);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (open && active >= 0 && results[active]) goToLead(results[active].id);
      else goToHub();
      return;
    }
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((p) => (p + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((p) => (p <= 0 ? results.length - 1 : p - 1));
    }
  };

  const showDropdown = open && debounced.trim().length >= 2;

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2"
          style={{ width: 13, height: 13, color: "var(--t-40)" }}
        >
          <circle cx="11" cy="11" r="7" />
          <path d="M21 21l-4.3-4.3" />
        </svg>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => { if (results.length > 0) setOpen(true); }}
          onKeyDown={onKeyDown}
          placeholder="Поиск лидов…"
          aria-label="Глобальный поиск лидов"
          className="input"
          style={{ paddingLeft: 30, paddingRight: 28, height: 34, fontSize: 12.5 }}
        />
        <kbd
          aria-hidden
          className="mono pointer-events-none absolute right-2 top-1/2 -translate-y-1/2"
          style={{ fontSize: 9.5, color: "var(--t-40)" }}
        >
          ⌘K
        </kbd>
      </div>

      {showDropdown && (
        <div
          role="listbox"
          className="panel absolute left-0 right-0 z-50 mt-1.5 overflow-hidden p-1"
          style={{ maxHeight: 320, overflowY: "auto" }}
        >
          {loading && results.length === 0 ? (
            <div className="px-2.5 py-3 text-[12px] t-48">Поиск…</div>
          ) : results.length === 0 ? (
            <div className="px-2.5 py-3 text-[12px] t-48">Ничего не найдено</div>
          ) : (
            results.map((lead, i) => (
              <button
                key={lead.id}
                type="button"
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onClick={() => goToLead(lead.id)}
                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors"
                style={{ background: i === active ? "var(--surface-hover)" : "transparent" }}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px]" style={{ color: "var(--t-100)" }} title={lead.company}>
                    {lead.company}
                  </div>
                  {lead.project_name && (
                    <div className="truncate text-[11px] t-48">{lead.project_name}</div>
                  )}
                </div>
                <span className="chip shrink-0" style={{ fontSize: 9.5 }}>
                  {STATUS_LABELS[lead.status] ?? lead.status}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

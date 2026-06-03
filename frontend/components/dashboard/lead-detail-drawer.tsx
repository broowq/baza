"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, X, Copy, Check, Mail, Phone, MapPin, Building2, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { Lead, LeadDetail } from "@/lib/types";

/* ─────────────────────────────────────────────────────────────────
   Constants
───────────────────────────────────────────────────────────────── */

const STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  contacted: "Контакт",
  qualified: "Квалифицирован",
  rejected: "Отклонён",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
  new: "badge--new",
  contacted: "badge--contacted",
  qualified: "badge--qualified",
  rejected: "badge--rejected",
};

const SOURCE_LABELS: Record<string, string> = {
  yandex_maps: "Яндекс Карты",
  "2gis": "2ГИС",
  rusprofile: "ЕГРЮЛ",
  maps_searxng: "Яндекс Карты (web)",
  searxng: "Web-поиск",
  bing: "Bing",
};

const STATUS_OPTIONS: { value: Lead["status"]; label: string }[] = [
  { value: "new",       label: "Новый" },
  { value: "contacted", label: "Контакт" },
  { value: "qualified", label: "Квалифицирован" },
  { value: "rejected",  label: "Отклонён" },
];

/* ─────────────────────────────────────────────────────────────────
   Copy-to-clipboard button helper
───────────────────────────────────────────────────────────────── */
function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="focus-ring ml-1 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded opacity-40 transition-opacity hover:opacity-80"
      aria-label={`Скопировать ${value}`}
      title="Скопировать"
    >
      {copied
        ? <Check size={11} className="text-status-online" />
        : <Copy size={11} />
      }
    </button>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Score ring (fully self-contained — avoids SVG xmlns issues)
───────────────────────────────────────────────────────────────── */
function ScoreRing({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const frac = clamped / 100;
  const circumference = 94.25;
  const dashOffset = circumference * (1 - frac);

  return (
    <div className="score-ring score-ring--lg" style={{ "--score": frac } as React.CSSProperties}>
      <svg viewBox="0 0 36 36" className="score-ring__svg" aria-hidden="true">
        <circle className="score-ring__track" cx="18" cy="18" r="15" />
        <circle
          className="score-ring__arc"
          cx="18"
          cy="18"
          r="15"
          style={{ strokeDashoffset: dashOffset }}
        />
      </svg>
      <span className="score-ring__label">{clamped}</span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Email status inline chip
───────────────────────────────────────────────────────────────── */
function EmailStatusChip({ status }: { status?: string }) {
  if (!status || status === "skipped" || status === "") return null;
  if (status === "valid") {
    return (
      <span className="chip chip-em ml-1 py-0.5 px-1.5 text-[10px]">
        ✓ MX
      </span>
    );
  }
  if (status === "no_mx") {
    return (
      <span className="chip chip-rs ml-1 py-0.5 px-1.5 text-[10px]">
        no MX
      </span>
    );
  }
  if (status === "syntax") {
    return (
      <span className="chip chip-rs ml-1 py-0.5 px-1.5 text-[10px]">
        синтаксис
      </span>
    );
  }
  return null;
}

/* ─────────────────────────────────────────────────────────────────
   Strip notes prefix (e.g. "relevance=85; demo=true; ...")
───────────────────────────────────────────────────────────────── */
function stripNotesPrefix(notes: string): string {
  // Strip leading "key=value; " metadata inserted by the pipeline
  return notes.replace(/^([\w]+=[^;]+;\s*)+/, "").trim();
}

/* ─────────────────────────────────────────────────────────────────
   Main Drawer Props
───────────────────────────────────────────────────────────────── */
export type LeadDetailDrawerProps = {
  leadId: string | null;
  onClose: () => void;
  onLeadUpdate?: (leadId: string, patch: Partial<Lead>) => void;
};

/* ─────────────────────────────────────────────────────────────────
   LeadDetailDrawer
───────────────────────────────────────────────────────────────── */
export function LeadDetailDrawer({ leadId, onClose, onLeadUpdate }: LeadDetailDrawerProps) {
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [editNotes, setEditNotes] = useState("");
  const [tagInput, setTagInput] = useState("");
  const drawerRef = useRef<HTMLElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  const isOpen = !!leadId;

  /* Fetch detail when leadId changes */
  useEffect(() => {
    if (!leadId) {
      setDetail(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    api<LeadDetail>(`/leads/${leadId}`)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setEditNotes(stripNotesPrefix(data.notes ?? ""));
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Не удалось загрузить лид");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [leadId]);

  /* Focus the close button when drawer opens */
  useEffect(() => {
    if (isOpen) {
      // Give CSS transition a tick before focusing
      const id = setTimeout(() => closeBtnRef.current?.focus(), 260);
      return () => clearTimeout(id);
    }
  }, [isOpen]);

  /* Escape key closes */
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  /* Patch helper */
  const patchLead = useCallback(async (patch: Partial<Lead> & { mark_contacted?: boolean }) => {
    if (!leadId) return;
    setSaving(true);
    try {
      const updated = await api<Lead>(`/leads/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setDetail((prev) => prev ? { ...prev, ...updated } : prev);
      onLeadUpdate?.(leadId, updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }, [leadId, onLeadUpdate]);

  const changeStatus = (newStatus: Lead["status"]) => void patchLead({ status: newStatus });

  const saveNotes = () => {
    const stripped = editNotes.trim();
    const current = stripNotesPrefix(detail?.notes ?? "");
    if (stripped !== current) void patchLead({ notes: stripped });
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t || (detail?.tags ?? []).includes(t)) { setTagInput(""); return; }
    void patchLead({ tags: [...(detail?.tags ?? []), t] });
    setTagInput("");
  };

  const removeTag = (t: string) => {
    void patchLead({ tags: (detail?.tags ?? []).filter((x) => x !== t) });
  };

  /* Derive useful values */
  const websiteOk = detail?.website && /^https?:\/\//i.test(detail.website.trim());
  const isAccent = (detail?.score ?? 0) >= 80;

  return (
    <>
      {/* Scrim */}
      <div
        className={`drawer-scrim${isOpen ? " drawer--open" : ""}`}
        aria-hidden="true"
        onClick={onClose}
      />

      {/* Drawer */}
      <aside
        ref={drawerRef}
        className={`detail-drawer${isOpen ? " drawer--open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={detail?.company ?? "Детали лида"}
        aria-busy={loading}
      >
        <div className="drawer-panel">
          {/* ── HEADER ─────────────────────────────── */}
          <header className="drawer-header">
            <div className="flex min-w-0 flex-1 items-center gap-3">
              {loading ? (
                <div className="skeleton" style={{ width: 64, height: 64, borderRadius: "50%" }} />
              ) : detail ? (
                <ScoreRing score={detail.score} />
              ) : null}

              <div className="min-w-0 flex-1">
                {loading ? (
                  <>
                    <div className="skeleton mb-2" style={{ width: 160, height: 16, borderRadius: 6 }} />
                    <div className="skeleton" style={{ width: 100, height: 12, borderRadius: 4 }} />
                  </>
                ) : detail ? (
                  <>
                    <h2
                      className="lead-card__name mb-1"
                      style={{ fontSize: 15 }}
                      title={detail.company}
                    >
                      {isAccent && (
                        <span
                          className="mr-1.5 inline-block h-2 w-2 rounded-full"
                          style={{ background: "var(--mint)", boxShadow: "0 0 8px rgba(168,197,192,0.7)", verticalAlign: "middle" }}
                          aria-hidden="true"
                        />
                      )}
                      {detail.company}
                    </h2>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={`badge ${STATUS_BADGE_CLASS[detail.status] ?? ""}`}>
                        {STATUS_LABELS[detail.status] ?? detail.status}
                      </span>
                      {detail.source && (
                        <span className="badge badge--source">
                          {SOURCE_LABELS[detail.source] ?? detail.source}
                        </span>
                      )}
                    </div>
                    {websiteOk ? (
                      <a
                        href={detail.website}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="lead-card__sub mt-1 inline-flex items-center gap-1 hover:text-white"
                        style={{ textDecoration: "none" }}
                      >
                        {detail.domain || detail.website.replace(/^https?:\/\//, "").split("/")[0]}
                        <ExternalLink size={10} className="shrink-0 opacity-60" />
                      </a>
                    ) : detail.website ? (
                      <span className="lead-card__sub mt-1 block">
                        {SOURCE_LABELS[detail.source ?? ""] ?? detail.website}
                      </span>
                    ) : null}
                  </>
                ) : null}
              </div>
            </div>

            <button
              ref={closeBtnRef}
              type="button"
              onClick={onClose}
              className="focus-ring ml-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg opacity-56 transition-opacity hover:opacity-100"
              style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }}
              aria-label="Закрыть"
            >
              <X size={15} />
            </button>
          </header>

          {/* ── BODY ───────────────────────────────── */}
          <div className="drawer-body">
            {loading && (
              <div className="space-y-4">
                {[120, 80, 100, 60].map((w, i) => (
                  <div key={i} className="skeleton" style={{ width: `${w}%`, height: 14, borderRadius: 6 }} />
                ))}
              </div>
            )}

            {error && (
              <div className="empty-state">
                <span className="empty-state__title">Не удалось загрузить</span>
                <span className="empty-state__body">{error}</span>
              </div>
            )}

            {!loading && !error && detail && (
              <div className="space-y-5">
                {/* Description */}
                {detail.description && (
                  <section>
                    <div className="eyebrow mb-2">О компании</div>
                    <p className="caption" style={{ lineHeight: 1.65 }}>
                      {detail.description}
                    </p>
                  </section>
                )}

                {/* Contacts */}
                <section>
                  <div className="eyebrow mb-2">Контакты</div>
                  <div
                    className="panel-glass divide-y"
                    style={{ "--tw-divide-opacity": 1, divideColor: "rgba(255,255,255,0.06)" } as React.CSSProperties}
                  >
                    {detail.email && (
                      <div className="flex items-center gap-2 px-3 py-2.5">
                        <Mail size={13} className="shrink-0 opacity-48" />
                        <a
                          href={`mailto:${detail.email}`}
                          className="caption min-w-0 flex-1 truncate hover:text-white"
                        >
                          {detail.email}
                        </a>
                        <EmailStatusChip status={detail.email_status} />
                        <CopyButton value={detail.email} />
                      </div>
                    )}
                    {detail.phone && (
                      <div className="flex items-center gap-2 px-3 py-2.5">
                        <Phone size={13} className="shrink-0 opacity-48" />
                        <a
                          href={`tel:${detail.phone}`}
                          className="caption font-mono min-w-0 flex-1 truncate hover:text-white"
                        >
                          {detail.phone}
                        </a>
                        <CopyButton value={detail.phone} />
                      </div>
                    )}
                    {detail.address && (
                      <div className="flex items-start gap-2 px-3 py-2.5">
                        <MapPin size={13} className="mt-0.5 shrink-0 opacity-48" />
                        <span className="caption min-w-0 flex-1 leading-relaxed">
                          {detail.address}
                        </span>
                        <CopyButton value={detail.address} />
                      </div>
                    )}
                    {!detail.email && !detail.phone && !detail.address && (
                      <div className="px-3 py-3">
                        <span className="t-40 text-xs">Контактные данные не найдены</span>
                      </div>
                    )}
                  </div>
                </section>

                {/* Categories */}
                {detail.warehouse?.categories && detail.warehouse.categories.length > 0 && (
                  <section>
                    <div className="eyebrow mb-2">Категории</div>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.warehouse.categories.map((cat) => (
                        <span
                          key={cat}
                          className="chip chip-sans max-w-full text-left"
                          style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}
                        >
                          {cat}
                        </span>
                      ))}
                    </div>
                  </section>
                )}

                {/* Warehouse / Реестр БАЗА */}
                <section>
                  <div className="eyebrow mb-2">Реестр БАЗА</div>
                  {detail.warehouse?.found ? (
                    <div className="panel-glass space-y-3 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="chip chip-em" style={{ fontSize: 11 }}>
                          Найдена {detail.warehouse.times_seen ?? 1} раз
                        </span>
                        {detail.warehouse.inn && (
                          <span className="chip" style={{ fontSize: 10.5 }}>
                            ИНН: {detail.warehouse.inn}
                          </span>
                        )}
                      </div>

                      {(detail.warehouse.first_seen_at || detail.warehouse.last_seen_at) && (
                        <div className="flex flex-wrap gap-3 text-xs text-white/[0.48]">
                          {detail.warehouse.first_seen_at && (
                            <span>
                              первый раз:{" "}
                              <span className="t-72">
                                {new Date(detail.warehouse.first_seen_at).toLocaleDateString("ru-RU")}
                              </span>
                            </span>
                          )}
                          {detail.warehouse.last_seen_at && (
                            <span>
                              последний раз:{" "}
                              <span className="t-72">
                                {new Date(detail.warehouse.last_seen_at).toLocaleDateString("ru-RU")}
                              </span>
                            </span>
                          )}
                        </div>
                      )}

                      {detail.warehouse.other_niches && detail.warehouse.other_niches.length > 0 && (
                        <div>
                          <div className="mb-1 text-[10px] uppercase tracking-wider text-white/[0.40]">Ниши</div>
                          <div className="flex flex-wrap gap-1.5">
                            {detail.warehouse.other_niches.map((n) => (
                              <span
                                key={n}
                                className="chip chip-mint chip-sans max-w-full text-left"
                                style={{ whiteSpace: "normal", overflowWrap: "anywhere", lineHeight: 1.35 }}
                              >
                                {n}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {detail.warehouse.sources && detail.warehouse.sources.length > 0 && (
                        <div>
                          <div className="mb-1 text-[10px] uppercase tracking-wider text-white/[0.40]">Источники</div>
                          <div className="flex flex-wrap gap-1.5">
                            {detail.warehouse.sources.map((s) => (
                              <span
                                key={s}
                                className="chip max-w-full text-left"
                                style={{ fontSize: 10.5, whiteSpace: "normal", overflowWrap: "anywhere" }}
                              >
                                {SOURCE_LABELS[s] ?? s}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="panel-glass px-3 py-2.5">
                      <span className="t-40 text-xs">не в реестре</span>
                    </div>
                  )}
                </section>

                {/* Tags */}
                <section>
                  <div className="eyebrow mb-2">Теги</div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {(detail.tags ?? []).map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => removeTag(t)}
                        disabled={saving}
                        className="chip chip-sans focus-ring hover:opacity-70 disabled:opacity-50"
                        title={`Удалить тег "${t}"`}
                      >
                        {t}
                        <X size={9} className="ml-0.5 opacity-56" />
                      </button>
                    ))}
                    <input
                      type="text"
                      value={tagInput}
                      onChange={(e) => setTagInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
                      placeholder="+ тег"
                      disabled={saving}
                      className="input focus-ring h-7 w-24 rounded-full px-3 text-xs"
                      style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.10)" }}
                    />
                  </div>
                </section>

                {/* Notes */}
                <section>
                  <div className="eyebrow mb-2">Заметка</div>
                  <textarea
                    value={editNotes}
                    onChange={(e) => setEditNotes(e.target.value)}
                    onBlur={saveNotes}
                    disabled={saving}
                    rows={3}
                    placeholder="Контекст переговоров, кто принимает решение..."
                    className="input focus-ring w-full resize-none rounded-xl px-3 py-2.5 text-sm"
                    style={{
                      height: "auto",
                      background: "rgba(255,255,255,0.04)",
                      border: "1px solid rgba(255,255,255,0.10)",
                    }}
                  />
                </section>
              </div>
            )}
          </div>

          {/* ── FOOTER ─────────────────────────────── */}
          <footer className="drawer-footer">
            {detail && (
              <div className="space-y-3">
                {/* Status change */}
                <div>
                  <div className="eyebrow mb-2">Изменить статус</div>
                  <div className="flex flex-wrap gap-1.5">
                    {STATUS_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        disabled={saving || detail.status === opt.value}
                        onClick={() => changeStatus(opt.value)}
                        className={`pill focus-ring text-xs${detail.status === opt.value ? " active" : ""}`}
                        aria-pressed={detail.status === opt.value}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Mark contacted */}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={saving}
                    onClick={() => void patchLead({ mark_contacted: true })}
                    className="btn btn-brand focus-ring flex-1 text-xs"
                    style={{ height: 34, fontSize: 12 }}
                  >
                    {saving
                      ? <Loader2 size={12} className="animate-spin" />
                      : "✓ Связались сейчас"
                    }
                  </button>
                  {detail.last_contacted_at && (
                    <span className="t-40 text-xs">
                      {new Date(detail.last_contacted_at).toLocaleDateString("ru-RU")}
                    </span>
                  )}
                </div>

                {/* Company icon + link if rusprofile */}
                {detail.source === "rusprofile" && detail.external_id && (
                  <a
                    href={`https://www.rusprofile.ru/id/${detail.external_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-ghost focus-ring w-full text-xs"
                    style={{ height: 32, fontSize: 11 }}
                  >
                    <Building2 size={12} className="mr-1" />
                    ЕГРЮЛ: rusprofile.ru
                    <ExternalLink size={10} className="ml-auto opacity-48" />
                  </a>
                )}
              </div>
            )}
          </footer>
        </div>
      </aside>
    </>
  );
}

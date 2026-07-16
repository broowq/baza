"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ExternalLink, X, Copy, Check, Mail, Phone, MapPin, Building2, Loader2, PhoneCall,
  Plus, Trash2, Calendar, User, Banknote, Sparkles, ArrowRightLeft, UserPlus, UserMinus,
  StickyNote, CheckCircle2, ListChecks, CircleDot, Send, ArrowUpRight, ArrowDownLeft,
  MessageCircle, MailOpen, Eye, MousePointerClick,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { pluralN } from "@/lib/plural";
import type {
  Lead, LeadCallNote, LeadDetail, OrgMember, LeadTask, LeadActivity, EmailSequence,
} from "@/lib/types";

/* ─────────────────────────────────────────────────────────────────
   Constants
───────────────────────────────────────────────────────────────── */

const STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  proposal: "КП отправлено",
  won: "Сделка",
  rejected: "Отказ",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
  new: "badge--new",
  contacted: "badge--contacted",
  qualified: "badge--qualified",
  rejected: "badge--rejected",
};

/* proposal/won have no dedicated CSS badge variant — derive themed inline
   styles from tokens (amber for proposal, mint for won). */
const STATUS_BADGE_STYLE: Record<string, React.CSSProperties> = {
  proposal: {
    background: "rgba(251, 191, 36, 0.10)",
    borderColor: "rgba(251, 191, 36, 0.28)",
    color: "var(--amber)",
  },
  won: {
    background: "rgba(168, 197, 192, 0.12)",
    borderColor: "rgba(168, 197, 192, 0.32)",
    color: "var(--mint)",
  },
};

const SOURCE_LABELS: Record<string, string> = {
  yandex_maps: "Яндекс Карты",
  "2gis": "2ГИС",
  rusprofile: "ЕГРЮЛ",
  maps_searxng: "Яндекс Карты (web)",
  searxng: "Web-поиск",
  yandex_search: "Яндекс.Поиск",
  bing: "Bing",
  warehouse: "Наша база",
  manual: "Вручную",
};

const STATUS_OPTIONS: { value: Lead["status"]; label: string }[] = [
  { value: "new",       label: "Новый" },
  { value: "contacted", label: "Связались" },
  { value: "qualified", label: "Квалифицирован" },
  { value: "proposal",  label: "КП отправлено" },
  { value: "won",       label: "Сделка" },
  { value: "rejected",  label: "Отказ" },
];

/* ─────────────────────────────────────────────────────────────────
   Date helpers (shared by deal-close, tasks, timeline)
───────────────────────────────────────────────────────────────── */
/** YYYY-MM-DD for <input type="date"> from an ISO/date string. */
function isoToDateInput(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A date-only input value → ISO at local midnight (or null when cleared). */
function dateInputToIso(value: string): string | null {
  if (!value) return null;
  const d = new Date(`${value}T00:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

function shortDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

function shortDateTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function isOverdue(iso?: string | null): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return d.getTime() < Date.now();
}

function formatRub(value?: number | null): string {
  if (value == null || value === 0) return "";
  try {
    return new Intl.NumberFormat("ru-RU").format(value);
  } catch {
    return String(value);
  }
}

/* ─────────────────────────────────────────────────────────────────
   Timeline: icon + accent colour per activity kind
───────────────────────────────────────────────────────────────── */
function activityVisual(kind: string): { Icon: typeof Sparkles; color: string } {
  switch (kind) {
    case "created":       return { Icon: Sparkles,       color: "var(--mint)" };
    case "stage_changed": return { Icon: ArrowRightLeft, color: "var(--sky)" };
    case "assigned":      return { Icon: UserPlus,       color: "var(--sky)" };
    case "unassigned":    return { Icon: UserMinus,      color: "var(--t-48)" };
    case "value_changed": return { Icon: Banknote,       color: "var(--amber)" };
    case "note":          return { Icon: StickyNote,     color: "var(--t-56)" };
    case "contacted":     return { Icon: PhoneCall,      color: "var(--green)" };
    case "call":          return { Icon: PhoneCall,      color: "var(--green)" };
    case "task_created":  return { Icon: ListChecks,     color: "var(--t-56)" };
    case "task_done":     return { Icon: CheckCircle2,   color: "var(--green)" };
    case "email_sent":    return { Icon: ArrowUpRight,   color: "var(--sky)" };
    case "email_in":      return { Icon: ArrowDownLeft,  color: "var(--mint)" };
    case "touch":         return { Icon: PhoneCall,      color: "var(--green)" };
    default:              return { Icon: CircleDot,      color: "var(--t-48)" };
  }
}

/* Touch channels carry their own icon/colour via meta.channel. */
function touchVisual(channel?: string): { Icon: typeof Sparkles; color: string; label: string } {
  switch (channel) {
    case "whatsapp": return { Icon: MessageCircle, color: "var(--green)", label: "WhatsApp" };
    case "telegram": return { Icon: Send,          color: "var(--sky)",   label: "Telegram" };
    case "call":     return { Icon: PhoneCall,     color: "var(--green)", label: "Звонок" };
    default:         return { Icon: PhoneCall,     color: "var(--green)", label: "Контакт" };
  }
}

/* Strip a phone string down to a leading «+» (if any) and digits. */
function phoneDigits(phone?: string | null): string {
  if (!phone) return "";
  const trimmed = phone.trim();
  const plus = trimmed.startsWith("+") ? "+" : "";
  return plus + trimmed.replace(/\D/g, "");
}

/* Digits for wa.me / t.me links: no «+», российское «8…» → «7…». */
function messengerDigits(phone?: string | null): string {
  const bare = phoneDigits(phone).replace(/^\+/, "");
  if (bare.length === 11 && bare.startsWith("8")) return `7${bare.slice(1)}`;
  return bare;
}

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
export function stripNotesPrefix(notes: string): string {
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
  const [calls, setCalls] = useState<LeadCallNote[]>([]);
  const [callComment, setCallComment] = useState("");
  const [savingCall, setSavingCall] = useState(false);

  /* ── CRM state (all non-critical: graceful catch on every fetch) ── */
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [dealValueInput, setDealValueInput] = useState("");
  const [closeDateInput, setCloseDateInput] = useState("");

  const [tasks, setTasks] = useState<LeadTask[]>([]);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskDue, setNewTaskDue] = useState("");
  const [addingTask, setAddingTask] = useState(false);

  const [activities, setActivities] = useState<LeadActivity[]>([]);
  const [activitiesLoading, setActivitiesLoading] = useState(false);

  /* ── Direct email composer (reply / write to the lead) ── */
  const [composerOpen, setComposerOpen] = useState(false);
  const [emailSubject, setEmailSubject] = useState("");
  const [emailBody, setEmailBody] = useState("");
  const [sendingEmail, setSendingEmail] = useState(false);
  const [aiDrafting, setAiDrafting] = useState(false);
  const [touchingChannel, setTouchingChannel] = useState<string | null>(null);

  /* ── Email sequence enrollment (lazy: fetched on first open) ── */
  const [sequences, setSequences] = useState<EmailSequence[] | null>(null);
  const [seqLoading, setSeqLoading] = useState(false);
  const [selectedSeqId, setSelectedSeqId] = useState("");
  const [enrolling, setEnrolling] = useState(false);

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
          setDealValueInput(data.deal_value ? String(data.deal_value) : "");
          setCloseDateInput(isoToDateInput(data.expected_close_at));
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

  /* Fetch call journal when leadId changes */
  useEffect(() => {
    if (!leadId) { setCalls([]); setCallComment(""); return; }
    let cancelled = false;
    api<LeadCallNote[]>(`/leads/${leadId}/calls`)
      .then((data) => { if (!cancelled) setCalls(data); })
      .catch(() => { /* журнал не критичен для отображения карточки */ });
    return () => { cancelled = true; };
  }, [leadId]);

  /* Fetch org members for the assignee dropdown when drawer opens */
  useEffect(() => {
    if (!leadId) return;
    let cancelled = false;
    api<OrgMember[]>(`/organizations/members`)
      .then((data) => { if (!cancelled) setMembers(data); })
      .catch(() => { /* CRM-секция не критична */ });
    return () => { cancelled = true; };
  }, [leadId]);

  /* Fetch tasks when leadId changes */
  useEffect(() => {
    if (!leadId) { setTasks([]); setNewTaskTitle(""); setNewTaskDue(""); return; }
    let cancelled = false;
    api<LeadTask[]>(`/crm/leads/${leadId}/tasks`)
      .then((data) => { if (!cancelled) setTasks(data); })
      .catch(() => { /* CRM-секция не критична */ });
    return () => { cancelled = true; };
  }, [leadId]);

  /* Fetch activity timeline when leadId changes */
  const refreshActivities = useCallback(async () => {
    if (!leadId) return;
    try {
      const data = await api<LeadActivity[]>(`/crm/leads/${leadId}/activities`);
      setActivities(data);
    } catch { /* CRM-секция не критична */ }
  }, [leadId]);

  useEffect(() => {
    if (!leadId) { setActivities([]); return; }
    let cancelled = false;
    setActivitiesLoading(true);
    api<LeadActivity[]>(`/crm/leads/${leadId}/activities`)
      .then((data) => { if (!cancelled) setActivities(data); })
      .catch(() => { /* CRM-секция не критична */ })
      .finally(() => { if (!cancelled) setActivitiesLoading(false); });
    return () => { cancelled = true; };
  }, [leadId]);

  /* Lazily fetch sequences once when the drawer opens — keep only «active»
     ones (the valid enrollment targets). Reset the picked sequence per lead. */
  useEffect(() => {
    if (!leadId) { setSelectedSeqId(""); return; }
    setSelectedSeqId("");
    if (sequences !== null || seqLoading) return;
    let cancelled = false;
    setSeqLoading(true);
    api<EmailSequence[]>(`/outreach/sequences`)
      .then((data) => { if (!cancelled) setSequences(Array.isArray(data) ? data : []); })
      .catch(() => { if (!cancelled) setSequences([]); /* рассылки не критичны */ })
      .finally(() => { if (!cancelled) setSeqLoading(false); });
    return () => { cancelled = true; };
  }, [leadId, sequences, seqLoading]);

  /* Reset the email composer whenever a different lead opens */
  useEffect(() => {
    setComposerOpen(false);
    setEmailSubject("");
    setEmailBody("");
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

  /* Patch helper. Returns the updated lead on success (null on failure) so
     callers can refresh the timeline only when something actually changed. */
  const patchLead = useCallback(async (
    patch: Partial<Lead> & { mark_contacted?: boolean },
  ): Promise<Lead | null> => {
    if (!leadId) return null;
    setSaving(true);
    try {
      const updated = await api<Lead>(`/leads/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setDetail((prev) => prev ? { ...prev, ...updated } : prev);
      onLeadUpdate?.(leadId, updated);
      // status / assignee / value changes emit timeline events — refresh feed.
      void refreshActivities();
      return updated;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось сохранить");
      return null;
    } finally {
      setSaving(false);
    }
  }, [leadId, onLeadUpdate, refreshActivities]);

  const changeStatus = (newStatus: Lead["status"]) => void patchLead({ status: newStatus });

  /* ── Сделка handlers ──────────────────────────────────────────── */
  const changeAssignee = (userId: string) => {
    void patchLead({ assigned_to_user_id: userId || null });
  };

  const commitDealValue = () => {
    const raw = dealValueInput.replace(/[^\d]/g, "");
    const next = raw ? parseInt(raw, 10) : 0;
    if (next === (detail?.deal_value ?? 0)) {
      // Normalise the field to the canonical representation and bail.
      setDealValueInput(next ? String(next) : "");
      return;
    }
    setDealValueInput(next ? String(next) : "");
    void patchLead({ deal_value: next });
  };

  const commitCloseDate = (value: string) => {
    setCloseDateInput(value);
    const iso = dateInputToIso(value);
    const current = detail?.expected_close_at ?? null;
    // Compare on date granularity to avoid redundant patches.
    if (isoToDateInput(iso) === isoToDateInput(current)) return;
    void patchLead({ expected_close_at: iso });
  };

  /* Enroll THIS lead into the chosen active sequence. Backend skips leads
     without email / opted-out / already enrolled (→ enrolled=0). A 400 means
     the org's email isn't configured — surface its detail verbatim. */
  const enrollInSequence = useCallback(async (seqId: string) => {
    if (!leadId || !seqId) return;
    setEnrolling(true);
    try {
      const res = await api<{ enrolled: number; skipped: number }>(
        `/outreach/sequences/${seqId}/enroll`,
        { method: "POST", body: JSON.stringify({ lead_ids: [leadId] }) },
      );
      if (res.enrolled > 0) toast.success("Добавлен в рассылку");
      else toast("Пропущен (нет email или уже в рассылке)");
      setSelectedSeqId("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось добавить в рассылку");
    } finally {
      setEnrolling(false);
    }
  }, [leadId]);

  /* Record a call: who (current user, attributed server-side) + optional comment.
     Side effects mirror mark_contacted: last_contacted_at=now, new → contacted. */
  const recordCall = useCallback(async (comment: string) => {
    if (!leadId) return;
    setSavingCall(true);
    try {
      const note = await api<LeadCallNote>(`/leads/${leadId}/calls`, {
        method: "POST",
        body: JSON.stringify({ comment: comment.trim() }),
      });
      setCalls((prev) => [note, ...prev]);
      setCallComment("");
      const nowIso = new Date().toISOString();
      setDetail((prev) => prev
        ? { ...prev, last_contacted_at: nowIso, status: prev.status === "new" ? "contacted" : prev.status }
        : prev);
      if (detail) {
        onLeadUpdate?.(leadId, {
          last_contacted_at: nowIso,
          status: detail.status === "new" ? "contacted" : detail.status,
        });
      }
      // The call surfaces in the timeline as kind="call" — refresh the feed.
      void refreshActivities();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось записать звонок");
    } finally {
      setSavingCall(false);
    }
  }, [leadId, detail, onLeadUpdate, refreshActivities]);

  /* ── Direct email handlers ────────────────────────────────────── */

  /* Fill the composer with an AI-drafted subject/body. niche falls back to
     the lead's company when no project context is available here. */
  const aiDraftEmail = useCallback(async () => {
    if (!detail) return;
    setAiDrafting(true);
    try {
      const res = await api<{ subject: string; body: string }>(
        `/outreach/ai/generate-email`,
        {
          method: "POST",
          body: JSON.stringify({ niche: detail.company || "", step_number: 1 }),
        },
      );
      setEmailSubject(res.subject || "");
      setEmailBody(res.body || "");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось сгенерировать черновик");
    } finally {
      setAiDrafting(false);
    }
  }, [detail]);

  /* Send the composed email through the org SMTP. The send surfaces in the
     timeline as kind="email_sent" — refresh the feed on success. */
  const sendEmail = useCallback(async () => {
    if (!leadId) return;
    const subject = emailSubject.trim();
    const body = emailBody.trim();
    if (!subject || !body) {
      toast.error("Заполните тему и текст письма");
      return;
    }
    setSendingEmail(true);
    try {
      await api<{ id: string; status: string }>(`/leads/${leadId}/email`, {
        method: "POST",
        body: JSON.stringify({ subject, body }),
      });
      toast.success("Письмо отправлено");
      setComposerOpen(false);
      setEmailSubject("");
      setEmailBody("");
      // Sending bumps last_contacted_at and may move new → contacted.
      const nowIso = new Date().toISOString();
      setDetail((prev) => prev
        ? { ...prev, last_contacted_at: nowIso, status: prev.status === "new" ? "contacted" : prev.status }
        : prev);
      if (detail) {
        onLeadUpdate?.(leadId, {
          last_contacted_at: nowIso,
          status: detail.status === "new" ? "contacted" : detail.status,
        });
      }
      void refreshActivities();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось отправить письмо");
    } finally {
      setSendingEmail(false);
    }
  }, [leadId, emailSubject, emailBody, detail, onLeadUpdate, refreshActivities]);

  /* One-click channel touch: open the channel app + log a touch (fire-and-forget),
     then refresh the timeline. last_contacted_at / new → contacted updated locally. */
  const channelTouch = useCallback((channel: "call" | "whatsapp" | "telegram") => {
    if (!leadId || !detail) return;
    const digits = phoneDigits(detail.phone);
    if (!digits) return;
    const bare = messengerDigits(detail.phone);
    if (channel === "call") window.open(`tel:${digits}`, "_self");
    else if (channel === "whatsapp") window.open(`https://wa.me/${bare}`, "_blank", "noopener");
    else window.open(`https://t.me/+${bare}`, "_blank", "noopener");

    setTouchingChannel(channel);
    void (async () => {
      try {
        await api<{ ok: boolean }>(`/leads/${leadId}/touch`, {
          method: "POST",
          body: JSON.stringify({ channel }),
        });
        const nowIso = new Date().toISOString();
        setDetail((prev) => prev
          ? { ...prev, last_contacted_at: nowIso, status: prev.status === "new" ? "contacted" : prev.status }
          : prev);
        onLeadUpdate?.(leadId, {
          last_contacted_at: nowIso,
          status: detail.status === "new" ? "contacted" : detail.status,
        });
        void refreshActivities();
      } catch {
        /* touch logging is best-effort — the channel already opened */
      } finally {
        setTouchingChannel(null);
      }
    })();
  }, [leadId, detail, onLeadUpdate, refreshActivities]);

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

  /* ── Задачи handlers ──────────────────────────────────────────── */
  const addTask = useCallback(async () => {
    const title = newTaskTitle.trim();
    if (!leadId || !title) return;
    setAddingTask(true);
    try {
      const created = await api<LeadTask>(`/crm/leads/${leadId}/tasks`, {
        method: "POST",
        body: JSON.stringify({
          title,
          due_at: dateInputToIso(newTaskDue),
        }),
      });
      setTasks((prev) => [...prev, created]);
      setNewTaskTitle("");
      setNewTaskDue("");
      void refreshActivities();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось создать задачу");
    } finally {
      setAddingTask(false);
    }
  }, [leadId, newTaskTitle, newTaskDue, refreshActivities]);

  const toggleTask = useCallback(async (task: LeadTask) => {
    const nextDone = !task.done;
    // Optimistic flip.
    setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, done: nextDone } : t)));
    try {
      const updated = await api<LeadTask>(`/crm/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ done: nextDone }),
      });
      setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)));
      void refreshActivities();
    } catch (err) {
      // Roll back on failure.
      setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, done: task.done } : t)));
      toast.error(err instanceof Error ? err.message : "Не удалось обновить задачу");
    }
  }, [refreshActivities]);

  const deleteTask = useCallback(async (taskId: string) => {
    const prevTasks = tasks;
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    try {
      await api<void>(`/crm/tasks/${taskId}`, { method: "DELETE" });
    } catch (err) {
      setTasks(prevTasks);
      toast.error(err instanceof Error ? err.message : "Не удалось удалить задачу");
    }
  }, [tasks]);

  /* Derive useful values */
  const websiteOk = detail?.website && /^https?:\/\//i.test(detail.website.trim());
  const isAccent = (detail?.score ?? 0) >= 80;
  const activeSequences = (sequences ?? []).filter((s) => s.status === "active");
  const memberName = (uid?: string | null): string => {
    if (!uid) return "";
    const m = members.find((x) => x.user_id === uid);
    return m ? (m.full_name || m.email) : "";
  };

  /* Per-lead engagement, derived from the unified timeline. */
  const engagement = (() => {
    let sent = 0, opened = 0, replies = 0;
    for (const a of activities) {
      if (a.kind === "email_sent") {
        sent += 1;
        if (a.meta?.opened) opened += 1;
      } else if (a.kind === "email_in") {
        replies += 1;
      }
    }
    return { sent, opened, replies };
  })();
  const hasEngagement = engagement.sent > 0 || engagement.replies > 0;
  const phone = phoneDigits(detail?.phone);

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
                      <span
                        className={`badge ${STATUS_BADGE_CLASS[detail.status] ?? ""}`}
                        style={STATUS_BADGE_STYLE[detail.status]}
                      >
                        {STATUS_LABELS[detail.status] ?? detail.status}
                      </span>
                      {detail.source && (
                        <span className="badge badge--source">
                          {SOURCE_LABELS[detail.source] ?? detail.source}
                        </span>
                      )}
                      {hasEngagement && (
                        <span
                          className="chip chip-sans py-0.5 px-1.5 text-[10px]"
                          title="Активность по письмам"
                        >
                          Отправлено {engagement.sent} · Открыто {engagement.opened} · Ответов {engagement.replies}
                        </span>
                      )}
                    </div>
                    {websiteOk ? (
                      <a
                        href={detail.website}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="lead-card__sub mt-1 flex min-w-0 max-w-full items-center gap-1 hover:text-[var(--t-100)]"
                        style={{ textDecoration: "none" }}
                      >
                        <span className="truncate min-w-0">
                          {detail.domain || detail.website.replace(/^https?:\/\//, "").split("/")[0]}
                        </span>
                        <ExternalLink size={10} className="shrink-0 opacity-60" />
                      </a>
                    ) : detail.website && SOURCE_LABELS[detail.source ?? ""] ? (
                      /* Не-http «сайт» (например, maps://) — сырую ссылку не
                         показываем, только откуда лид пришёл. */
                      <span className="lead-card__sub mt-1 block">
                        {SOURCE_LABELS[detail.source ?? ""]}
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
              style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
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

                {/* ── Сделка (CRM) ─────────────────────────── */}
                <section>
                  <div className="eyebrow mb-2">Сделка</div>

                  {/* Stage pills — all 6 pipeline stages */}
                  <div className="mb-3 flex flex-wrap gap-1.5">
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

                  <div className="panel-glass space-y-3 p-3">
                    {/* Assignee */}
                    <label className="block">
                      <span className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--t-40)]">
                        <User size={11} /> Ответственный
                      </span>
                      <select
                        value={detail.assigned_to_user_id ?? ""}
                        disabled={saving}
                        onChange={(e) => changeAssignee(e.target.value)}
                        className="input focus-ring h-9 w-full rounded-lg px-3 text-sm"
                        style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)" }}
                      >
                        <option value="">Не назначен</option>
                        {members.map((m) => (
                          <option key={m.user_id} value={m.user_id}>
                            {m.full_name || m.email}
                          </option>
                        ))}
                      </select>
                    </label>

                    <div className="flex flex-wrap gap-3">
                      {/* Deal value */}
                      <label className="block min-w-0 flex-1" style={{ minWidth: 130 }}>
                        <span className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--t-40)]">
                          <Banknote size={11} /> Сумма, ₽
                        </span>
                        <input
                          type="text"
                          inputMode="numeric"
                          value={dealValueInput}
                          disabled={saving}
                          onChange={(e) => setDealValueInput(e.target.value)}
                          onBlur={commitDealValue}
                          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.target as HTMLInputElement).blur(); } }}
                          placeholder="0"
                          className="input focus-ring mono h-9 w-full rounded-lg px-3 text-sm"
                          style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)" }}
                        />
                      </label>

                      {/* Expected close */}
                      <label className="block min-w-0 flex-1" style={{ minWidth: 130 }}>
                        <span className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--t-40)]">
                          <Calendar size={11} /> Закрытие
                        </span>
                        <input
                          type="date"
                          value={closeDateInput}
                          disabled={saving}
                          onChange={(e) => commitCloseDate(e.target.value)}
                          className="input focus-ring h-9 w-full rounded-lg px-3 text-sm"
                          style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)", colorScheme: "light dark" }}
                        />
                      </label>
                    </div>

                    {!!detail.deal_value && (
                      <div className="text-xs text-[var(--t-48)]">
                        Текущая сумма:{" "}
                        <span className="mono t-72">{formatRub(detail.deal_value)} ₽</span>
                      </div>
                    )}

                    {/* Email sequence enrollment — picker + «В рассылку» */}
                    <div className="border-t pt-3" style={{ borderColor: "var(--line)" }}>
                      <span className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--t-40)]">
                        <Send size={11} /> Рассылка
                      </span>
                      {activeSequences.length > 0 ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <select
                            value={selectedSeqId}
                            disabled={enrolling}
                            onChange={(e) => setSelectedSeqId(e.target.value)}
                            className="input focus-ring h-9 min-w-0 flex-1 rounded-lg px-3 text-sm"
                            style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)", minWidth: 130 }}
                            aria-label="Выбрать рассылку"
                          >
                            <option value="">Выберите рассылку…</option>
                            {activeSequences.map((s) => (
                              <option key={s.id} value={s.id}>{s.name}</option>
                            ))}
                          </select>
                          <button
                            type="button"
                            disabled={enrolling || !selectedSeqId}
                            onClick={() => void enrollInSequence(selectedSeqId)}
                            className="btn btn-ghost focus-ring shrink-0 text-xs"
                            style={{ height: 36, fontSize: 12 }}
                          >
                            {enrolling
                              ? <Loader2 size={13} className="animate-spin" />
                              : <><Send size={12} className="mr-1.5" /> В рассылку</>
                            }
                          </button>
                        </div>
                      ) : (
                        <span className="t-40 text-xs">
                          {seqLoading ? "Загрузка…" : "Нет активных рассылок"}
                        </span>
                      )}
                    </div>
                  </div>
                </section>

                {/* Contacts */}
                <section>
                  <div className="eyebrow mb-2">Контакты</div>
                  <div
                    className="panel-glass divide-y"
                    style={{ "--tw-divide-opacity": 1, divideColor: "var(--line)" } as React.CSSProperties}
                  >
                    {detail.email && (
                      <div className="flex items-center gap-2 px-3 py-2.5">
                        <Mail size={13} className="shrink-0 opacity-48" />
                        <a
                          href={`mailto:${detail.email}`}
                          className="caption min-w-0 flex-1 truncate hover:text-[var(--t-100)]"
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
                          className="caption font-mono min-w-0 flex-1 truncate hover:text-[var(--t-100)]"
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
                          Найдена {pluralN(detail.warehouse.times_seen ?? 1, "раз", "раза", "раз")}
                        </span>
                        {detail.warehouse.inn && (
                          <span className="chip" style={{ fontSize: 10.5 }}>
                            ИНН: {detail.warehouse.inn}
                          </span>
                        )}
                      </div>

                      {(detail.warehouse.first_seen_at || detail.warehouse.last_seen_at) && (
                        <div className="flex flex-wrap gap-3 text-xs text-[var(--t-48)]">
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
                          <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--t-40)]">Ниши</div>
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
                          <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--t-40)]">Источники</div>
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
                      style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)" }}
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
                      background: "var(--surface-input)",
                      border: "1px solid var(--line-2)",
                    }}
                  />
                </section>

                {/* Call journal: who called + comment, history below */}
                <section>
                  <div className="eyebrow mb-2">Обзвон</div>
                  <div className="space-y-2">
                    <textarea
                      value={callComment}
                      onChange={(e) => setCallComment(e.target.value)}
                      disabled={savingCall}
                      rows={2}
                      maxLength={2000}
                      placeholder="Комментарий к звонку: с кем говорили, итог, когда перезвонить..."
                      className="input focus-ring w-full resize-none rounded-xl px-3 py-2.5 text-sm"
                      style={{
                        height: "auto",
                        background: "var(--surface-input)",
                        border: "1px solid var(--line-2)",
                      }}
                    />
                    <button
                      type="button"
                      disabled={savingCall}
                      onClick={() => void recordCall(callComment)}
                      className="btn btn-ghost focus-ring w-full text-xs"
                      style={{ height: 32, fontSize: 11 }}
                    >
                      {savingCall
                        ? <Loader2 size={12} className="animate-spin" />
                        : <><PhoneCall size={12} className="mr-1.5" /> Записать звонок</>
                      }
                    </button>

                    {calls.length > 0 && (
                      <div className="panel-glass divide-y" style={{ divideColor: "var(--line)" } as React.CSSProperties}>
                        {calls.map((c) => (
                          <div key={c.id} className="px-3 py-2.5">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-xs font-medium t-72">{c.user_name || "—"}</span>
                              <span className="t-40 text-[10.5px]">
                                {new Date(c.created_at).toLocaleString("ru-RU", {
                                  day: "2-digit", month: "2-digit", year: "2-digit",
                                  hour: "2-digit", minute: "2-digit",
                                })}
                              </span>
                            </div>
                            {c.comment && (
                              <p className="caption mt-1" style={{ lineHeight: 1.5, overflowWrap: "anywhere" }}>
                                {c.comment}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {calls.length === 0 && (
                      <div className="t-40 text-xs px-1">Звонков пока не было</div>
                    )}
                  </div>
                </section>

                {/* ── Задачи (CRM) ─────────────────────────── */}
                <section>
                  <div className="eyebrow mb-2">Задачи</div>
                  <div className="space-y-2">
                    {tasks.length > 0 && (
                      <div className="panel-glass divide-y" style={{ divideColor: "var(--line)" } as React.CSSProperties}>
                        {tasks.map((t) => {
                          const overdue = !t.done && isOverdue(t.due_at);
                          const assignee = memberName(t.assigned_to_user_id);
                          return (
                            <div key={t.id} className="flex items-start gap-2.5 px-3 py-2.5">
                              <button
                                type="button"
                                onClick={() => void toggleTask(t)}
                                aria-pressed={t.done}
                                aria-label={t.done ? "Снять отметку" : "Отметить выполненной"}
                                className={`cbox focus-ring mt-0.5 shrink-0${t.done ? " checked" : ""}`}
                              >
                                {t.done && <Check size={11} />}
                              </button>
                              <div className="min-w-0 flex-1">
                                <div
                                  className="text-sm"
                                  style={{
                                    color: t.done ? "var(--t-40)" : "var(--t-100)",
                                    textDecoration: t.done ? "line-through" : "none",
                                    overflowWrap: "anywhere",
                                  }}
                                >
                                  {t.title}
                                </div>
                                {(t.due_at || assignee) && (
                                  <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[10.5px]">
                                    {t.due_at && (
                                      <span
                                        className="inline-flex items-center gap-1"
                                        style={{ color: overdue ? "var(--rose)" : "var(--t-48)" }}
                                      >
                                        <Calendar size={10} />
                                        {shortDate(t.due_at)}
                                        {overdue && " · просрочено"}
                                      </span>
                                    )}
                                    {assignee && (
                                      <span className="inline-flex items-center gap-1 text-[var(--t-48)]">
                                        <User size={10} /> {assignee}
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>
                              <button
                                type="button"
                                onClick={() => void deleteTask(t.id)}
                                aria-label="Удалить задачу"
                                title="Удалить задачу"
                                className="focus-ring mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded opacity-40 transition-opacity hover:opacity-80"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Add-task row */}
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="text"
                        value={newTaskTitle}
                        onChange={(e) => setNewTaskTitle(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addTask(); } }}
                        disabled={addingTask}
                        placeholder="Новая задача…"
                        className="input focus-ring h-9 min-w-0 flex-1 rounded-lg px-3 text-sm"
                        style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)", minWidth: 140 }}
                      />
                      <input
                        type="date"
                        value={newTaskDue}
                        onChange={(e) => setNewTaskDue(e.target.value)}
                        disabled={addingTask}
                        aria-label="Срок задачи"
                        className="input focus-ring h-9 rounded-lg px-2.5 text-sm"
                        style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)", width: 140, colorScheme: "light dark" }}
                      />
                      <button
                        type="button"
                        onClick={() => void addTask()}
                        disabled={addingTask || !newTaskTitle.trim()}
                        className="btn btn-ghost focus-ring shrink-0"
                        style={{ height: 36, width: 36, padding: 0 }}
                        aria-label="Добавить задачу"
                        title="Добавить задачу"
                      >
                        {addingTask ? <Loader2 size={14} className="animate-spin" /> : <Plus size={15} />}
                      </button>
                    </div>

                    {tasks.length === 0 && (
                      <div className="t-40 text-xs px-1">Задач пока нет</div>
                    )}
                  </div>
                </section>

                {/* ── Переписка (unified communication hub) ── */}
                <section>
                  <div className="eyebrow mb-2">Переписка</div>

                  {/* Multi-channel one-click row — only when a phone exists */}
                  {phone && (
                    <div className="mb-2.5 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => channelTouch("call")}
                        disabled={touchingChannel === "call"}
                        className="btn btn-ghost focus-ring flex-1"
                        style={{ height: 34, fontSize: 12, minWidth: 96 }}
                        aria-label="Позвонить лиду"
                      >
                        <PhoneCall size={13} className="mr-1.5" style={{ color: "var(--green)" }} />
                        Позвонить
                      </button>
                      <button
                        type="button"
                        onClick={() => channelTouch("whatsapp")}
                        disabled={touchingChannel === "whatsapp"}
                        className="btn btn-ghost focus-ring flex-1"
                        style={{ height: 34, fontSize: 12, minWidth: 96 }}
                        aria-label="Написать в WhatsApp"
                      >
                        <MessageCircle size={13} className="mr-1.5" style={{ color: "var(--green)" }} />
                        WhatsApp
                      </button>
                      <button
                        type="button"
                        onClick={() => channelTouch("telegram")}
                        disabled={touchingChannel === "telegram"}
                        className="btn btn-ghost focus-ring flex-1"
                        style={{ height: 34, fontSize: 12, minWidth: 96 }}
                        aria-label="Написать в Telegram"
                      >
                        <Send size={13} className="mr-1.5" style={{ color: "var(--sky)" }} />
                        Telegram
                      </button>
                    </div>
                  )}

                  {/* Compose / reply by email */}
                  {!composerOpen ? (
                    <button
                      type="button"
                      onClick={() => {
                        setComposerOpen(true);
                        if (!emailSubject && engagement.replies > 0) setEmailSubject("Re: ");
                      }}
                      className="btn btn-brand focus-ring mb-3 w-full"
                      style={{ height: 34, fontSize: 12 }}
                      aria-label={engagement.replies > 0 ? "Ответить письмом" : "Написать письмо"}
                    >
                      <Mail size={13} className="mr-1.5" />
                      {engagement.replies > 0 ? "Ответить" : "Написать письмо"}
                    </button>
                  ) : (
                    <div className="panel-glass mb-3 space-y-2 p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] uppercase tracking-wider text-[var(--t-40)]">
                          {detail.email ? `Письмо → ${detail.email}` : "Письмо"}
                        </span>
                        <button
                          type="button"
                          onClick={() => setComposerOpen(false)}
                          aria-label="Закрыть составление письма"
                          className="focus-ring inline-flex h-5 w-5 items-center justify-center rounded opacity-48 hover:opacity-80"
                        >
                          <X size={13} />
                        </button>
                      </div>
                      <input
                        type="text"
                        value={emailSubject}
                        onChange={(e) => setEmailSubject(e.target.value)}
                        disabled={sendingEmail || aiDrafting}
                        placeholder="Тема письма"
                        className="input focus-ring h-9 w-full rounded-lg px-3 text-sm"
                        style={{ background: "var(--surface-input)", border: "1px solid var(--line-2)" }}
                        aria-label="Тема письма"
                      />
                      <textarea
                        value={emailBody}
                        onChange={(e) => setEmailBody(e.target.value)}
                        disabled={sendingEmail || aiDrafting}
                        rows={6}
                        placeholder="Текст письма…"
                        className="input focus-ring w-full resize-none rounded-xl px-3 py-2.5 text-sm"
                        style={{ height: "auto", background: "var(--surface-input)", border: "1px solid var(--line-2)" }}
                        aria-label="Текст письма"
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => void aiDraftEmail()}
                          disabled={aiDrafting || sendingEmail}
                          className="btn btn-ghost focus-ring text-xs"
                          style={{ height: 34, fontSize: 12 }}
                        >
                          {aiDrafting
                            ? <Loader2 size={13} className="mr-1.5 animate-spin" />
                            : <Sparkles size={13} className="mr-1.5" style={{ color: "var(--mint)" }} />
                          }
                          AI-черновик
                        </button>
                        <button
                          type="button"
                          onClick={() => void sendEmail()}
                          disabled={sendingEmail || aiDrafting || !emailSubject.trim() || !emailBody.trim()}
                          className="btn btn-brand focus-ring ml-auto text-xs"
                          style={{ height: 34, fontSize: 12 }}
                        >
                          {sendingEmail
                            ? <Loader2 size={13} className="mr-1.5 animate-spin" />
                            : <Send size={13} className="mr-1.5" />
                          }
                          Отправить
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Unified communication timeline */}
                  {activitiesLoading && activities.length === 0 ? (
                    <div className="space-y-2">
                      {[70, 90, 55].map((w, i) => (
                        <div key={i} className="skeleton" style={{ width: `${w}%`, height: 12, borderRadius: 6 }} />
                      ))}
                    </div>
                  ) : activities.length > 0 ? (
                    <ol className="relative space-y-3 pl-1">
                      {activities.map((a) => {
                        const isTouch = a.kind === "touch";
                        const isEmailSent = a.kind === "email_sent";
                        const isEmailIn = a.kind === "email_in";
                        const base = activityVisual(a.kind);
                        const tv = isTouch ? touchVisual(a.meta?.channel as string | undefined) : null;
                        const Icon = tv ? tv.Icon : base.Icon;
                        const color = tv ? tv.color : base.color;

                        const subject = (a.meta?.subject as string | undefined) || "";
                        const fromEmail = (a.meta?.from_email as string | undefined) || a.user_name || "";
                        const opens = Number(a.meta?.opens ?? 0);
                        const clicks = Number(a.meta?.clicks ?? 0);
                        const opened = !!a.meta?.opened;
                        const clicked = !!a.meta?.clicked;
                        const failed = a.meta?.status === "failed";

                        return (
                          <li key={a.id} className="flex gap-2.5">
                            <span
                              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              style={{ background: "var(--surface-2)", border: "1px solid var(--line-2)", color }}
                              aria-hidden="true"
                            >
                              <Icon size={11} />
                            </span>
                            <div className="min-w-0 flex-1">
                              {isEmailSent ? (
                                <>
                                  <div className="caption" style={{ color: "var(--t-84)", overflowWrap: "anywhere" }}>
                                    {failed ? "Письмо не отправлено" : "Письмо отправлено"}
                                    {subject && <span className="t-56">: {subject}</span>}
                                  </div>
                                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                    {opened && (
                                      <span className="chip chip-em py-0.5 px-1.5 text-[10px]">
                                        <MailOpen size={9} className="mr-1" />
                                        открыто{opens > 1 ? ` ${opens}` : ""}
                                      </span>
                                    )}
                                    {!opened && !failed && (
                                      <span className="chip chip-sans py-0.5 px-1.5 text-[10px]">
                                        <Eye size={9} className="mr-1 opacity-56" />
                                        не открыто
                                      </span>
                                    )}
                                    {clicked && (
                                      <span className="chip chip-mint py-0.5 px-1.5 text-[10px]">
                                        <MousePointerClick size={9} className="mr-1" />
                                        клик{clicks > 1 ? ` ${clicks}` : ""}
                                      </span>
                                    )}
                                    {failed && (
                                      <span className="chip chip-rs py-0.5 px-1.5 text-[10px]">ошибка</span>
                                    )}
                                  </div>
                                </>
                              ) : isEmailIn ? (
                                <>
                                  <div className="caption" style={{ color: "var(--t-84)", overflowWrap: "anywhere" }}>
                                    Ответ от {fromEmail}
                                    {subject && <span className="t-56">: {subject}</span>}
                                  </div>
                                  {a.text && (
                                    <p
                                      className="caption mt-0.5 italic"
                                      style={{ color: "var(--t-56)", lineHeight: 1.5, overflowWrap: "anywhere" }}
                                    >
                                      «{a.text}»
                                    </p>
                                  )}
                                </>
                              ) : isTouch ? (
                                <div className="caption" style={{ color: "var(--t-84)", overflowWrap: "anywhere" }}>
                                  {tv?.label}
                                  {a.text && <span className="t-56">: {a.text}</span>}
                                </div>
                              ) : (
                                <div className="caption" style={{ color: "var(--t-84)", overflowWrap: "anywhere" }}>
                                  {a.text}
                                </div>
                              )}
                              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10.5px] text-[var(--t-40)]">
                                {a.user_name && !isEmailIn && <span className="t-48">{a.user_name}</span>}
                                {a.user_name && !isEmailIn && <span aria-hidden="true">·</span>}
                                <span>{shortDateTime(a.created_at)}</span>
                              </div>
                            </div>
                          </li>
                        );
                      })}
                    </ol>
                  ) : (
                    <div className="t-40 text-xs px-1">Событий пока нет</div>
                  )}
                </section>
              </div>
            )}
          </div>

          {/* ── FOOTER ─────────────────────────────── */}
          <footer className="drawer-footer">
            {detail && (
              <div className="space-y-3">
                {/* Mark contacted — writes a call-journal entry so the team
                    sees WHO called, not just that someone did. The full
                    6-stage selector now lives in the «Сделка» section above. */}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={savingCall}
                    onClick={() => void recordCall(callComment)}
                    className="btn btn-brand focus-ring flex-1 text-xs"
                    style={{ height: 34, fontSize: 12 }}
                  >
                    {savingCall
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

"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import {
  Plus,
  Pencil,
  Trash2,
  Play,
  Pause,
  Users,
  ChevronDown,
  Mail,
  Loader2,
  Sparkles,
  Inbox,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogMedia,
} from "@/components/ui/alert-dialog";
import { api } from "@/lib/api";
import { useAuthGuard } from "@/lib/hooks";
import type {
  EmailSequence,
  OutreachReply,
  OutreachSettings,
  SequenceEnrollment,
  SequenceStep,
} from "@/lib/types";

const MAX_STEPS = 20;

const PLACEHOLDER_HINT = "Доступные подстановки: {{company}}, {{city}}, {{email}}";

/** Built-in RU templates for instant, no-API step prefilling. */
const STEP_TEMPLATES: { key: string; label: string; subject: string; body: string }[] = [
  {
    key: "cold",
    label: "Холодное первое касание",
    subject: "Сотрудничество с {{company}}",
    body:
      "Здравствуйте!\n\n" +
      "Меня заинтересовала компания {{company}} — мы помогаем подобным компаниям " +
      "привлекать больше клиентов.\n\n" +
      "Будет ли вам удобно созвониться на 10–15 минут на этой неделе, чтобы я коротко " +
      "рассказал, чем можем быть полезны?\n\n" +
      "С уважением",
  },
  {
    key: "followup",
    label: "Follow-up",
    subject: "Re: Сотрудничество с {{company}}",
    body:
      "Здравствуйте!\n\n" +
      "Поднимаю своё прошлое письмо — возможно, оно затерялось.\n\n" +
      "Подскажите, актуален ли для {{company}} вопрос привлечения новых клиентов? " +
      "Если да, я с радостью покажу пару идей именно под вашу сферу.\n\n" +
      "С уважением",
  },
  {
    key: "last",
    label: "Последнее касание",
    subject: "Закрываю вопрос по {{company}}",
    body:
      "Здравствуйте!\n\n" +
      "Не хочу быть навязчивым, поэтому это моё последнее письмо.\n\n" +
      "Если тема привлечения клиентов для {{company}} сейчас неактуальна — просто " +
      "ответьте «не сейчас», и я не побеспокою. Если же интересно — буду рад обсудить.\n\n" +
      "Спасибо за внимание!",
  },
];

const STATUS_META: Record<
  EmailSequence["status"],
  { label: string; chip: string; dot: string }
> = {
  active: { label: "Активна", chip: "chip-mint", dot: "dot-mt" },
  paused: { label: "Пауза", chip: "chip-amber", dot: "dot-am" },
  archived: { label: "Архив", chip: "", dot: "dot-rs" },
};

/** Editable step shape inside the create/edit modal (string delay for inputs). */
type StepDraft = { delay_days: string; subject: string; body: string };

const blankStep = (delay = 0): StepDraft => ({
  delay_days: String(delay),
  subject: "",
  body: "",
});

function toDrafts(steps: SequenceStep[]): StepDraft[] {
  if (!steps.length) return [blankStep(0)];
  return [...steps]
    .sort((a, b) => (a.step_order ?? 0) - (b.step_order ?? 0))
    .map((s) => ({
      delay_days: String(s.delay_days ?? 0),
      subject: s.subject ?? "",
      body: s.body ?? "",
    }));
}

/* ─────────────────────────────────────────────────────────────────────── */

type Tab = "sequences" | "replies";

export default function OutreachPage() {
  const authed = useAuthGuard();
  const [tab, setTab] = useState<Tab>("sequences");
  const [sequences, setSequences] = useState<EmailSequence[]>([]);
  const [settings, setSettings] = useState<OutreachSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal state — null target = create, EmailSequence = edit.
  const [formOpen, setFormOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EmailSequence | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<EmailSequence | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Tracks ids with an in-flight status PATCH so their toggle reflects it.
  const [pending, setPending] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [seqs, cfg] = await Promise.all([
        api<EmailSequence[]>("/outreach/sequences"),
        api<OutreachSettings>("/outreach/settings").catch(() => null),
      ]);
      setSequences(Array.isArray(seqs) ? seqs : []);
      setSettings(cfg);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить рассылки");
      setSequences([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed) void load();
  }, [authed, load]);

  const toggleStatus = async (seq: EmailSequence) => {
    if (pending.has(seq.id) || seq.status === "archived") return;
    const next = seq.status === "active" ? "paused" : "active";
    setPending((prev) => new Set(prev).add(seq.id));
    try {
      const updated = await api<EmailSequence>(`/outreach/sequences/${seq.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      setSequences((prev) => prev.map((s) => (s.id === seq.id ? { ...s, ...updated } : s)));
      toast.success(next === "active" ? "Рассылка возобновлена" : "Рассылка на паузе");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось обновить статус");
    } finally {
      setPending((prev) => {
        const n = new Set(prev);
        n.delete(seq.id);
        return n;
      });
    }
  };

  const removeSequence = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api(`/outreach/sequences/${deleteTarget.id}`, { method: "DELETE" });
      setSequences((prev) => prev.filter((s) => s.id !== deleteTarget.id));
      toast.success("Рассылка удалена");
      setDeleteTarget(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось удалить рассылку");
    } finally {
      setDeleting(false);
    }
  };

  const openCreate = () => {
    setEditTarget(null);
    setFormOpen(true);
  };
  const openEdit = (seq: EmailSequence) => {
    setEditTarget(seq);
    setFormOpen(true);
  };

  const onSaved = (saved: EmailSequence) => {
    setSequences((prev) => {
      const exists = prev.some((s) => s.id === saved.id);
      return exists ? prev.map((s) => (s.id === saved.id ? saved : s)) : [saved, ...prev];
    });
    setFormOpen(false);
    setEditTarget(null);
  };

  if (!authed) {
    return (
      <main className="mx-auto max-w-[920px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <OutreachSkeleton />
      </main>
    );
  }

  return (
    <motion.main
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-[920px] space-y-7 px-4 py-8 sm:px-6 lg:px-10 lg:py-10"
    >
      {/* ── Header ── */}
      <div>
        <div className="eyebrow mb-2">outreach · email</div>
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <h1 className="h1" style={{ fontSize: 44 }}>Рассылки</h1>
          <button onClick={openCreate} className="btn btn-brand mb-1">
            <Plus className="h-3.5 w-3.5" />
            Новая рассылка
          </button>
        </div>
        <p className="t-56 text-[13px] mt-2">
          Автоматические письма-цепочки по лидам: тема, текст и задержки между шагами.
        </p>

        {/* ── Цепочки | Ответы toggle ── */}
        <div className="mt-4 inline-flex gap-1 rounded-full p-1" style={{ background: "var(--surface-1)", border: "1px solid var(--line)" }}>
          <button
            type="button"
            onClick={() => setTab("sequences")}
            className={`seg-btn ${tab === "sequences" ? "!text-[var(--t-100)] !bg-[var(--surface-2)]" : ""}`}
            aria-pressed={tab === "sequences"}
          >
            <Mail className="h-3 w-3" />
            Цепочки
          </button>
          <button
            type="button"
            onClick={() => setTab("replies")}
            className={`seg-btn ${tab === "replies" ? "!text-[var(--t-100)] !bg-[var(--surface-2)]" : ""}`}
            aria-pressed={tab === "replies"}
          >
            <Inbox className="h-3 w-3" />
            Ответы
          </button>
        </div>
      </div>

      {/* ── Mail-not-configured banner ── */}
      {tab === "sequences" && settings && !settings.configured && (
        <div
          className="panel-flat rounded-2xl p-4 flex flex-wrap items-center justify-between gap-3"
          style={{ borderColor: "rgba(251,191,36,0.18)" }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <span className="dot dot-am shrink-0" />
            <p className="text-sm t-84">
              Сначала подключите почту в Настройки → Email-рассылка.
            </p>
          </div>
          <Link
            href="/dashboard/settings"
            className="ghost rounded-full px-4 py-1.5 text-[12.5px] shrink-0"
          >
            Открыть настройки
          </Link>
        </div>
      )}

      {/* ── Replies inbox ── */}
      {tab === "replies" && <RepliesInbox />}

      {/* ── Body ── */}
      {tab === "sequences" && (loading ? (
        <OutreachSkeleton />
      ) : error ? (
        <div className="panel p-8 text-center space-y-4">
          <p className="t-72 text-sm">{error}</p>
          <button className="btn btn-brand" onClick={() => void load()}>
            Повторить
          </button>
        </div>
      ) : sequences.length === 0 ? (
        <div className="empty-state panel-glass elev-1">
          <div className="empty-state__icon">
            <Mail style={{ color: "var(--mint)", width: 28, height: 28 }} />
          </div>
          <h3 className="empty-state__title">Пока нет рассылок</h3>
          <p className="empty-state__body">
            Создайте цепочку писем — БАЗА разошлёт их вашим лидам по расписанию и
            покажет, кто открыл и кто ответил.
          </p>
          <button onClick={openCreate} className="brand rounded-full px-5 py-2.5 text-[13.5px] inline-flex items-center gap-2 mt-2">
            <Plus className="h-3.5 w-3.5" />
            Создать рассылку
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {sequences.map((seq, idx) => (
            <SequenceCard
              key={seq.id}
              seq={seq}
              index={idx}
              busy={pending.has(seq.id)}
              onToggle={() => void toggleStatus(seq)}
              onEdit={() => openEdit(seq)}
              onDelete={() => setDeleteTarget(seq)}
            />
          ))}
        </div>
      ))}

      {/* ── Create / edit modal ── */}
      <SequenceFormDialog
        open={formOpen}
        target={editTarget}
        onOpenChange={(open) => {
          setFormOpen(open);
          if (!open) setEditTarget(null);
        }}
        onSaved={onSaved}
      />

      {/* ── Delete confirm ── */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogMedia className="bg-destructive/10">
              <Trash2 className="h-5 w-5 text-destructive" />
            </AlertDialogMedia>
            <AlertDialogTitle>Удалить рассылку?</AlertDialogTitle>
            <AlertDialogDescription>
              Рассылка &laquo;{deleteTarget?.name}&raquo; и её расписание отправок будут
              удалены безвозвратно.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction variant="destructive" disabled={deleting} onClick={removeSequence}>
              {deleting ? "Удаляем..." : "Удалить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </motion.main>
  );
}

/* ── Sequence card ─────────────────────────────────────────────────────── */

function SequenceCard({
  seq,
  index,
  busy,
  onToggle,
  onEdit,
  onDelete,
}: {
  seq: EmailSequence;
  index: number;
  busy: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = STATUS_META[seq.status];
  const stepCount = seq.steps?.length ?? 0;
  const stats = seq.stats;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay: Math.min(index * 0.04, 0.24) }}
      className="lead-card group relative"
      style={busy ? { opacity: 0.6 } : undefined}
    >
      <div className="lead-card__row">
        <span className={`dot ${meta.dot} shrink-0`} />

        <div className="min-w-0 flex-1">
          <div className="lead-card__row" style={{ gap: 8, marginBottom: 4 }}>
            <span className="lead-card__name truncate min-w-0">{seq.name}</span>
            <span className={`chip ${meta.chip} shrink-0`}>{meta.label}</span>
          </div>

          <div className="lead-card__meta">
            <span>{stepCount} {pluralSteps(stepCount)}</span>
          </div>

          {/* Compact stats row */}
          <div className="lead-card__sub">
            <span className="flex items-center gap-3 flex-wrap">
              <Stat label="В работе" value={stats?.active ?? 0} tone="mint" />
              <span className="t-28">·</span>
              <Stat label="Отправлено" value={stats?.sent_messages ?? 0} />
              <span className="t-28">·</span>
              <Stat label="Ответили" value={stats?.replied ?? 0} tone="mint" />
              <span className="t-28">·</span>
              <Stat label="Отписались" value={stats?.unsubscribed ?? 0} tone="rose" />
            </span>
          </div>

          {/* Tracking stats row */}
          <div className="lead-card__sub">
            <span className="flex items-center gap-3 flex-wrap">
              <Stat label="Открыто" value={stats?.opened ?? 0} />
              <span className="t-28">·</span>
              <Stat label="Клики" value={stats?.clicked ?? 0} />
              <span className="t-28">·</span>
              <Stat label="Ответы" value={stats?.replies ?? 0} tone="mint" />
            </span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 shrink-0">
          {seq.status !== "archived" && (
            <button
              type="button"
              className="btn-icon"
              onClick={onToggle}
              disabled={busy}
              aria-label={seq.status === "active" ? "Поставить на паузу" : "Возобновить"}
              title={seq.status === "active" ? "Пауза" : "Возобновить"}
            >
              {seq.status === "active" ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            </button>
          )}
          <button type="button" className="btn-icon" onClick={onEdit} aria-label="Редактировать" title="Редактировать">
            <Pencil className="h-3 w-3" />
          </button>
          <button
            type="button"
            className="btn-icon hover:!text-[var(--rose)]"
            onClick={onDelete}
            aria-label="Удалить"
            title="Удалить"
          >
            <Trash2 className="h-3 w-3" />
          </button>
          <button
            type="button"
            className={`btn-icon ${expanded ? "!text-[var(--t-100)]" : ""}`}
            onClick={() => setExpanded((v) => !v)}
            aria-label="Получатели"
            aria-expanded={expanded}
            title="Получатели"
          >
            <Users className="h-3 w-3" />
            <ChevronDown
              className="h-3 w-3 ml-0.5 transition-transform"
              style={{ transform: expanded ? "rotate(180deg)" : "none" }}
            />
          </button>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="enrollments"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22 }}
            className="overflow-hidden"
          >
            <EnrollmentsPanel sequenceId={seq.id} />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "mint" | "rose" }) {
  const color = tone === "mint" ? "var(--mint)" : tone === "rose" ? "var(--rose)" : "var(--t-84)";
  return (
    <span>
      <span className="t-40">{label}: </span>
      <span className="tnum" style={{ color }}>{value.toLocaleString("ru-RU")}</span>
    </span>
  );
}

/* ── Replies inbox ─────────────────────────────────────────────────────── */

function RepliesInbox() {
  const [rows, setRows] = useState<OutreachReply[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    try {
      const data = await api<OutreachReply[]>("/outreach/replies");
      setRows(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить ответы");
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (rows === null) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-[88px] animate-pulse rounded-2xl border border-[var(--line)] bg-[var(--surface-1)]"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel p-8 text-center space-y-4">
        <p className="t-72 text-sm">{error}</p>
        <button className="btn btn-brand" onClick={() => void load()}>
          Повторить
        </button>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="empty-state panel-glass elev-1">
        <div className="empty-state__icon">
          <Inbox style={{ color: "var(--mint)", width: 28, height: 28 }} />
        </div>
        <h3 className="empty-state__title">Ответов пока нет</h3>
        <p className="empty-state__body">
          Когда лиды ответят на письма из ваших цепочек, их ответы появятся здесь.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {rows.map((r, idx) => (
        <motion.div
          key={r.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, delay: Math.min(idx * 0.04, 0.24) }}
          className="lead-card"
        >
          <div className="flex items-start gap-3">
            <span className="dot dot-mt shrink-0 mt-1.5" />
            <div className="min-w-0 flex-1">
              <div className="lead-card__row" style={{ gap: 8, marginBottom: 2 }}>
                <span className="lead-card__name truncate min-w-0">
                  {r.lead_company || r.from_email || "—"}
                </span>
                <span className="mono t-40 text-[10.5px] shrink-0">{shortDate(r.received_at)}</span>
              </div>
              <div className="mono t-48 text-[11px] truncate">{r.from_email}</div>
              {r.subject && (
                <div className="text-[13px] t-84 mt-1.5 truncate">{r.subject}</div>
              )}
              {r.snippet && (
                <p
                  className="t-56 text-[12.5px] mt-1 leading-relaxed"
                  style={{
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                  }}
                >
                  {r.snippet}
                </p>
              )}
            </div>
          </div>
        </motion.div>
      ))}
    </div>
  );
}

/* ── Recipients (enrollments) panel ────────────────────────────────────── */

function EnrollmentsPanel({ sequenceId }: { sequenceId: string }) {
  const [rows, setRows] = useState<SequenceEnrollment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await api<SequenceEnrollment[]>(`/outreach/sequences/${sequenceId}/enrollments`);
      setRows(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить получателей");
      setRows([]);
    }
  }, [sequenceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const stop = async (enr: SequenceEnrollment) => {
    if (stopping.has(enr.id)) return;
    setStopping((prev) => new Set(prev).add(enr.id));
    try {
      await api(`/outreach/enrollments/${enr.id}/stop`, { method: "POST", body: JSON.stringify({}) });
      setRows((prev) =>
        prev ? prev.map((r) => (r.id === enr.id ? { ...r, status: "stopped" } : r)) : prev
      );
      toast.success("Отправка остановлена");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось остановить");
    } finally {
      setStopping((prev) => {
        const n = new Set(prev);
        n.delete(enr.id);
        return n;
      });
    }
  };

  return (
    <div className="mt-3 pt-3 border-t border-[var(--line)]">
      {rows === null ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-9 animate-pulse rounded-lg bg-[var(--surface-1)]" />
          ))}
        </div>
      ) : error ? (
        <div className="flex items-center justify-between gap-3">
          <p className="t-72 text-[12.5px]">{error}</p>
          <button className="seg-btn" onClick={() => void load()}>Повторить</button>
        </div>
      ) : rows.length === 0 ? (
        <p className="t-48 text-[12.5px] py-1">Пока никого не добавили в эту рассылку.</p>
      ) : (
        <div className="flex flex-col gap-1">
          {rows.map((enr) => {
            const active = isActiveEnrollment(enr.status);
            return (
              <div
                key={enr.id}
                className="flex items-center gap-3 py-1.5 rounded-lg"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] text-[var(--t-84)] truncate">
                    {enr.lead_company || enr.to_email || "—"}
                  </div>
                  <div className="mono t-40 text-[10.5px] truncate">{enr.to_email}</div>
                </div>
                <span className="mono-cap t-48 text-[10px] shrink-0">шаг {enr.current_step}</span>
                <span className="chip shrink-0" style={{ padding: "2px 8px", fontSize: "9.5px" }}>
                  {enrollmentStatusLabel(enr.status)}
                </span>
                {active && (
                  <button
                    type="button"
                    className="seg-btn shrink-0"
                    onClick={() => void stop(enr)}
                    disabled={stopping.has(enr.id)}
                  >
                    {stopping.has(enr.id) ? "…" : "Стоп"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Create / edit modal ───────────────────────────────────────────────── */

function SequenceFormDialog({
  open,
  target,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  target: EmailSequence | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (seq: EmailSequence) => void;
}) {
  const [name, setName] = useState("");
  const [steps, setSteps] = useState<StepDraft[]>([blankStep(0)]);
  const [saving, setSaving] = useState(false);

  // Re-seed the form whenever the dialog opens or the target changes.
  useEffect(() => {
    if (open) {
      setName(target?.name ?? "");
      setSteps(target ? toDrafts(target.steps) : [blankStep(0)]);
      setSaving(false);
    }
  }, [open, target]);

  const updateStep = (idx: number, patch: Partial<StepDraft>) =>
    setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));

  const addStep = () =>
    setSteps((prev) => (prev.length >= MAX_STEPS ? prev : [...prev, blankStep(3)]));

  const removeStep = (idx: number) =>
    setSteps((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error("Введите название рассылки");
      return;
    }
    if (steps.length < 1) {
      toast.error("Добавьте хотя бы один шаг");
      return;
    }
    const cleaned = steps.map((s) => ({
      delay_days: Math.max(0, Math.floor(Number(s.delay_days) || 0)),
      subject: s.subject.trim(),
      body: s.body.trim(),
    }));
    const bad = cleaned.findIndex((s) => !s.subject || !s.body);
    if (bad !== -1) {
      toast.error(`Шаг ${bad + 1}: заполните тему и текст письма`);
      return;
    }

    setSaving(true);
    try {
      let saved: EmailSequence;
      if (target) {
        saved = await api<EmailSequence>(`/outreach/sequences/${target.id}`, {
          method: "PATCH",
          body: JSON.stringify({ name: trimmedName, steps: cleaned }),
        });
      } else {
        saved = await api<EmailSequence>("/outreach/sequences", {
          method: "POST",
          body: JSON.stringify({ name: trimmedName, steps: cleaned }),
        });
      }
      toast.success(target ? "Рассылка обновлена" : "Рассылка создана");
      onSaved(saved);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось сохранить рассылку");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{target ? "Редактировать рассылку" : "Новая рассылка"}</DialogTitle>
          <DialogDescription>
            Цепочка писем с задержками. Используйте подстановки {"{{company}}"}, {"{{city}}"}, {"{{email}}"}.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="grid gap-4 px-1 sm:px-0">
          <div className="grid gap-1.5">
            <Label htmlFor="seq-name">Название</Label>
            <Input
              id="seq-name"
              required
              value={name}
              maxLength={140}
              placeholder="Например: Холодное знакомство"
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="grid gap-3">
            <div className="flex items-center justify-between">
              <Label>Шаги ({steps.length})</Label>
              <span className="mono-cap t-40 text-[10px]">макс. {MAX_STEPS}</span>
            </div>

            {steps.map((step, idx) => (
              <StepEditor
                key={idx}
                idx={idx}
                step={step}
                canRemove={steps.length > 1}
                projectId={target?.project_id ?? null}
                onChange={(patch) => updateStep(idx, patch)}
                onRemove={() => removeStep(idx)}
              />
            ))}

            <button
              type="button"
              onClick={addStep}
              disabled={steps.length >= MAX_STEPS}
              className="px-4 py-3 flex items-center justify-center gap-2 t-56 hover:t-72 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ border: "1px dashed var(--line-2)", borderRadius: 14 }}
            >
              <Plus className="h-3.5 w-3.5" />
              <span className="text-[13px]">Добавить шаг</span>
            </button>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Сохраняем...
                </>
              ) : target ? (
                "Сохранить"
              ) : (
                "Создать"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ── Single step editor (with templates + AI generation) ───────────────── */

function StepEditor({
  idx,
  step,
  canRemove,
  projectId,
  onChange,
  onRemove,
}: {
  idx: number;
  step: StepDraft;
  canRemove: boolean;
  projectId?: string | null;
  onChange: (patch: Partial<StepDraft>) => void;
  onRemove: () => void;
}) {
  const [aiOpen, setAiOpen] = useState(false);
  const [niche, setNiche] = useState("");
  const [goal, setGoal] = useState("");
  const [generating, setGenerating] = useState(false);

  const applyTemplate = (key: string) => {
    if (!key) return;
    const tpl = STEP_TEMPLATES.find((t) => t.key === key);
    if (!tpl) return;
    onChange({ subject: tpl.subject, body: tpl.body });
    toast.success(`Шаблон «${tpl.label}» применён`);
  };

  const generate = async () => {
    const trimmedNiche = niche.trim();
    if (!trimmedNiche) {
      toast.error("Укажите нишу / о чём письмо");
      return;
    }
    setGenerating(true);
    try {
      const res = await api<{ subject: string; body: string }>("/outreach/ai/generate-email", {
        method: "POST",
        body: JSON.stringify({
          ...(projectId ? { project_id: projectId } : {}),
          niche: trimmedNiche,
          ...(goal.trim() ? { goal: goal.trim() } : {}),
          step_number: idx + 1,
        }),
      });
      onChange({ subject: res.subject ?? "", body: res.body ?? "" });
      toast.success("Письмо сгенерировано");
      setAiOpen(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось сгенерировать письмо");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div
      className="rounded-2xl border border-[var(--line-2)] p-3 grid gap-2.5"
      style={{ background: "var(--surface-1)" }}
    >
      <div className="flex items-center justify-between">
        <span className="mono-cap t-56 text-[11px]">Шаг {idx + 1}</span>
        {canRemove && (
          <button
            type="button"
            className="btn-icon hover:!text-[var(--rose)]"
            onClick={onRemove}
            aria-label={`Удалить шаг ${idx + 1}`}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>

      {/* Template dropdown + AI toggle */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          className="input text-[12px] max-w-[200px]"
          value=""
          onChange={(e) => {
            applyTemplate(e.target.value);
            e.target.value = "";
          }}
          aria-label="Готовый шаблон"
        >
          <option value="">Шаблон…</option>
          {STEP_TEMPLATES.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="seg-btn"
          onClick={() => setAiOpen((v) => !v)}
          aria-expanded={aiOpen}
        >
          <Sparkles className="h-3 w-3" />
          Сгенерировать с AI
        </button>
      </div>

      <AnimatePresence initial={false}>
        {aiOpen && (
          <motion.div
            key="ai"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div
              className="grid gap-2 rounded-xl p-2.5"
              style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
            >
              <Input
                value={niche}
                maxLength={200}
                placeholder="Ниша / о чём (напр. студия веб-дизайна)"
                onChange={(e) => setNiche(e.target.value)}
                className="text-[12.5px]"
              />
              <Input
                value={goal}
                maxLength={200}
                placeholder="Цель (необязательно, напр. записать на созвон)"
                onChange={(e) => setGoal(e.target.value)}
                className="text-[12.5px]"
              />
              <div className="flex justify-end">
                <button
                  type="button"
                  className="btn btn-brand"
                  onClick={() => void generate()}
                  disabled={generating}
                >
                  {generating ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Генерируем…
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-3.5 w-3.5" />
                      Сгенерировать
                    </>
                  )}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="grid gap-1.5">
        <Label htmlFor={`step-${idx}-delay`} className="text-xs text-muted-foreground">
          Задержка (дней){idx === 0 ? " · 0 = сразу" : ""}
        </Label>
        <Input
          id={`step-${idx}-delay`}
          type="number"
          min={0}
          max={365}
          value={step.delay_days}
          onChange={(e) => onChange({ delay_days: e.target.value })}
          className="max-w-[140px]"
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={`step-${idx}-subject`} className="text-xs text-muted-foreground">
          Тема
        </Label>
        <Input
          id={`step-${idx}-subject`}
          value={step.subject}
          maxLength={300}
          placeholder="Тема письма"
          onChange={(e) => onChange({ subject: e.target.value })}
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={`step-${idx}-body`} className="text-xs text-muted-foreground">
          Текст письма
        </Label>
        <Textarea
          id={`step-${idx}-body`}
          value={step.body}
          rows={4}
          placeholder={"Здравствуйте!\n\nМеня заинтересовала компания {{company}} из города {{city}}…"}
          onChange={(e) => onChange({ body: e.target.value })}
          className="min-h-[96px] rounded-xl px-3 py-2.5 leading-relaxed"
        />
        <p className="mono-cap t-40 text-[10px]">{PLACEHOLDER_HINT}</p>
      </div>
    </div>
  );
}

/* ── Skeleton ──────────────────────────────────────────────────────────── */

function OutreachSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-[96px] animate-pulse rounded-2xl border border-[var(--line)] bg-[var(--surface-1)]"
        />
      ))}
    </div>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

/** Short RU date for reply timestamps, e.g. "20 июн" or "20 июн 2025". */
function shortDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

function pluralSteps(n: number): string {
  const rule = new Intl.PluralRules("ru").select(n);
  if (rule === "one") return "шаг";
  if (rule === "few") return "шага";
  return "шагов";
}

/** Enrollment statuses where the lead is still mid-flight and can be stopped. */
function isActiveEnrollment(status: string): boolean {
  return status === "active" || status === "scheduled" || status === "pending";
}

const ENROLLMENT_STATUS_LABEL: Record<string, string> = {
  active: "В работе",
  scheduled: "Запланирован",
  pending: "Ожидает",
  completed: "Завершён",
  replied: "Ответил",
  unsubscribed: "Отписался",
  bounced: "Недоставлено",
  stopped: "Остановлен",
  failed: "Ошибка",
};

function enrollmentStatusLabel(status: string): string {
  return ENROLLMENT_STATUS_LABEL[status] ?? status;
}

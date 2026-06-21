"use client";

import { useState } from "react";
import { Loader2, UserPlus } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { getOrgId, getToken } from "@/lib/auth";
import type { Lead, LeadStatus, OrgMember } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

const STATUS_OPTIONS: { value: LeadStatus; label: string }[] = [
  { value: "new", label: "Новый" },
  { value: "contacted", label: "Связались" },
  { value: "qualified", label: "Квалифицирован" },
  { value: "proposal", label: "КП отправлено" },
  { value: "won", label: "Сделка" },
  { value: "rejected", label: "Отказ" },
];
const STATUS_LABELS: Record<string, string> = Object.fromEntries(
  STATUS_OPTIONS.map((o) => [o.value, o.label]),
);

// Sentinel for "no assignee" inside the Select (Base UI needs a non-empty value).
const NO_ASSIGNEE = "__none__";

type Props = {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  members?: OrgMember[];
  onCreated: () => void;
  // Optional — opens the existing lead's drawer on a 409 duplicate.
  onOpenLead?: (leadId: string) => void;
};

type DuplicateState = { id: string } | null;

export function AddLeadDialog({
  projectId,
  open,
  onOpenChange,
  members = [],
  onCreated,
  onOpenLead,
}: Props) {
  const [company, setCompany] = useState("");
  const [city, setCity] = useState("");
  const [website, setWebsite] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<LeadStatus>("new");
  const [dealValue, setDealValue] = useState("");
  const [assignee, setAssignee] = useState(NO_ASSIGNEE);
  const [tagsInput, setTagsInput] = useState("");
  const [notes, setNotes] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [duplicate, setDuplicate] = useState<DuplicateState>(null);

  const reset = () => {
    setCompany("");
    setCity("");
    setWebsite("");
    setEmail("");
    setPhone("");
    setAddress("");
    setStatus("new");
    setDealValue("");
    setAssignee(NO_ASSIGNEE);
    setTagsInput("");
    setNotes("");
    setDuplicate(null);
  };

  const handleOpenChange = (next: boolean) => {
    if (submitting) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const submit = async () => {
    const trimmedCompany = company.trim();
    if (!trimmedCompany) {
      toast.error("Укажите название компании");
      return;
    }
    setSubmitting(true);
    setDuplicate(null);

    const tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    const dv = Number.parseInt(dealValue, 10);

    const body: Record<string, unknown> = {
      company: trimmedCompany,
      city: city.trim(),
      website: website.trim(),
      email: email.trim(),
      phone: phone.trim(),
      address: address.trim(),
      notes: notes.trim(),
      tags,
      status,
      deal_value: Number.isFinite(dv) && dv > 0 ? dv : 0,
    };
    if (assignee !== NO_ASSIGNEE) body.assigned_to_user_id = assignee;

    // Direct fetch (not the `api` helper) so the 409 body's nested
    // `existing_lead_id` is readable — `api` collapses `detail` into an Error.
    try {
      const token = getToken();
      const orgId = getOrgId();
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;
      if (orgId) headers["X-Org-Id"] = orgId;

      const res = await fetch(`${API_URL}/leads/project/${projectId}`, {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify(body),
      });

      if (res.status === 409) {
        const payload = (await res.json().catch(() => null)) as
          | { detail?: { existing_lead_id?: string } | string }
          | null;
        const existingId =
          payload && typeof payload.detail === "object"
            ? payload.detail.existing_lead_id
            : undefined;
        setDuplicate(existingId ? { id: existingId } : { id: "" });
        return;
      }

      if (!res.ok) {
        const err = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        const msg =
          err && typeof err.detail === "string" ? err.detail : `Ошибка запроса (${res.status})`;
        throw new Error(msg);
      }

      const created = (await res.json()) as Lead;
      toast.success(`Лид «${created.company}» добавлен`);
      reset();
      onOpenChange(false);
      onCreated();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось добавить лид");
    } finally {
      setSubmitting(false);
    }
  };

  const openDuplicate = () => {
    if (duplicate?.id && onOpenLead) {
      onOpenLead(duplicate.id);
      reset();
      onOpenChange(false);
    } else if (duplicate?.id) {
      toast.info(`Существующий лид: ${duplicate.id}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus size={16} /> Добавить лид
          </DialogTitle>
          <DialogDescription>
            Внесите свою компанию вручную. Обязательно только название.
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          className="space-y-3"
        >
          <div className="space-y-1.5">
            <Label htmlFor="al-company">
              Компания <span className="text-status-offline">*</span>
            </Label>
            <Input
              id="al-company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="ООО «Ромашка»"
              maxLength={180}
              autoFocus
              required
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="al-city">Город</Label>
              <Input
                id="al-city"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                placeholder="Москва"
                maxLength={120}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="al-website">Сайт</Label>
              <Input
                id="al-website"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                placeholder="example.ru"
                maxLength={300}
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="al-email">Email</Label>
              <Input
                id="al-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="info@example.ru"
                maxLength={255}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="al-phone">Телефон</Label>
              <Input
                id="al-phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+7 900 000-00-00"
                maxLength={80}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="al-address">Адрес</Label>
            <Input
              id="al-address"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="ул. Ленина, 1"
              maxLength={300}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Статус</Label>
              <Select value={status} onValueChange={(v: string | null) => { if (v) setStatus(v as LeadStatus); }}>
                <SelectTrigger className="w-full" aria-label="Статус лида">
                  <SelectValue>
                    {(v: string | null) => (v ? STATUS_LABELS[v] ?? v : "Новый")}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="al-value">Сумма сделки, ₽</Label>
              <Input
                id="al-value"
                type="number"
                min={0}
                value={dealValue}
                onChange={(e) => setDealValue(e.target.value)}
                placeholder="0"
              />
            </div>
          </div>

          {members.length > 0 && (
            <div className="space-y-1.5">
              <Label>Ответственный</Label>
              <Select value={assignee} onValueChange={(v: string | null) => { if (v) setAssignee(v); }}>
                <SelectTrigger className="w-full" aria-label="Ответственный">
                  <SelectValue>
                    {(v: string | null) => {
                      if (!v || v === NO_ASSIGNEE) return "Не назначен";
                      const m = members.find((x) => x.user_id === v);
                      return m ? m.full_name || m.email : "Ответственный";
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_ASSIGNEE}>Не назначен</SelectItem>
                  {members.map((m) => (
                    <SelectItem key={m.user_id} value={m.user_id}>
                      {m.full_name || m.email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="al-tags">Теги</Label>
            <Input
              id="al-tags"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="через запятую: vip, входящий"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="al-notes">Заметки</Label>
            <Textarea
              id="al-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Контекст, кто принимает решение…"
              rows={3}
            />
          </div>

          {duplicate && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-status-warning/30 bg-status-warning/10 px-3 py-2 text-sm">
              <span className="text-[var(--t-72)]">Такой лид уже есть</span>
              {duplicate.id && (
                <Button type="button" size="xs" variant="secondary" onClick={openDuplicate}>
                  Открыть
                </Button>
              )}
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" disabled={submitting} onClick={() => handleOpenChange(false)}>
              Отмена
            </Button>
            <Button type="submit" variant="brand" disabled={submitting || !company.trim()}>
              {submitting ? (
                <><Loader2 size={14} className="animate-spin" /> Сохраняем…</>
              ) : (
                "Добавить лид"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

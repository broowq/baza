"use client";

import { useRef, useState } from "react";
import { Download, FileUp, Loader2, Upload } from "lucide-react";
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
import { apiUpload } from "@/lib/api";
import type { ImportResult } from "@/lib/types";

// Human labels for the auto-detected field keys returned by the backend.
const FIELD_LABELS: Record<string, string> = {
  company: "Компания",
  city: "Город",
  website: "Сайт",
  email: "Email",
  phone: "Телефон",
  address: "Адрес",
  notes: "Заметки",
};

const TEMPLATE_HEADERS = ["Компания", "Город", "Сайт", "Email", "Телефон", "Адрес"];

function pluralLeads(n: number): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "лид";
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return "лида";
  return "лидов";
}

type Props = {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: () => void;
};

export function ImportLeadsDialog({ projectId, open, onOpenChange, onImported }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const busy = previewing || importing;

  const reset = () => {
    setFile(null);
    setPreview(null);
    setPreviewing(false);
    setImporting(false);
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleOpenChange = (next: boolean) => {
    if (busy) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const runImport = async (picked: File, dryRun: boolean): Promise<ImportResult> => {
    const fd = new FormData();
    fd.append("file", picked);
    return apiUpload<ImportResult>(
      `/leads/project/${projectId}/import?dry_run=${dryRun ? "true" : "false"}`,
      fd,
    );
  };

  const onPick = async (picked: File | null) => {
    setError(null);
    setPreview(null);
    if (!picked) {
      setFile(null);
      return;
    }
    const lower = picked.name.toLowerCase();
    if (!lower.endsWith(".csv") && !lower.endsWith(".xlsx")) {
      setError("Поддерживаются только файлы .csv или .xlsx");
      setFile(null);
      return;
    }
    setFile(picked);
    setPreviewing(true);
    try {
      const res = await runImport(picked, true);
      setPreview(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось прочитать файл");
    } finally {
      setPreviewing(false);
    }
  };

  const commit = async () => {
    if (!file || !preview) return;
    setImporting(true);
    setError(null);
    try {
      const res = await runImport(file, false);
      toast.success(
        `Добавлено ${res.created} ${pluralLeads(res.created)} (${res.duplicates} дубликатов пропущено)`,
      );
      reset();
      onOpenChange(false);
      onImported();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось импортировать");
    } finally {
      setImporting(false);
    }
  };

  const downloadTemplate = () => {
    // BOM so Excel opens UTF-8 Cyrillic correctly.
    const csv = "﻿" + TEMPLATE_HEADERS.join(",") + "\n";
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "leads-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const mappedEntries = preview ? Object.entries(preview.detected_columns) : [];

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileUp size={16} /> Импорт лидов
          </DialogTitle>
          <DialogDescription>
            Загрузите CSV или XLSX. Колонки распознаются автоматически по заголовкам.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* File picker */}
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx"
              disabled={busy}
              onChange={(e) => void onPick(e.target.files?.[0] ?? null)}
              className="block w-full max-w-full text-sm text-[var(--t-72)] file:mr-3 file:cursor-pointer file:rounded-full file:border-0 file:bg-[var(--surface-3)] file:px-3.5 file:py-1.5 file:text-sm file:font-medium file:text-[var(--t-100)] hover:file:bg-[var(--surface-active)] disabled:opacity-50"
              aria-label="Файл для импорта"
            />
          </div>

          <button
            type="button"
            onClick={downloadTemplate}
            className="inline-flex items-center gap-1.5 text-sm text-[var(--t-72)] underline decoration-[var(--t-28)] underline-offset-2 hover:text-[var(--t-100)] hover:decoration-[var(--t-100)]"
          >
            <Download size={13} /> Скачать шаблон CSV
          </button>

          {previewing && (
            <div className="flex items-center gap-2 text-sm text-[var(--t-72)]">
              <Loader2 size={14} className="animate-spin" /> Читаем файл…
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-status-offline/30 bg-status-offline/10 px-3 py-2 text-sm text-status-offline">
              {error}
            </div>
          )}

          {/* Preview */}
          {preview && !previewing && (
            <div className="space-y-3">
              {/* Detected column mapping */}
              <div className="space-y-1.5">
                <div className="eyebrow">Распознанные колонки</div>
                {mappedEntries.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {mappedEntries.map(([field, header]) => (
                      <span
                        key={field}
                        className="inline-flex items-center gap-1 rounded-full border border-[var(--line-2)] bg-[var(--surface-3)] px-2.5 py-1 text-xs"
                      >
                        <span className="font-medium text-[var(--t-100)]">
                          {FIELD_LABELS[field] ?? field}
                        </span>
                        <span className="text-[var(--t-40)]">←</span>
                        <span className="text-[var(--t-56)]">{header}</span>
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-status-offline">
                    Не найдено ни одной колонки. Проверьте заголовки файла.
                  </p>
                )}
                {preview.unmapped_headers.length > 0 && (
                  <p className="text-xs text-[var(--t-48)]">
                    Пропущены колонки: {preview.unmapped_headers.join(", ")}
                  </p>
                )}
              </div>

              {/* Counts */}
              <div className="flex flex-wrap gap-4 text-sm">
                <span>
                  Будет добавлено:{" "}
                  <strong className="tnum text-[var(--mint)]">{preview.created}</strong>
                </span>
                <span className="text-[var(--t-72)]">
                  Дубликатов: <strong className="tnum">{preview.duplicates}</strong>
                </span>
                {preview.errors.length > 0 && (
                  <span className="text-status-offline">
                    Ошибок: <strong className="tnum">{preview.errors.length}</strong>
                  </span>
                )}
              </div>

              {/* Errors */}
              {preview.errors.length > 0 && (
                <div className="max-h-32 space-y-1 overflow-y-auto rounded-lg border border-[var(--line)] bg-[var(--surface-1)] p-2 text-xs">
                  {preview.errors.map((err) => (
                    <div key={err.row} className="text-[var(--t-72)]">
                      <span className="font-mono text-[var(--t-48)]">строка {err.row}:</span>{" "}
                      {err.error}
                    </div>
                  ))}
                </div>
              )}

              {/* Sample table */}
              {preview.sample.length > 0 && (
                <div className="overflow-hidden rounded-lg border border-[var(--line)]">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-[var(--surface-1)] text-[var(--t-48)]">
                      <tr>
                        <th className="px-3 py-2 font-medium">Компания</th>
                        <th className="px-3 py-2 font-medium">Город</th>
                        <th className="px-3 py-2 font-medium">Email</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.sample.map((lead, i) => (
                        <tr key={i} className="border-t border-[var(--line)]">
                          <td className="px-3 py-2 text-[var(--t-100)]">{lead.company}</td>
                          <td className="px-3 py-2 text-[var(--t-72)]">{lead.city || "—"}</td>
                          <td className="px-3 py-2 text-[var(--t-72)]">{lead.email || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => handleOpenChange(false)}>
            Отмена
          </Button>
          <Button
            type="button"
            variant="brand"
            disabled={busy || !preview || preview.created === 0}
            onClick={() => void commit()}
          >
            {importing ? (
              <><Loader2 size={14} className="animate-spin" /> Импортируем…</>
            ) : (
              <>
                <Upload size={14} />
                {preview ? `Импортировать ${preview.created} ${pluralLeads(preview.created)}` : "Импортировать"}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

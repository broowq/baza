"use client";

import { FileUp, Loader2, Search, UserPlus } from "lucide-react";

/**
 * Guided first-run panel for a project with no leads yet. Replaces the noisy
 * "all-zeros stats + filters + «нет лидов по фильтрам»" view that confused
 * pilot users — gives one obvious, highlighted thing to click.
 */
export function ProjectEmptyState({
  niche,
  geography,
  collecting = false,
  canManage = false,
  onCollect,
  onAddLead,
  onImport,
}: {
  niche?: string;
  geography?: string;
  collecting?: boolean;
  canManage?: boolean;
  onCollect: () => void;
  onAddLead?: () => void;
  onImport?: () => void;
}) {
  if (collecting) {
    return (
      <div className="empty-state panel-glass elev-2">
        <div className="empty-state__icon">
          <Loader2 className="animate-spin" style={{ color: "var(--mint)", width: 26, height: 26 }} />
        </div>
        <h3 className="empty-state__title">Собираем компании…</h3>
        <p className="empty-state__body">
          БАЗА ищет компании{niche ? ` по нише «${niche}»` : ""}{geography ? ` — ${geography}` : ""} и
          проверяет телефоны и email. Обычно меньше минуты — можно не ждать на этой
          странице, лиды появятся здесь автоматически.
        </p>
      </div>
    );
  }

  return (
    <div className="empty-state panel-glass elev-2">
      <div className="empty-state__icon">
        <Search style={{ color: "var(--mint)", width: 26, height: 26 }} />
      </div>
      <div className="eyebrow mb-3">первый шаг</div>
      <h3 className="empty-state__title">Соберём первых клиентов</h3>
      <p className="empty-state__body">
        Нажмите кнопку ниже — БАЗА найдёт компании{niche ? ` по нише «${niche}»` : ""}
        {geography ? ` — ${geography}` : ""}, проверит телефоны и email и оценит по
        релевантности. Обычно занимает меньше минуты.
      </p>
      {canManage && (
        <button
          onClick={onCollect}
          className="brand cta-pulse rounded-full inline-flex items-center gap-2 mt-1"
          style={{ padding: "13px 26px", fontSize: 14.5, fontWeight: 500 }}
        >
          <Search className="h-4 w-4" />
          Собрать первых лидов
        </button>
      )}
      {canManage && (onAddLead || onImport) && (
        <div className="mt-6 flex items-center justify-center gap-3 text-[12.5px] t-48 flex-wrap">
          <span>или внесите свои контакты:</span>
          {onAddLead && (
            <button
              onClick={onAddLead}
              className="inline-flex items-center gap-1.5 t-72 hover:t-100 transition-colors"
            >
              <UserPlus size={13} /> добавить вручную
            </button>
          )}
          {onAddLead && onImport && <span className="sep-dot" />}
          {onImport && (
            <button
              onClick={onImport}
              className="inline-flex items-center gap-1.5 t-72 hover:t-100 transition-colors"
            >
              <FileUp size={13} /> импорт из файла
            </button>
          )}
        </div>
      )}
    </div>
  );
}

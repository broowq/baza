// Обработка устаревшего бандла после деплоя.
//
// Когда мы выкатываем новую версию фронта, Next.js пересобирает JS/CSS-чанки с
// новыми хэшами в имени. Вкладка, открытая ДО деплоя, всё ещё держит в памяти
// старый роут-манифест и при переходе (клике по навигации) пытается подгрузить
// чанк со старым именем — а его на сервере уже нет → 404 → `ChunkLoadError`.
// Раньше эта ошибка всплывала в наш ErrorBoundary и показывала пользователю
// «Что-то пошло не так» почти на любую кнопку. Правильная реакция — один раз
// перезагрузить страницу, чтобы получить свежий бандл.

/** Похоже ли это на ошибку загрузки чанка (устаревший бандл)? */
export function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;

  const message =
    typeof error === "string"
      ? error
      : ((error as { message?: unknown }).message ?? "");
  const name =
    typeof error === "string"
      ? ""
      : ((error as { name?: unknown }).name ?? "");

  if (name === "ChunkLoadError") return true;

  const text = String(message);
  return /ChunkLoadError|Loading chunk [\w-]+ failed|Loading CSS chunk|Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed/i.test(
    text,
  );
}

// Ключ и окно защиты от петли перезагрузок. Если после перезагрузки чанк ВСЁ
// РАВНО не грузится (деплой реально сломан, CDN отдаёт 404), не крутим reload
// бесконечно — один раз попробовали, дальше показываем обычную ошибку.
const RELOAD_KEY = "baza:chunk-reload-at";
const RELOAD_GUARD_MS = 10_000;

/**
 * Перезагрузить страницу один раз ради свежего бандла.
 * @returns true, если перезагрузка запущена; false, если сработала защита от
 *          петли (недавно уже перезагружались — значит проблема не в кеше).
 */
export function reloadOnceForChunkError(): boolean {
  if (typeof window === "undefined") return false;

  try {
    const now = Date.now();
    const last = Number(window.sessionStorage.getItem(RELOAD_KEY) || "0");
    if (Number.isFinite(last) && now - last < RELOAD_GUARD_MS) {
      // Уже перезагружались только что, а чанк снова не грузится — не зациклимся.
      return false;
    }
    window.sessionStorage.setItem(RELOAD_KEY, String(now));
  } catch {
    // sessionStorage недоступен (приватный режим/сторонние куки) — всё равно
    // делаем одну best-effort перезагрузку.
  }

  window.location.reload();
  return true;
}

"use client";

import { useEffect } from "react";

import { isChunkLoadError, reloadOnceForChunkError } from "@/lib/chunk-error";

/**
 * Ловит ошибки загрузки чанков, которые НЕ проходят через React-ErrorBoundary:
 *  • отклонённые промисы динамического import() из обработчиков событий;
 *  • провалы загрузки <script>/<link> из /_next/static (устаревший бандл).
 * В обоих случаях один раз перезагружаем страницу ради свежего бандла
 * (с защитой от петли внутри reloadOnceForChunkError).
 */
export function ChunkReloadGuard() {
  useEffect(() => {
    const onRejection = (e: PromiseRejectionEvent) => {
      if (isChunkLoadError(e.reason)) reloadOnceForChunkError();
    };

    const onError = (e: ErrorEvent) => {
      if (isChunkLoadError(e.error) || isChunkLoadError(e.message)) {
        reloadOnceForChunkError();
        return;
      }
      // Провал загрузки ресурса (script/link) не всплывает — виден только в фазе
      // перехвата и приходит с target-элементом, а не с error-объектом.
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "SCRIPT" || target.tagName === "LINK")) {
        const url =
          (target as HTMLScriptElement).src ||
          (target as HTMLLinkElement).href ||
          "";
        if (url.includes("/_next/static/")) reloadOnceForChunkError();
      }
    };

    window.addEventListener("unhandledrejection", onRejection);
    // capture:true — ошибки загрузки ресурсов не всплывают, ловим на перехвате.
    window.addEventListener("error", onError, true);
    return () => {
      window.removeEventListener("unhandledrejection", onRejection);
      window.removeEventListener("error", onError, true);
    };
  }, []);

  return null;
}

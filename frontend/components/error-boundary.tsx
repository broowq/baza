"use client";

import React, { Component, type ErrorInfo, type ReactNode } from "react";

import { isChunkLoadError, reloadOnceForChunkError } from "@/lib/chunk-error";

type Props = { children: ReactNode };
type State = { hasError: boolean; error: Error | null; reloading: boolean; errorId: string };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

/** Короткий код ошибки для пользователя/саппорта — по нему находим стек в логах. */
function shortErrorId(error: Error): string {
  const src = `${error.name}:${error.message}`;
  let h = 0;
  for (let i = 0; i < src.length; i++) h = ((h << 5) - h + src.charCodeAt(i)) | 0;
  return Math.abs(h).toString(16).slice(0, 6).padStart(6, "0");
}

/** Fire-and-forget репорт краша на бэкенд (наблюдаемость «Что-то пошло не так»).
 *  Ошибки самого репортера глотаем: диагностика не должна ронять UI. */
function reportClientError(error: Error, info: ErrorInfo, errorId: string): void {
  try {
    void fetch(`${API_URL}/client-errors`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      keepalive: true, // доживает даже если пользователь сразу уходит со страницы
      body: JSON.stringify({
        message: `${error.name}: ${error.message}`.slice(0, 1000),
        stack: (error.stack || "").slice(0, 6000),
        component_stack: (info.componentStack || "").slice(0, 4000),
        url: window.location.href.slice(0, 500),
        error_id: errorId,
      }),
    }).catch(() => {});
  } catch {
    /* noop */
  }
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, reloading: false, errorId: "" };
  }

  static getDerivedStateFromError(error: Error): State {
    // Устаревший бандл после деплоя (ChunkLoadError) — не пугаем пользователя
    // «Что-то пошло не так», а сразу показываем «Обновляем…» и перезагружаемся.
    return {
      hasError: true,
      error,
      reloading: isChunkLoadError(error),
      errorId: shortErrorId(error),
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
    if (isChunkLoadError(error)) {
      // Тихо перезагружаемся один раз ради свежего бандла. Если защита от петли
      // сработала (только что уже перезагружались) — падаем на обычный экран
      // ошибки, чтобы не крутить reload бесконечно.
      const reloading = reloadOnceForChunkError();
      if (!reloading) this.setState({ reloading: false });
      return; // chunk-ошибки самовосстанавливаются — в логи их не шлём
    }
    // Реальный render-краш: шлём стек на бэкенд — иначе такие инциденты
    // (кейс «настройки падают только у одного клиента») диагностируются вслепую.
    reportClientError(error, info, shortErrorId(error));
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null, reloading: false, errorId: "" });
  };

  render() {
    if (this.state.hasError) {
      if (this.state.reloading) {
        return (
          <div className="flex min-h-[60vh] items-center justify-center px-6">
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-white/70" />
              Обновляем приложение…
            </div>
          </div>
        );
      }
      return (
        <div className="flex min-h-[60vh] items-center justify-center px-6">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0E0F12] p-8 text-center shadow-sm">
            {/* Icon */}
            <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-white/[0.06] text-2xl">
              ⚠
            </div>

            <h2 className="text-xl font-bold text-white">
              Что-то пошло не так
            </h2>

            <p className="mt-2 text-sm text-slate-400">
              Произошла непредвиденная ошибка. Попробуйте обновить страницу или
              нажмите кнопку ниже.
            </p>

            {process.env.NODE_ENV === 'development' && this.state.error && (
              <pre className="mt-4 max-h-24 overflow-auto rounded-xl border border-white/[0.06] bg-white/[0.03] p-3 text-left text-xs text-rose-400/80">
                {this.state.error.message}
              </pre>
            )}

            {/* Код ошибки: репорт со стеком уже улетел на сервер — по этому
                коду саппорт находит его в логах, а пользователю есть что
                назвать вместо пересказа «ну там ошибка». */}
            {this.state.errorId && (
              <p className="mt-3 text-[11px] text-slate-500 select-all">
                Код ошибки: {this.state.errorId}
              </p>
            )}

            <div className="mt-6 flex items-center justify-center gap-3">
              <button
                onClick={this.handleRetry}
                className="rounded-xl bg-white/[0.1] px-5 py-2.5 text-sm font-medium text-white transition-all hover:bg-white/[0.16] active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
              >
                Попробовать снова
              </button>
              <button
                onClick={() => (window.location.href = "/")}
                className="rounded-xl border border-white/10 bg-white/[0.04] px-5 py-2.5 text-sm font-medium text-slate-300 transition-all hover:bg-white/[0.08] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
              >
                На главную
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

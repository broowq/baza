"use client";

import React, { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean; error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-[60vh] items-center justify-center px-6">
          <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-[#2A2D31] dark:bg-[#1A1C1F]">
            {/* Icon */}
            <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gray-100 dark:bg-white/[0.06] text-2xl">
              ⚠
            </div>

            <h2 className="text-xl font-bold text-[#191C1F] dark:text-white">
              Что-то пошло не так
            </h2>

            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              Произошла непредвиденная ошибка. Попробуйте обновить страницу или
              нажмите кнопку ниже.
            </p>

            {this.state.error && (
              <pre className="mt-4 max-h-24 overflow-auto rounded-xl border border-gray-200 bg-[#F7F7F8] p-3 text-left text-xs text-rose-600 dark:border-white/[0.06] dark:bg-white/[0.03] dark:text-rose-400/80">
                {this.state.error.message}
              </pre>
            )}

            <div className="mt-6 flex items-center justify-center gap-3">
              <button
                onClick={this.handleRetry}
                className="rounded-xl bg-[#191C1F] px-5 py-2.5 text-sm font-medium text-white transition-all hover:bg-[#2C2F33] active:scale-95"
              >
                Попробовать снова
              </button>
              <button
                onClick={() => (window.location.href = "/")}
                className="rounded-xl border border-gray-200 bg-[#F7F7F8] px-5 py-2.5 text-sm font-medium text-gray-700 transition-all hover:bg-gray-100 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-slate-300 dark:hover:bg-white/[0.08]"
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

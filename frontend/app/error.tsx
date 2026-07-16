"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[app/error]", error);
  }, [error]);

  return (
    <main className="relative flex min-h-[80vh] items-center justify-center px-6 overflow-hidden">
      <div className="mesh-bg" aria-hidden>
        <div className="mesh-aux" />
      </div>
      <div className="grid-lines" aria-hidden />
      <div className="panel elev-2 relative z-10 w-full max-w-md p-8 text-center">
        <div className="eyebrow">ошибка</div>
        <h1 className="h3 mt-4">Что-то пошло не так</h1>
        <p className="t-72 mt-3 text-[14px] leading-[1.55]">
          Страница не загрузилась. Попробуйте обновить — обычно этого достаточно.
        </p>
        {/* Digest — короткий код для саппорта: по нему находим стек в логах. */}
        {error.digest && (
          <p className="t-48 mono mt-3 text-[11px] select-all">
            Код ошибки: {error.digest}
          </p>
        )}
        <div className="mt-7 flex items-center justify-center gap-3">
          <button
            onClick={reset}
            className="brand rounded-full px-5 py-2.5 text-[13.5px] inline-flex items-center gap-2 cursor-pointer"
          >
            Обновить
          </button>
          <Link
            href="/"
            className="ghost rounded-full px-5 py-2.5 text-[13.5px] inline-flex items-center gap-2"
          >
            На главную
          </Link>
        </div>
      </div>
    </main>
  );
}

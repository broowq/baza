import Link from "next/link";

export const metadata = {
  title: "Страница не найдена — БАЗА",
};

export default function NotFound() {
  return (
    <main className="relative flex min-h-[80vh] items-center justify-center px-6 overflow-hidden">
      <div className="mesh-bg" aria-hidden>
        <div className="mesh-aux" />
      </div>
      <div className="grid-lines" aria-hidden />
      <div className="panel elev-2 relative z-10 w-full max-w-md p-8 text-center">
        <div className="eyebrow">ошибка · 404</div>
        <div className="h1 tnum mt-4" style={{ fontSize: "clamp(64px, 14vw, 96px)" }}>
          404
        </div>
        <h1 className="h3 mt-4">Такой страницы нет</h1>
        <p className="t-72 mt-3 text-[14px] leading-[1.55]">
          Возможно, ссылка устарела или в адресе опечатка.
          Лиды тем временем на месте.
        </p>
        <div className="mt-7 flex items-center justify-center">
          <Link
            href="/"
            className="brand rounded-full px-5 py-2.5 text-[13.5px] inline-flex items-center gap-2"
          >
            На главную
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </Link>
        </div>
      </div>
    </main>
  );
}

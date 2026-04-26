"use client";

/**
 * Landing page v2 — full Cinematic Glass implementation.
 * Faithfully ports /tmp/baza-design/ee/project/База v2.html into React.
 *
 * Animations:
 *  - Cursor spotlight (global ambient mint glow)
 *  - Live ticking number + rolling feed in hero
 *  - Typed prompt → entity highlight reveal with chips
 *  - Animated counters on scroll-into-view
 *  - Pulse feed (kafka-style scroller in dashboard frame)
 *  - 24h × source heatmap
 *  - Bubble chart with hover focus
 *  - View transitions between Обзор / Проект / Лид
 *  - Live clock in corner-meta
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";

import { getToken } from "@/lib/auth";

/* ─────────────────────────────────────────────────────────────
   DATA
   ───────────────────────────────────────────────────────────── */

const COMPANY_POOL: Array<[string, string, string, number]> = [
  ["СибКорм", "Томск", "10.91", 87],
  ["АлтайАгро", "Барнаул", "10.91", 76],
  ["Фермер КПК", "Новосибирск", "01.46", 74],
  ["Птицефабрика «MSK»", "Москва", "10.10", 91],
  ["АгроКомплект", "Ростов", "10.91", 71],
  ["КраснояркКорм", "Красноярск", "10.91", 68],
  ["Юг-Птица", "Краснодар", "01.47", 92],
  ["Стрежевой Корма", "Стрежевой", "10.91", 64],
  ["Молпром-Алтай", "Барнаул", "10.51", 82],
  ["ОмскХлеб", "Омск", "10.71", 69],
  ["Томь-Агро", "Томск", "01.11", 79],
  ["Енисей-Мясо", "Красноярск", "10.13", 86],
  ["Иртыш-Корм", "Омск", "01.42", 73],
  ["Алтай-Зерно", "Бийск", "01.11", 81],
  ["Север-Продукт", "Сургут", "10.91", 68],
];

const PULSE_FEED: Array<{
  ts: string;
  tag: "g" | "b" | "a";
  tagText: string;
  co: string;
  meta: string;
  num: string;
}> = [
  { ts: "14:23:08.412", tag: "g", tagText: "+ enriched", co: "ООО «СибКорм»", meta: "Томск · 10.10.1", num: "score 87" },
  { ts: "14:23:07.901", tag: "b", tagText: "~ verify mx", co: "АлтайАгроПродукт", meta: "Барнаул · 10.10.2", num: "deliv 96%" },
  { ts: "14:23:07.205", tag: "g", tagText: "+ enriched", co: "Фермер КПК", meta: "Новосиб. · 01.46", num: "score 74" },
  { ts: "14:23:06.788", tag: "a", tagText: "× dedup hit", co: "СибИнтерАгро", meta: "Кемерово · ИНН", num: "→ 0017" },
  { ts: "14:23:06.142", tag: "g", tagText: "+ enriched", co: "Птицефабрика «MSK»", meta: "Москва · 10.10.1", num: "score 91" },
  { ts: "14:23:05.620", tag: "b", tagText: "~ smtp probe", co: "АгроКомплект", meta: "Ростов · 10.10.2", num: "220 ok" },
  { ts: "14:23:04.997", tag: "g", tagText: "+ enriched", co: "КраснояркКорм", meta: "Красноярск · 10.10.1", num: "score 68" },
  { ts: "14:23:04.331", tag: "a", tagText: "× invalid email", co: "ТомПищеПром", meta: "Томск · 10.71", num: "550 hard" },
];

const HEATMAP_SOURCES: Array<{ name: string; curve: number[] }> = [
  { name: "реестр", curve: [0.2, 0.15, 0.1, 0.08, 0.06, 0.08, 0.18, 0.42, 0.65, 0.78, 0.85, 0.82, 0.78, 0.74, 0.7, 0.62, 0.55, 0.48, 0.42, 0.36, 0.32, 0.28, 0.24, 0.22] },
  { name: "СПАРК", curve: [0.12, 0.08, 0.06, 0.05, 0.04, 0.06, 0.14, 0.32, 0.55, 0.7, 0.78, 0.74, 0.7, 0.66, 0.6, 0.52, 0.45, 0.38, 0.32, 0.28, 0.24, 0.2, 0.16, 0.14] },
  { name: "каталоги", curve: [0.08, 0.06, 0.05, 0.04, 0.04, 0.06, 0.12, 0.22, 0.38, 0.5, 0.58, 0.55, 0.52, 0.5, 0.46, 0.4, 0.34, 0.3, 0.26, 0.22, 0.2, 0.18, 0.14, 0.1] },
  { name: "парс", curve: [0.32, 0.28, 0.22, 0.18, 0.16, 0.14, 0.18, 0.22, 0.28, 0.32, 0.36, 0.4, 0.42, 0.45, 0.42, 0.38, 0.34, 0.32, 0.36, 0.42, 0.5, 0.55, 0.48, 0.4] },
];

const BUBBLE_DATA: Array<{
  region: string; short: string; rev: number; leads: number; qual: number; primary?: boolean;
}> = [
  { region: "Томская обл.", short: "Томск", rev: 142, leads: 47, qual: 17, primary: true },
  { region: "Новосибирская", short: "Новосиб.", rev: 98, leads: 28, qual: 11 },
  { region: "Красноярский кр.", short: "Красноярск", rev: 168, leads: 17, qual: 9 },
  { region: "Кемеровская", short: "Кемерово", rev: 128, leads: 19, qual: 6 },
  { region: "Алтайский кр.", short: "Барнаул", rev: 72, leads: 11, qual: 4 },
  { region: "Омская обл.", short: "Омск", rev: 88, leads: 12, qual: 3 },
  { region: "Иркутская", short: "Иркутск", rev: 116, leads: 9, qual: 3 },
  { region: "Респ. Хакасия", short: "Абакан", rev: 54, leads: 6, qual: 2 },
  { region: "Респ. Алтай", short: "Г-Алт.", rev: 42, leads: 4, qual: 1 },
];

/* ─────────────────────────────────────────────────────────────
   HOOKS
   ───────────────────────────────────────────────────────────── */

/** Cursor spotlight tracker — sets --mx/--my on body for the global glow. */
function useCursorSpotlight() {
  useEffect(() => {
    let raf = 0;
    function onMove(e: PointerEvent) {
      document.body.classList.add("spot-ready");
      if (raf) return;
      raf = requestAnimationFrame(() => {
        document.body.style.setProperty("--mx", e.clientX + "px");
        document.body.style.setProperty("--my", e.clientY + "px");
        raf = 0;
      });
    }
    document.addEventListener("pointermove", onMove, { passive: true });
    return () => document.removeEventListener("pointermove", onMove);
  }, []);
}

/** Format a number with thin-space thousand separators (e.g. 142 580). */
const thinFmt = (n: number) => Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "\u2009");

/** Animate a count-up from 0 to target when the element scrolls into view. */
function useCountUp<T extends HTMLElement>(target: number, opts?: { thin?: boolean; durationMs?: number }) {
  const ref = useRef<T | null>(null);
  const ranRef = useRef(false);
  useEffect(() => {
    if (!ref.current) return;
    const dur = opts?.durationMs ?? 1400;
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);
    const io = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          if (!en.isIntersecting || ranRef.current) continue;
          ranRef.current = true;
          const start = performance.now();
          const step = (t: number) => {
            const k = Math.min(1, (t - start) / dur);
            const v = target * ease(k);
            if (ref.current) {
              ref.current.textContent = opts?.thin ? thinFmt(v) : Math.round(v).toString();
            }
            if (k < 1) requestAnimationFrame(step);
          };
          requestAnimationFrame(step);
          io.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    io.observe(ref.current);
    return () => io.disconnect();
  }, [target, opts?.thin, opts?.durationMs]);
  return ref;
}

/** Live ticking clock in the corner-meta. */
function useLiveClock() {
  const [s, setS] = useState(() => formatClock(new Date()));
  useEffect(() => {
    const id = setInterval(() => setS(formatClock(new Date())), 1000);
    return () => clearInterval(id);
  }, []);
  return s;
}
function formatClock(d: Date) {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/* ─────────────────────────────────────────────────────────────
   COMPONENTS
   ───────────────────────────────────────────────────────────── */

function CornerMeta() {
  const clock = useLiveClock();
  return (
    <div className="corner-meta">
      № 0042 / Tomsk
      <br />
      <span>{clock}</span>
    </div>
  );
}

function TopNav() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    setAuthed(Boolean(getToken()));
  }, []);

  return (
    <header className="topnav">
      <div className="max-w-[1320px] mx-auto px-6 h-14 flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2">
          <span
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M4 6 L12 3 L20 6 L20 18 L12 21 L4 18 Z" stroke="black" strokeWidth="1.6" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="text-[15px]" style={{ fontWeight: 500 }}>база</span>
          <span className="t-40 text-[11px] mono">v0.42</span>
        </Link>
        <nav className="hidden md:flex items-center gap-1 ml-4">
          <span className="nav-link active">Продукт</span>
          <span className="nav-link">Источники</span>
          <Link href="/plans" className="nav-link">Цены</Link>
          <span className="nav-link">Документация</span>
          <span className="nav-link">Журнал</span>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden md:flex items-center gap-2 text-[11px] t-48">
            <span className="dot dot-em" />
            все системы стабильны
          </span>
          {authed ? (
            <Link
              href="/dashboard"
              className="brand rounded-full px-4 py-1.5 text-[12.5px]"
            >
              Открыть дашборд →
            </Link>
          ) : (
            <>
              <Link href="/login" className="ghost rounded-full px-3.5 py-1.5 text-[12.5px]">Войти</Link>
              <Link href="/register" className="brand rounded-full px-4 py-1.5 text-[12.5px]">Получить доступ</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

/* ── Hero + Live mini-card ──────────────────────────────────── */

function HeroLiveCard() {
  const [count, setCount] = useState(2731);
  const [delta, setDelta] = useState(47);
  const [feed, setFeed] = useState<
    Array<{ id: string; co: string; meta: string; score: number; out?: boolean }>
  >([]);
  const [ago, setAgo] = useState(0);
  const flashRef = useRef<HTMLDivElement | null>(null);
  const lastUpdateRef = useRef<number>(Date.now());
  const seedRef = useRef(false);
  const sectionRef = useRef<HTMLDivElement | null>(null);

  // ago counter
  useEffect(() => {
    const id = setInterval(() => {
      setAgo(Math.floor((Date.now() - lastUpdateRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // start ticking when section in view
  useEffect(() => {
    if (!sectionRef.current) return;
    const io = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (!en.isIntersecting || seedRef.current) continue;
        seedRef.current = true;
        // seed 3 rows
        const seed: typeof feed = [];
        for (let k = 0; k < 3; k++) {
          const [co, city, , score] = COMPANY_POOL[Math.floor(Math.random() * COMPANY_POOL.length)];
          seed.unshift({ id: `${Date.now()}-${k}`, co, meta: city, score });
        }
        setFeed(seed);
        // start ticks
        const numTimer = scheduleTickNum();
        const feedTimer = scheduleTickFeed();
        return () => {
          clearTimeout(numTimer);
          clearTimeout(feedTimer);
        };
      }
    }, { threshold: 0.3 });
    io.observe(sectionRef.current);
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scheduleTickNum = useCallback(() => {
    return window.setTimeout(function tick() {
      const inc = 1 + Math.floor(Math.random() * 2);
      setCount((c) => c + inc);
      setDelta((d) => d + inc);
      // flash
      if (flashRef.current) {
        flashRef.current.classList.remove("flash");
        // force reflow
        void flashRef.current.offsetWidth;
        flashRef.current.classList.add("flash");
      }
      window.setTimeout(tick, 2200 + Math.random() * 1800);
    }, 1800);
  }, []);

  const scheduleTickFeed = useCallback(() => {
    return window.setTimeout(function pushLead() {
      lastUpdateRef.current = Date.now();
      setAgo(0);
      const [co, city, , score] = COMPANY_POOL[Math.floor(Math.random() * COMPANY_POOL.length)];
      setFeed((f) => {
        const next = [{ id: `${Date.now()}-${Math.random()}`, co, meta: city, score }, ...f];
        // mark oldest as fade-out if > 4
        if (next.length > 4) {
          const last = next[next.length - 1];
          last.out = true;
          // remove after fade animation
          window.setTimeout(() => {
            setFeed((cur) => cur.filter((x) => x.id !== last.id));
          }, 360);
        }
        return next;
      });
      window.setTimeout(pushLead, 2400 + Math.random() * 1600);
    }, 3200);
  }, []);

  return (
    <div ref={sectionRef} className="col-span-12 lg:col-span-4 lg:pl-6 reveal" style={{ animationDelay: "0.34s" }}>
      <div className="panel p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="dot dot-em" />
            <span className="text-[12px] t-72">собирается прямо сейчас</span>
          </div>
          <span className="t-40 text-[10px] mono">обновлено {ago}с назад</span>
        </div>
        <div ref={flashRef} className="h1 tnum hero-bignum" style={{ fontSize: 84 }}>
          {count.toLocaleString("ru-RU")}
        </div>
        <div className="text-[12px] t-72 mt-1">лидов сегодня</div>
        <div className="mt-4 flex items-baseline gap-3 text-[12px]">
          <span className="mono tnum" style={{ color: "var(--green)" }}>▲ +{delta}</span>
          <span className="t-48">за последний час</span>
        </div>

        <div className="mt-5 hairline pt-4">
          <div className="eyebrow mb-3">последние</div>
          <div className="hero-feed">
            {feed.map((row) => (
              <div key={row.id} className={"feed-row" + (row.out ? " fade-out" : "")}>
                <span className="dot dot-em" style={{ width: 5, height: 5 }} />
                <span className="fr-co">{row.co}</span>
                <span className="fr-meta">{row.meta}</span>
                <span className="fr-score">{row.score}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 hairline pt-4 grid grid-cols-2 gap-3 text-[11px]">
          <div>
            <div className="t-48">конверсия в работу</div>
            <div className="mono mt-0.5 tnum text-white text-[13px]">21.0%</div>
          </div>
          <div>
            <div className="t-48">средний score</div>
            <div className="mono mt-0.5 tnum text-white text-[13px]">72 / 100</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function HeroSection() {
  return (
    <section className="relative overflow-hidden">
      <div className="field" />
      <div className="grid-lines" />
      <div className="grain" />

      <div className="relative z-10 max-w-[1320px] mx-auto px-6 pt-24 pb-20">
        <div className="grid grid-cols-12 gap-10 items-end">
          <div className="col-span-12 lg:col-span-8">
            <div className="flex items-center gap-3 mb-7 reveal" style={{ animationDelay: "0.05s" }}>
              <span className="panel-thin px-3 py-1 text-[11px] flex items-center gap-2">
                <span className="dot dot-em" />
                раннее открытие · апрель 2026
              </span>
              <span className="t-48 text-[12px]">для B2B-команд продаж в РФ</span>
            </div>
            <h1
              className="h1 reveal"
              style={{
                fontSize: "clamp(64px,9vw,128px)",
                animationDelay: "0.1s",
              }}
            >
              Лиды, которые{" "}
              <span style={{ color: "var(--mint)" }} className="serif">созревают</span>
              <br />
              до того, как вы их откроете.
            </h1>
            <p
              className="mt-7 max-w-[640px] text-[17px] t-72 leading-[1.5] light reveal"
              style={{ animationDelay: "0.2s" }}
            >
              База — это инжиниринг лидов под промпт. Опишите идеального клиента словами,
              получите список компаний, людей и каналов связи — обогащённый,
              отдедуплицированный и оценённый по релевантности.
            </p>

            <div
              className="flex flex-wrap items-center gap-3 mt-9 reveal"
              style={{ animationDelay: "0.28s" }}
            >
              <Link href="/register" className="brand rounded-full px-5 py-2.5 text-[13.5px] flex items-center gap-2">
                Получить доступ
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </Link>
              <a className="ghost rounded-full px-5 py-2.5 text-[13.5px] flex items-center gap-2 cursor-pointer">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                Посмотреть продукт · 2 мин
              </a>
              <span className="ml-2 text-[12px] t-48">
                от <span className="text-white mono">2 ₽</span> за обогащённый контакт
              </span>
            </div>

            <div
              className="mt-12 flex flex-wrap items-center gap-x-7 gap-y-3 t-48 text-[11.5px] reveal"
              style={{ animationDelay: "0.4s" }}
            >
              {[
                "ЕГРЮЛ · 4.7M записей",
                "2GIS · 1.8M точек",
                "СПАРК · API",
                "ФНС · открытые данные",
                "отраслевые каталоги",
              ].map((t) => (
                <span key={t} className="flex items-center gap-2 mono">
                  <span className="dot dot-mt" />
                  {t}
                </span>
              ))}
            </div>
          </div>

          <HeroLiveCard />
        </div>
      </div>
    </section>
  );
}

/* ── Prompt demo ──────────────────────────────────────────────── */

function PromptDemo() {
  const targetText =
    "Продаю кормовые добавки для крупного рогатого скота. Нужны фермерские хозяйства Сибирского ФО от 200 голов, с email и закупщиком. Без перекупщиков.";
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [phase, setPhase] = useState<"wait" | "typing" | "parsed">("wait");
  const [typed, setTyped] = useState("");
  const [litCount, setLitCount] = useState(0);

  useEffect(() => {
    if (!wrapRef.current) return;
    const io = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (!en.isIntersecting || phase !== "wait") continue;
        setPhase("typing");
        io.disconnect();
        let i = 0;
        const tt = () => {
          i++;
          setTyped(targetText.slice(0, i));
          if (i < targetText.length) {
            setTimeout(tt, 22 + Math.random() * 30);
          } else {
            setTimeout(() => setPhase("parsed"), 500);
          }
        };
        setTimeout(tt, 400);
      }
    }, { threshold: 0.5 });
    io.observe(wrapRef.current);
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reveal entity highlights one by one after typing.
  useEffect(() => {
    if (phase !== "parsed") return;
    let cancelled = false;
    let n = 0;
    const tags = 6;
    const reveal = () => {
      if (cancelled) return;
      n++;
      setLitCount(n);
      if (n < tags) setTimeout(reveal, 340);
    };
    setTimeout(reveal, 220);
    return () => {
      cancelled = true;
    };
  }, [phase]);

  // Tagged content rendered when parsed
  const Tagged = () => {
    const tags: Array<{ text: string; chip: string }> = [
      { text: "кормовые добавки", chip: "продукт" },
      { text: "крупного рогатого скота", chip: "отрасль · КРС" },
      { text: "фермерские хозяйства", chip: "ОКВЭД 01.4*" },
      { text: "Сибирского ФО", chip: "регион · СФО" },
      { text: "от 200 голов", chip: "размер" },
      { text: "email и закупщиком", chip: "контакт" },
    ];
    // Construct rendered text by splitting on tag.text occurrences in order
    const parts: React.ReactNode[] = [];
    let remaining = targetText;
    let key = 0;
    tags.forEach((tag, idx) => {
      const at = remaining.indexOf(tag.text);
      if (at < 0) return;
      if (at > 0) parts.push(<span key={key++}>{remaining.slice(0, at)}</span>);
      parts.push(
        <span
          key={key++}
          className={"ptag" + (idx < litCount ? " lit" : "")}
        >
          {tag.text}
          <span className="chip">{tag.chip}</span>
        </span>,
      );
      remaining = remaining.slice(at + tag.text.length);
    });
    if (remaining) parts.push(<span key={key++}>{remaining}</span>);
    return <>{parts}</>;
  };

  return (
    <section className="relative">
      <div className="max-w-[1320px] mx-auto px-6 pt-6 pb-20">
        <div className="grid grid-cols-12 gap-8 items-start">
          <div className="col-span-12 lg:col-span-5">
            <div className="eyebrow mb-3">шаг 01 · описание</div>
            <h2 className="h2" style={{ fontSize: "clamp(40px,4.4vw,64px)" }}>
              Опишите, кого вы ищете —
              <br />
              как вы бы рассказали стажёру.
            </h2>
            <p className="mt-5 text-[15px] t-72 max-w-[440px] light leading-[1.55]">
              Без фильтров, форм и тегов. Свободный текст — модель сама вытащит из него
              отрасль, географию, размер, признаки готовности к сделке.
            </p>
            <ul className="mt-7 space-y-3 text-[13px] t-72">
              <li className="flex items-start gap-3"><span className="mono t-40 mt-0.5">01</span>распознаём ОКВЭД и регионы по смыслу</li>
              <li className="flex items-start gap-3"><span className="mono t-40 mt-0.5">02</span>матчим к источникам — ЕГРЮЛ, 2GIS, СПАРК, отраслевые</li>
              <li className="flex items-start gap-3"><span className="mono t-40 mt-0.5">03</span>обогащаем контактами и оцениваем релевантность</li>
            </ul>
          </div>

          <div ref={wrapRef} className="col-span-12 lg:col-span-7">
            <div className="panel p-5">
              <div className="flex items-center gap-2 mb-4 px-1">
                <span className="dot dot-em" />
                <span className="text-[12px] t-72">собирает</span>
                <span className="ml-auto t-40 text-[10px] mono">prompt → leads · 8.2s</span>
              </div>
              <div className="panel-flat p-5 prompt-box" style={{ borderRadius: 14, position: "relative" }}>
                <div className="text-[11px] t-40 mono mb-2">/задача</div>
                <div className="prompt-text-wrap" style={{ position: "relative" }}>
                  <p className="text-[19px] light leading-[1.55]" style={{ minHeight: 84 }}>
                    {phase === "parsed" ? <Tagged /> : typed}
                    {phase !== "parsed" && <span className="caret" />}
                  </p>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-5 gap-2 text-[11px]">
                {[
                  ["01 · парсинг", "8 источников", 100, "var(--mint)"],
                  ["02 · матчинг", "12 410 → 384", 100, "var(--mint)"],
                  ["03 · дедуп", "→ 217", 100, "var(--mint)"],
                  ["04 · обогащение", "SMTP+MX", 78, "var(--mint)"],
                  ["05 · готово", `${phase === "parsed" ? 134 : 0} лидов`, 100, "var(--green)"],
                ].map(([label, val, w, color], i) => (
                  <div key={i} className="panel-flat px-3 py-3">
                    <div className="t-40 mono text-[10px]">{label as string}</div>
                    <div className="text-white tnum mt-1">{val as string}</div>
                    <div className="h-[2px] mt-2 rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${w}%`,
                          background: color as string,
                          boxShadow: i === 4 ? "0 0 8px rgba(52,211,153,0.5)" : undefined,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-5 flex items-center gap-3 t-48 text-[11px] hairline pt-4">
                <span className="mono">9 регионов · ОКВЭД 01.4*</span>
                <span className="mx-2">·</span>
                <span>отбор по выручке &gt; 60M ₽</span>
                <span className="ml-auto text-[12px] flex items-center gap-2">
                  смотреть результат
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Product Frame: tabbed Overview / Project / Lead ────────── */

function ProductFrame() {
  const [view, setView] = useState<"overview" | "project" | "lead">("overview");
  // keyboard shortcut 1/2/3
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "1") setView("overview");
      if (e.key === "2") setView("project");
      if (e.key === "3") setView("lead");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const crumb = view === "overview" ? "Обзор" : view === "project" ? "Проект" : "Лид";
  return (
    <section className="relative">
      <div className="max-w-[1320px] mx-auto px-6 pt-6 pb-24">
        <div className="flex items-end justify-between mb-7">
          <div>
            <div className="eyebrow mb-3">шаг 02 · работа с результатом</div>
            <h2 className="h2" style={{ fontSize: "clamp(40px,4.4vw,64px)" }}>
              Один экран от обзора
              <br />
              до карточки лида.
            </h2>
          </div>
          <div className="seg">
            {[
              { k: "overview", label: "Обзор" },
              { k: "project", label: "Проект" },
              { k: "lead", label: "Лид" },
            ].map((v) => (
              <button
                key={v.k}
                className={"seg-btn" + (view === v.k ? " active" : "")}
                onClick={() => setView(v.k as typeof view)}
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>

        <div className="frame">
          <div className="frame-bar">
            <div className="flex items-center gap-1.5">
              <span className="tlight" style={{ background: "#3a3a3e" }} />
              <span className="tlight" style={{ background: "#3a3a3e" }} />
              <span className="tlight" style={{ background: "#3a3a3e" }} />
            </div>
            <div className="ml-3 flex items-center gap-2 text-[11.5px] t-72">
              <span className="hover:text-white">Кормопром · Томск</span>
              <span className="t-28">/</span>
              <span className="text-white">{crumb}</span>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <button className="ghost rounded-full px-3 py-1 text-[11.5px] flex items-center gap-2">
                <span>⌘K</span>
                <span className="t-48">поиск</span>
              </button>
              <span className="panel-thin px-3 py-1 text-[11px] flex items-center gap-2">
                <span className="dot dot-em" />
                сбор активен
              </span>
              <span className="w-7 h-7 rounded-full" style={{ background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)" }} />
            </div>
          </div>

          <div className="grid" style={{ gridTemplateColumns: "220px 1fr" }}>
            <FrameRail view={view} setView={setView} />
            <main
              className="p-7 min-h-[640px]"
              style={{ background: "linear-gradient(180deg,rgba(255,255,255,0.012),transparent)" }}
            >
              <ViewOverview active={view === "overview"} />
              <ViewProject active={view === "project"} />
              <ViewLead active={view === "lead"} />
            </main>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3 t-48 text-[12px]">
          <span className="mono">→</span>
          Переключайтесь между видами кнопками сверху или клавишами{" "}
          <span className="mono panel-thin px-1.5 py-0.5 text-[10px]">1</span>{" "}
          <span className="mono panel-thin px-1.5 py-0.5 text-[10px]">2</span>{" "}
          <span className="mono panel-thin px-1.5 py-0.5 text-[10px]">3</span>
        </div>
      </div>
    </section>
  );
}

function FrameRail({
  view,
  setView,
}: {
  view: "overview" | "project" | "lead";
  setView: (v: "overview" | "project" | "lead") => void;
}) {
  return (
    <aside className="p-3" style={{ borderRight: "1px solid var(--line)" }}>
      <div className="rail-section">workspace</div>
      <RailItem active={view === "overview"} onClick={() => setView("overview")}>
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <rect x="3" y="3" width="7" height="7" rx="1.2" />
          <rect x="14" y="3" width="7" height="7" rx="1.2" />
          <rect x="3" y="14" width="7" height="7" rx="1.2" />
          <rect x="14" y="14" width="7" height="7" rx="1.2" />
        </svg>
        Обзор
      </RailItem>
      <RailItem active={view === "project"} onClick={() => setView("project")}>
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 1118 0z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
        Проекты
      </RailItem>
      <RailItem active={view === "lead"} onClick={() => setView("lead")}>
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <circle cx="12" cy="8" r="4" />
          <path d="M4 21c1.5-4.5 5-7 8-7s6.5 2.5 8 7" />
        </svg>
        Лиды
      </RailItem>
      <RailItem>
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M3 3h18M5 8h14M7 13h10M9 18h6" />
        </svg>
        Источники
      </RailItem>
      <RailItem>
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M3 3v18h18" />
          <path d="M7 14l4-4 4 4 5-7" />
        </svg>
        Аналитика
      </RailItem>

      <div className="rail-section">проекты</div>
      <RailItem><span className="dot dot-em" />Кормовые · Томск</RailItem>
      <RailItem><span className="dot dot-em" />HoReCa · Москва</RailItem>
      <RailItem><span className="dot dot-am" />Стройматериалы · СПб</RailItem>
      <RailItem className="t-48"><span style={{ opacity: 0.5 }}>+</span>новый проект</RailItem>

      <div className="rail-section">аккаунт</div>
      <RailItem className="t-48">
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <circle cx="12" cy="12" r="3" />
          <path d="M19 12a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        Настройки
      </RailItem>
      <RailItem className="t-48">
        <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M12 8v4M12 16h.01M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9 9 4.03 9 9z" />
        </svg>
        Поддержка
      </RailItem>
    </aside>
  );
}

function RailItem({
  children,
  active,
  className = "",
  onClick,
}: {
  children: React.ReactNode;
  active?: boolean;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <div className={`rail-item${active ? " active" : ""} ${className}`} onClick={onClick}>
      {children}
    </div>
  );
}

/* ── View: Overview ──────────────────────────────────────── */

function ViewOverview({ active }: { active: boolean }) {
  // counters
  const liveRef = useCountUp<HTMLSpanElement>(142580, { thin: true });
  const totalRef = useCountUp<HTMLSpanElement>(2847, { thin: true });
  const enrichedRef = useCountUp<HTMLSpanElement>(1923, { thin: true });
  const emailRef = useCountUp<HTMLSpanElement>(1456, { thin: true });
  const scoreRef = useCountUp<HTMLSpanElement>(72);
  const fnQueueRef = useCountUp<HTMLSpanElement>(142580, { thin: true });
  const fnParserRef = useCountUp<HTMLSpanElement>(111210, { thin: true });
  const fnDedupRef = useCountUp<HTMLSpanElement>(76994, { thin: true });
  const fnEnrichRef = useCountUp<HTMLSpanElement>(51328, { thin: true });
  const fnReadyRef = useCountUp<HTMLSpanElement>(29942, { thin: true });

  return (
    <section className={"view" + (active ? " active" : "")}>
      <div className="flex items-end justify-between mb-6 flex-wrap gap-6">
        <div>
          <div className="eyebrow">live · последние 24ч</div>
          <div className="h1 tnum mt-2" style={{ fontSize: 84 }}>
            <span ref={liveRef} className="count-num">0</span>
          </div>
          <div className="text-[13px] t-72 mt-1">
            кандидатов прошло через очередь ·{" "}
            <span style={{ color: "var(--green)" }}>+18%</span> vs вчера
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 w-full sm:w-[340px] flex-none">
          {[
            ["всего лидов", totalRef],
            ["обогащено", enrichedRef],
            ["с email", emailRef],
            ["средний score", scoreRef],
          ].map(([label, ref], i) => (
            <div key={i} className="panel-flat p-3">
              <div className="eyebrow">{label as string}</div>
              <div className="h2 tnum mt-2" style={{ fontSize: 28 }}>
                <span ref={ref as React.RefObject<HTMLSpanElement>} className="count-num">0</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Pulse feed */}
        <div className="col-span-12 lg:col-span-7 panel-flat overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 hairline" style={{ borderTop: 0 }}>
            <div className="flex items-center gap-2">
              <span className="dot dot-em" />
              <span className="text-[12px] t-72">живой поток · обогащение</span>
            </div>
            <span className="t-40 mono text-[10px]">stream://enrich.kafka.lead-v3</span>
          </div>
          <div className="feed-mask">
            <div className="feed-rail">
              {[...PULSE_FEED, ...PULSE_FEED].map((row, i) => (
                <div key={i} className="feed-row">
                  <span className="mono t-40">{row.ts}</span>
                  <span className={`feed-tag ${row.tag}`}>{row.tagText}</span>
                  <span className="feed-co flex-1">{row.co}</span>
                  <span className="t-48 text-[11px]">{row.meta}</span>
                  <span className="mono ml-auto t-72">{row.num}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Funnel */}
        <div className="col-span-12 lg:col-span-5 panel-flat p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="eyebrow">pipeline · 24ч</div>
              <div className="text-[12px] t-72 mt-1">от очереди к готовым</div>
            </div>
            <span className="t-40 mono text-[10px]">шаг · кол-во</span>
          </div>
          <div className="funnel">
            <FunnelRow label="очередь" w={100} numRef={fnQueueRef} />
            <FunnelRow label="парсер" w={78} numRef={fnParserRef} />
            <FunnelRow label="дедуп" w={54} numRef={fnDedupRef} />
            <FunnelRow label="обогащ." w={36} numRef={fnEnrichRef} />
            <FunnelRow label="готовы" w={21} numRef={fnReadyRef} em />
          </div>
        </div>

        {/* Heatmap */}
        <div className="col-span-12 lg:col-span-7 panel-flat p-5">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <div>
              <div className="eyebrow">интенсивность · 24ч × источник</div>
              <div className="text-[12px] t-72 mt-1">ярче — больше лидов в этот час</div>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] t-40 mono">low</span>
              {[0.06, 0.18, 0.34, 0.55, 0.85].map((a) => (
                <span key={a} className="hm-leg" style={{ ["--a" as never]: a }} />
              ))}
              <span className="text-[10px] t-40 mono">high</span>
            </div>
          </div>
          <div className="heatmap">
            {HEATMAP_SOURCES.map((s) => (
              <Heatmap row key={s.name} src={s} />
            ))}
          </div>
          <div className="flex justify-between mt-2 text-[9px] t-28 mono tnum">
            {["00", "03", "06", "09", "12", "15", "18", "21", "24"].map((t) => (
              <span key={t}>{t}</span>
            ))}
          </div>
        </div>

        {/* Sources mix */}
        <div className="col-span-12 lg:col-span-5 panel-flat p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="eyebrow">источники · 7 дней</div>
            <span className="t-40 mono text-[10px]">all projects</span>
          </div>
          <div className="src-list">
            <SourceRow name="Реестр ННО" pct={42} num="59 884" path="M0 12 L10 11 L20 8 L30 9 L40 6 L50 7 L60 4 L70 5 L80 3" />
            <SourceRow name="СПАРК / API" pct={26} num="37 070" path="M0 8 L10 10 L20 7 L30 9 L40 8 L50 6 L60 7 L70 5 L80 6" />
            <SourceRow name="Отраслевые" pct={18} num="25 664" path="M0 6 L10 8 L20 7 L30 11 L40 9 L50 12 L60 10 L70 13 L80 11" />
            <SourceRow name="Парс сайтов" pct={9} num="12 832" path="M0 14 L10 12 L20 13 L30 10 L40 11 L50 9 L60 10 L70 8 L80 9" />
            <SourceRow name="Импорт CSV" pct={5} num="7 130" path="M0 11 L10 11 L20 12 L30 10 L40 12 L50 11 L60 13 L70 12 L80 14" />
          </div>
        </div>
      </div>
    </section>
  );
}

function FunnelRow({
  label,
  w,
  numRef,
  em,
}: {
  label: string;
  w: number;
  numRef: React.RefObject<HTMLSpanElement>;
  em?: boolean;
}) {
  return (
    <div className={"fn-row" + (em ? " em" : "")}>
      <span className="fn-label">{label}</span>
      <div className={"fn-bar" + (em ? " em" : "")} style={{ ["--w" as never]: `${w}%` }} />
      <span className="fn-num mono tnum">
        <span ref={numRef} className="count-num">0</span>
      </span>
    </div>
  );
}

function Heatmap({ src }: { src: { name: string; curve: number[] }; row?: boolean }) {
  return (
    <>
      <div className="hm-label">{src.name}</div>
      {src.curve.map((v, i) => {
        const a = Math.max(0.04, Math.min(0.92, v + (Math.random() - 0.5) * 0.08)).toFixed(3);
        return <div key={i} className="hm-cell" style={{ ["--a" as never]: a }} />;
      })}
    </>
  );
}

function SourceRow({ name, pct, num, path }: { name: string; pct: number; num: string; path: string }) {
  return (
    <div className="src-row">
      <span className="src-name">{name}</span>
      <svg className="src-spark" viewBox="0 0 80 18">
        <path d={path} stroke="rgba(255,255,255,0.55)" strokeWidth="1" fill="none" />
      </svg>
      <span className="src-pct mono tnum">{pct}%</span>
      <span className="src-num mono">{num}</span>
    </div>
  );
}

/* ── View: Project ─────────────────────────────────────── */

function ViewProject({ active }: { active: boolean }) {
  const collectedRef = useCountUp<HTMLSpanElement>(134);
  const emailedRef = useCountUp<HTMLSpanElement>(71);
  const qualRef = useCountUp<HTMLSpanElement>(17);

  return (
    <section className={"view" + (active ? " active" : "")}>
      <div className="flex items-end justify-between mb-6 flex-wrap gap-6">
        <div>
          <div className="eyebrow">проект · 0042</div>
          <div className="h1 mt-2" style={{ fontSize: 64 }}>Кормовые добавки · Томск</div>
          <div className="text-[13px] t-72 mt-1 mono">ОКВЭД 10.91 · 01.46 · 10.10 · 47.21 · регион 70</div>
        </div>
        <div className="grid grid-cols-3 gap-3 w-full sm:w-[380px] flex-none">
          {[
            ["собрано", collectedRef],
            ["с email", emailedRef],
            ["qualified", qualRef],
          ].map(([label, ref], i) => (
            <div key={i} className="panel-flat p-3">
              <div className="eyebrow">{label as string}</div>
              <div className="h2 tnum mt-2" style={{ fontSize: 28 }}>
                <span ref={ref as React.RefObject<HTMLSpanElement>} className="count-num">0</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-12 lg:col-span-7">
          <BubbleChart />

          <div className="panel-flat mt-5 p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="eyebrow">распределение по ОКВЭД</div>
              <span className="t-40 mono text-[10px]">5 групп</span>
            </div>
            <div className="space-y-2.5 text-[12px]">
              {[
                ["10.91", 62, "62 / 83"],
                ["01.46", 38, "38 / 51"],
                ["01.41", 24, "24 / 32"],
                ["10.10.1", 12, "12 / 16"],
                ["47.21", 6, "6 / 8"],
              ].map(([code, w, val]) => (
                <div
                  key={code as string}
                  className="grid items-center gap-3"
                  style={{ gridTemplateColumns: "120px 1fr 60px" }}
                >
                  <span className="mono t-72">{code as string}</span>
                  <div className="h-[10px] rounded" style={{ background: "rgba(168,197,192,0.10)" }}>
                    <div className="h-full rounded" style={{ width: `${w}%`, background: "var(--mint)" }} />
                  </div>
                  <span className="mono text-white tnum text-right">{val as string}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5 panel-flat overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 hairline" style={{ borderTop: 0 }}>
            <div className="text-[12px]"><span className="text-white">Лиды</span> <span className="t-40 ml-1 mono">134</span></div>
            <div className="seg" style={{ padding: 2 }}>
              <button className="seg-btn active" style={{ padding: "4px 10px", fontSize: 11 }}>Все</button>
              <button className="seg-btn" style={{ padding: "4px 10px", fontSize: 11 }}>Q · 17</button>
            </div>
          </div>
          <table className="lt">
            <thead>
              <tr><th>Компания</th><th>Город</th><th className="text-right">Score</th></tr>
            </thead>
            <tbody>
              {[
                { src: "2G", color: "var(--sky)", co: "Птицефабрика «Юг»", inn: "ИНН 7017234567", city: "Томск", score: 92 },
                { src: "ЕГ", color: "var(--amber)", co: "АО «Сибирская аграрная»", inn: "ИНН 7017012345", city: "Томск", score: 88 },
                { src: "ЯК", color: "var(--green)", co: "КФХ «Турунтаево»", inn: "ИНН 7014099887", city: "с. Турунтаево", score: 81 },
                { src: "2G", color: "var(--sky)", co: "Межениновская ПТФ", inn: "ИНН 7014048561", city: "с. Межениновка", score: 78 },
                { src: "ЕГ", color: "var(--amber)", co: "ООО «Томь-Агро»", inn: "ИНН 7017341290", city: "Северск", score: 74 },
                { src: "ЯК", color: "var(--green)", co: "СПК «Нелюбино»", inn: "ИНН 7014011230", city: "с. Нелюбино", score: 64 },
              ].map((row, i) => (
                <tr key={i}>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="mono text-[10px]" style={{ color: row.color }}>{row.src}</span>
                      <span style={{ fontWeight: i === 0 ? 500 : 400 }}>{row.co}</span>
                    </div>
                    <div className="t-40 mono text-[10px] mt-0.5">{row.inn}</div>
                  </td>
                  <td className="t-72">{row.city}</td>
                  <td className="text-right">
                    <div className="flex items-center gap-2 justify-end">
                      <div className="scorebar"><div style={{ width: `${row.score}%` }} /></div>
                      <span className="mono">{row.score}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-5 py-3 hairline flex items-center text-[11px]">
            <span className="t-40">показано 6 из 134</span>
            <a className="ml-auto text-white flex items-center gap-1.5 cursor-pointer">
              смотреть все
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

function BubbleChart() {
  const VW = 760, VH = 360;
  const ML = 64, MR = 24, MT = 24, MB = 44;
  const W = VW - ML - MR;
  const H = VH - MT - MB;
  const xMin = 30, xMax = 200, yMin = 0, yMax = 55, rMin = 6, rMax = 32;
  const qMax = Math.max(...BUBBLE_DATA.map((d) => d.qual));
  const X = (v: number) => ML + ((v - xMin) / (xMax - xMin)) * W;
  const Y = (v: number) => MT + H - ((v - yMin) / (yMax - yMin)) * H;
  const R = (q: number) => rMin + (Math.sqrt(q) / Math.sqrt(qMax)) * (rMax - rMin);

  const xTicks = [40, 80, 120, 160, 200];
  const yTicks = [10, 20, 30, 40, 50];

  // medians
  const medX = [...BUBBLE_DATA].map((d) => d.rev).sort((a, b) => a - b)[Math.floor(BUBBLE_DATA.length / 2)];
  const medY = [...BUBBLE_DATA].map((d) => d.leads).sort((a, b) => a - b)[Math.floor(BUBBLE_DATA.length / 2)];

  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  return (
    <div className={"bubble-wrap" + (hoverIdx !== null ? " has-hover" : "")}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="eyebrow">регионы · сводка</div>
          <div className="text-[15px] light mt-1">Лиды по выручке и объёму</div>
        </div>
        <div className="t-40 mono text-[10px] text-right">
          9 регионов
          <br />
          134 лида
        </div>
      </div>

      <svg className="w-full" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="b-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(168,197,192,0.55)" />
            <stop offset="100%" stopColor="rgba(168,197,192,0)" />
          </radialGradient>
        </defs>

        {/* grid */}
        <g stroke="rgba(255,255,255,0.05)" strokeWidth="0.5" fill="none">
          {yTicks.map((t) => <path key={`y${t}`} d={`M ${ML} ${Y(t)} H ${VW - MR}`} />)}
          {xTicks.map((t) => <path key={`x${t}`} d={`M ${X(t)} ${MT} V ${MT + H}`} />)}
        </g>

        {/* axes */}
        <g fontFamily="Geist Mono" fontSize="9.5" fill="rgba(255,255,255,0.35)">
          {yTicks.map((t) => (
            <text key={`yl${t}`} x={ML - 10} y={Y(t) + 3} textAnchor="end">{t}</text>
          ))}
          {xTicks.map((t) => (
            <text key={`xl${t}`} x={X(t)} y={VH - MB + 18} textAnchor="middle">{t}M</text>
          ))}
          <text x={ML} y={MT - 8} fill="rgba(255,255,255,0.55)" fontSize="10.5">лиды собрано</text>
          <text x={VW - MR} y={VH - 12} textAnchor="end" fill="rgba(255,255,255,0.55)" fontSize="10.5">медианная выручка, ₽M →</text>
        </g>

        {/* medians */}
        <g>
          <line x1={X(medX)} y1={MT} x2={X(medX)} y2={MT + H} stroke="rgba(168,197,192,0.18)" strokeWidth="0.6" strokeDasharray="2,3" />
          <line x1={ML} y1={Y(medY)} x2={VW - MR} y2={Y(medY)} stroke="rgba(168,197,192,0.18)" strokeWidth="0.6" strokeDasharray="2,3" />
          <text x={VW - MR - 4} y={Y(medY) - 4} textAnchor="end" fontFamily="Geist Mono" fontSize="8.5" fill="rgba(168,197,192,0.45)">медиана</text>
        </g>

        {/* bubbles */}
        <g>
          {BUBBLE_DATA.map((d, i) => {
            const cx = X(d.rev), cy = Y(d.leads), r = R(d.qual);
            const isHover = hoverIdx === i;
            return (
              <g
                key={d.short}
                className={"bubble-group" + (d.primary ? " is-primary" : "") + (isHover ? " is-hover" : "")}
                onMouseEnter={() => setHoverIdx(i)}
                onMouseLeave={() => setHoverIdx(null)}
              >
                {d.primary && (
                  <>
                    <circle cx={cx} cy={cy} r={r + 10} fill="url(#b-glow)" opacity="0.7" />
                    <circle cx={cx} cy={cy} r={r + 4} fill="none" stroke="var(--mint)" strokeOpacity="0.4" strokeWidth="0.7">
                      <animate attributeName="r" values={`${r + 2};${r + 12};${r + 2}`} dur="2.8s" repeatCount="indefinite" />
                      <animate attributeName="stroke-opacity" values="0.5;0;0.5" dur="2.8s" repeatCount="indefinite" />
                    </circle>
                  </>
                )}
                <circle
                  className="bubble-circle"
                  cx={cx} cy={cy} r={r.toFixed(1)}
                  fill={d.primary ? "rgba(168,197,192,0.20)" : "rgba(168,197,192,0.10)"}
                  stroke={d.primary ? "var(--mint)" : "rgba(168,197,192,0.55)"}
                  strokeWidth="1"
                />
                <text className="bubble-label" x={cx + r + 8} y={cy - 2} fontFamily="Inter" fontSize="11" fill="rgba(255,255,255,0.75)">
                  {d.short}
                </text>
                <text className="bubble-num" x={cx + r + 8} y={cy + 11} fontFamily="Geist Mono" fontSize="9.5" fill="rgba(168,197,192,0.7)">
                  {d.leads} лид · {d.qual} qual
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="bubble-legend mt-3 flex items-center gap-5 text-[11px] t-48 flex-wrap">
        <span className="flex items-center gap-2">
          <span className="bub-dot" style={{ width: 6, height: 6 }} />
          &lt; 30 qual.
        </span>
        <span className="flex items-center gap-2">
          <span className="bub-dot" style={{ width: 10, height: 10 }} />
          30–60 qual.
        </span>
        <span className="flex items-center gap-2">
          <span className="bub-dot" style={{ width: 15, height: 15 }} />
          60+ qual.
        </span>
        <span className="ml-auto mono">размер · qualified</span>
      </div>
    </div>
  );
}

/* ── View: Lead ──────────────────────────────────────── */

function ViewLead({ active }: { active: boolean }) {
  const scoreRef = useCountUp<HTMLSpanElement>(92);
  return (
    <section className={"view" + (active ? " active" : "")}>
      <div className="flex items-end justify-between mb-6 flex-wrap gap-6">
        <div>
          <div className="eyebrow">лид № 0042 · 2GIS+ЕГРЮЛ</div>
          <div className="h1 mt-2" style={{ fontSize: 56 }}>Птицефабрика «Юг»</div>
          <div className="text-[13px] t-72 mt-1">
            ООО «Птицефабрика Юг» <span className="t-28">·</span>{" "}
            <span className="mono">ИНН 7017234567</span> <span className="t-28">·</span> Томск
          </div>
        </div>
        <div className="flex items-center gap-2 flex-none">
          <button className="ghost rounded-full px-3.5 py-2 text-[12.5px]">В кампанию</button>
          <button className="brand rounded-full px-4 py-2 text-[12.5px]">Связаться</button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-12 lg:col-span-4 panel-flat p-5">
          <div className="flex items-end justify-between">
            <div className="eyebrow">lead score</div>
            <div className="flex items-baseline gap-1">
              <span className="h1 tnum" style={{ fontSize: 72 }}>
                <span ref={scoreRef} className="count-num">0</span>
              </span>
              <span className="t-40 text-[14px]">/ 100</span>
            </div>
          </div>
          <div className="h-[5px] rounded-full mt-3" style={{ background: "rgba(255,255,255,0.08)" }}>
            <div
              className="h-full rounded-full"
              style={{ width: "92%", background: "var(--mint)", boxShadow: "0 0 12px rgba(168,197,192,0.45)" }}
            />
          </div>
          <div className="grid grid-cols-3 gap-2 mt-4 text-[11px]">
            {[
              ["соответствие", "98"],
              ["контактность", "94"],
              ["платёжесп.", "86"],
            ].map(([l, v]) => (
              <div key={l} className="panel-flat px-3 py-2">
                <div className="t-40 mb-0.5">{l}</div>
                <div className="mono tnum">{v}</div>
              </div>
            ))}
          </div>
          <div className="hairline mt-5 pt-4">
            <div className="eyebrow mb-2">признаки</div>
            <div className="flex flex-wrap gap-2">
              {["ОКВЭД 01.47 ✓", "штат 200+", "выручка 320M", "сайт активен", "тендеры ✓"].map((t) => (
                <span key={t} className="panel-thin px-2.5 py-0.5 text-[11px]">{t}</span>
              ))}
            </div>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 panel-flat p-5">
          <div className="eyebrow mb-3">контакты</div>
          <div className="space-y-3 text-[12.5px]">
            <div className="flex items-center gap-3">
              <span className="dot dot-em" />
              <span className="mono">info@ptf-yug.ru</span>
              <span className="ml-auto t-40 text-[10px]">SMTP+MX ✓</span>
            </div>
            <div className="flex items-center gap-3">
              <svg className="t-48" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" />
              </svg>
              <span className="mono">+7 382 245-18-90</span>
              <span className="ml-auto t-40 text-[10px]">основной</span>
            </div>
            <div className="flex items-center gap-3">
              <svg className="t-48" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="12" r="9" />
                <path d="M3 12h18M12 3a13 13 0 010 18 13 13 0 010-18z" />
              </svg>
              <span className="mono">ptf-yug.ru</span>
              <span className="ml-auto t-40 text-[10px]">site online</span>
            </div>
          </div>
          <div className="hairline mt-5 pt-4">
            <div className="eyebrow mb-2">ЛПР</div>
            <div className="text-[13px]">Сергей Ковалёв</div>
            <div className="t-48 text-[11.5px]">директор по закупкам · подтверждено LinkedIn</div>
          </div>
          <div className="hairline mt-5 pt-4">
            <div className="eyebrow mb-2">адрес</div>
            <div className="t-72 text-[12px] leading-snug">
              634009, Томская область,
              <br />
              г. Томск, ул. Кузовлёвский тракт, 12
            </div>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 panel-flat p-5">
          <div className="eyebrow mb-3">хронология</div>
          <div className="space-y-3 text-[12px]">
            {[
              ["14:23", <>обогащён <span className="t-48">· score 92</span></>],
              ["14:21", "подтверждён email · SMTP 220"],
              ["14:19", <>сматчен с ЕГРЮЛ <span className="mono t-40">7017234567</span></>],
              ["14:18", <>попал в очередь <span className="t-48">· источник: 2GIS</span></>],
              ["26.02", "добавлен в проект «Кормовые · Томск»"],
            ].map(([t, c], i) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mono t-40 w-[60px]">{t as string}</span>
                <div>{c}</div>
              </div>
            ))}
          </div>
          <div className="hairline mt-5 pt-4">
            <div className="flex items-center justify-between mb-2">
              <div className="eyebrow">заметки</div>
              <span className="t-40 text-[10px] mono">214 / 1000</span>
            </div>
            <div className="text-[12px] t-72 leading-[1.55]">
              Отдел закупок отвечает после 14:00 МСК. Прислали запрос по премиксам — нужен прайс на партии 5–10 тонн. Договорились созвониться в среду.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Features ──────────────────────────────────────── */

function FeaturesSection() {
  return (
    <section className="relative">
      <div className="max-w-[1320px] mx-auto px-6 py-24">
        <div className="grid grid-cols-12 gap-10 mb-14">
          <div className="col-span-12 lg:col-span-6">
            <div className="eyebrow mb-3">шаг 03 · что внутри</div>
            <h2 className="h2" style={{ fontSize: "clamp(40px,4.4vw,64px)" }}>
              Не каталог компаний.
              <br />
              Машина по производству лидов.
            </h2>
          </div>
          <div className="col-span-12 lg:col-span-6 lg:pt-10 text-[15px] t-72 light leading-[1.55]">
            База подключена к 8 верифицированным источникам, обновляется ежедневно и работает
            как единая поверхность. Никаких CSV из неизвестных папок.
          </div>
        </div>

        <div className="grid grid-cols-12 gap-5">
          <div className="col-span-12 md:col-span-4 panel-flat p-6">
            <div className="flex items-center justify-between"><div className="eyebrow">обогащение</div><span className="mono t-40 text-[10px]">01</span></div>
            <h3 className="h3 mt-3" style={{ fontSize: 24 }}>Email, телефон, ЛПР, выручка — для каждой компании.</h3>
            <p className="t-72 text-[13px] mt-3 leading-[1.55]">SMTP+MX-проверка, валидация по ФНС, сопоставление ЛПР с открытыми профилями.</p>
            <div className="mt-5 hairline pt-4 grid grid-cols-3 text-[11px]">
              <div><div className="t-40">deliver</div><div className="mono mt-0.5 tnum">94%</div></div>
              <div><div className="t-40">match</div><div className="mono mt-0.5 tnum">88%</div></div>
              <div><div className="t-40">ЛПР</div><div className="mono mt-0.5 tnum">71%</div></div>
            </div>
          </div>
          <div className="col-span-12 md:col-span-4 panel-flat p-6">
            <div className="flex items-center justify-between"><div className="eyebrow">scoring</div><span className="mono t-40 text-[10px]">02</span></div>
            <h3 className="h3 mt-3" style={{ fontSize: 24 }}>100-балльный скоринг под ваш промпт.</h3>
            <p className="t-72 text-[13px] mt-3 leading-[1.55]">Соответствие, контактность, платёжеспособность — три оси, прозрачные веса, объяснение для каждого балла.</p>
            <div className="mt-5 hairline pt-4">
              <div className="flex items-center justify-between text-[11px] t-48 mb-1.5"><span>средний</span><span className="mono">72 / 100</span></div>
              <div className="h-[3px] rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
                <div className="h-full rounded-full" style={{ width: "72%", background: "var(--mint)" }} />
              </div>
            </div>
          </div>
          <div className="col-span-12 md:col-span-4 panel-flat p-6">
            <div className="flex items-center justify-between"><div className="eyebrow">экспорт</div><span className="mono t-40 text-[10px]">03</span></div>
            <h3 className="h3 mt-3" style={{ fontSize: 24 }}>CSV, API, webhook прямо в CRM.</h3>
            <p className="t-72 text-[13px] mt-3 leading-[1.55]">Bitrix24, amoCRM, Pipedrive — нативные коннекторы. По API — 50 запросов в секунду.</p>
            <div className="mt-5 hairline pt-4 flex flex-wrap gap-2 text-[11px]">
              {["Bitrix24", "amoCRM", "Pipedrive", "webhook"].map((c) => (
                <span key={c} className="panel-thin px-2.5 py-0.5">{c}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── CTA + Footer ──────────────────────────────────── */

function CtaSection() {
  return (
    <section className="relative">
      <div className="max-w-[1320px] mx-auto px-6 py-24">
        <div className="panel p-10 lg:p-14 text-center">
          <div className="eyebrow mb-5">раннее открытие</div>
          <h2 className="h2 max-w-[820px] mx-auto" style={{ fontSize: "clamp(40px,4.8vw,72px)" }}>
            Покажите, кого вы ищете —
            <br />
            посмотрите, что мы найдём.
          </h2>
          <p className="mt-6 max-w-[520px] mx-auto t-72 text-[15px] light">
            2 ₽ за обогащённый контакт. Бесплатные первые 100 — без карты.
          </p>
          <div className="mt-9 flex items-center justify-center gap-3 flex-wrap">
            <Link href="/register" className="brand rounded-full px-6 py-3 text-[14px] flex items-center gap-2">
              Получить доступ
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </Link>
            <a className="ghost rounded-full px-6 py-3 text-[14px] cursor-pointer">Связаться с командой</a>
          </div>
        </div>
      </div>
    </section>
  );
}

function FooterSection() {
  return (
    <footer className="hairline">
      <div className="max-w-[1320px] mx-auto px-6 py-10 grid grid-cols-12 gap-8 t-48 text-[12px]">
        <div className="col-span-12 md:col-span-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-6 h-6 rounded-md" style={{ background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)" }} />
            <span className="text-white text-[14px]" style={{ fontWeight: 500 }}>база</span>
          </div>
          <p className="leading-[1.55] max-w-[260px]">
            Лид-инжиниринг для команд продаж. Промпт → готовая воронка.
          </p>
        </div>
        {[
          { title: "Продукт", items: ["Возможности", "Источники", "Цены", "API"] },
          { title: "Компания", items: ["О нас", "Журнал", "Карьера", "Контакты"] },
          { title: "Документы", items: ["Условия", "Конфиденциальность", "Обработка ПДн", "152-ФЗ"] },
        ].map((g) => (
          <div key={g.title} className="col-span-6 md:col-span-2">
            <div className="text-white mb-3 text-[12px]">{g.title}</div>
            <div className="space-y-2">
              {g.items.map((i) => <div key={i}>{i}</div>)}
            </div>
          </div>
        ))}
        <div className="col-span-6 md:col-span-2 md:text-right">
          <div className="text-white mb-3 text-[12px]">Статус</div>
          <div className="flex md:justify-end items-center gap-2">
            <span className="dot dot-em" />
            <span>все системы стабильны</span>
          </div>
          <div className="mono mt-2">latency 184 мс</div>
        </div>
      </div>
      <div className="hairline">
        <div className="max-w-[1320px] mx-auto px-6 py-6 flex items-center justify-between t-40 text-[11px]">
          <div>© 2026 База · usebaza.ru · v0.42 предварительный обзор</div>
          <div className="mono">№ 0042 / Tomsk · LTR</div>
        </div>
      </div>
    </footer>
  );
}

/* ── Page wrapper ──────────────────────────────────── */

export function LandingPage() {
  useCursorSpotlight();
  return (
    <div className="min-h-screen bg-[var(--bg)] text-white">
      <CornerMeta />
      <TopNav />
      <HeroSection />
      <PromptDemo />
      <ProductFrame />
      <FeaturesSection />
      <CtaSection />
      <FooterSection />
    </div>
  );
}

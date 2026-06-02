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
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";

import { getToken } from "@/lib/auth";
import { Reveal } from "@/components/reveal";
import { Magnetic } from "@/components/magnetic";

/* ─────────────────────────────────────────────────────────────
   LIVE DEMO DATA — fed from the public, unauthenticated
   GET {NEXT_PUBLIC_API_URL}/public/landing endpoint.
   Every consumer falls back to its original hardcoded value when
   `stats` is null (still loading) or the endpoint reports
   available:false (demo base not seeded) — so the page renders
   identically when no data has arrived. No layout shift, no flash.
   ───────────────────────────────────────────────────────────── */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

type LandingStats = {
  available: boolean;
  totals: { leads: number; enriched: number; with_email: number; with_phone: number; qualified: number };
  rates: { enrichment: number; email: number; phone: number; qualified: number };
  avg_score: number;
  sources: Array<{ source: string; count: number }>;
  by_city: Array<{ city: string; count: number; avg_score: number }>;
  funnel: { found: number; added: number; enriched: number; qualified: number };
  samples: Array<{
    company: string;
    city: string;
    score: number;
    source: string;
    has_email: boolean;
    has_phone: boolean;
    email_valid?: boolean;
  }>;
  generated_at?: string;
};

/** Maps backend source codes → RU display labels used across the demos. */
const SOURCE_LABELS: Record<string, string> = {
  "2gis": "2ГИС",
  yandex_maps: "Яндекс",
  rusprofile: "ЕГРЮЛ",
  searxng: "Web",
  bing: "Bing",
};
const sourceLabel = (code: string) => SOURCE_LABELS[code] ?? code;

/** Short 2-letter badge for the leads table (matches existing visual style). */
const sourceBadge = (code: string): { src: string; color: string } => {
  switch (code) {
    case "2gis":
      return { src: "2G", color: "var(--sky)" };
    case "yandex_maps":
      return { src: "ЯК", color: "var(--green)" };
    case "rusprofile":
      return { src: "ЕГ", color: "var(--amber)" };
    case "searxng":
      return { src: "Web", color: "var(--mint)" };
    case "bing":
      return { src: "Bi", color: "var(--sky)" };
    default:
      return { src: code.slice(0, 2).toUpperCase(), color: "var(--mint)" };
  }
};

/** Context carrying the fetched stats (null until/unless data arrives). */
const StatsContext = createContext<LandingStats | null>(null);
const useStats = () => useContext(StatsContext);

/**
 * Fetch /public/landing ONCE on mount with a plain fetch (NOT the @/lib/api
 * helper — that redirects to /login on 401, which would break this public
 * page). On any error or available:false, stats stays null and every block
 * keeps its hardcoded fallback. Render is never blocked on this fetch.
 */
function useLandingStats(): LandingStats | null {
  const [stats, setStats] = useState<LandingStats | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/public/landing`, { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as LandingStats;
        if (!cancelled && data && data.available) setStats(data);
      } catch {
        // leave stats null → fallbacks
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  return stats;
}

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
  // Start null so SSR and the first client render produce identical markup.
  // Rendering a live `new Date()` during SSR caused a document-level hydration
  // mismatch (server time ≠ client time) → React threw away the server HTML and
  // re-rendered the whole page = the load-time flash. Fill in only after mount.
  const [s, setS] = useState<string | null>(null);
  useEffect(() => {
    setS(formatClock(new Date()));
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
      <span>{clock}</span>
    </div>
  );
}

function TopNav() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

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
        </Link>
        <nav className="hidden md:flex items-center gap-1 ml-4">
          <a href="#product" className="nav-link">Продукт</a>
          <a href="#sources" className="nav-link">Возможности</a>
          <Link href="/plans" className="nav-link">Цены</Link>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden md:flex items-center gap-2 text-[11px] t-48">
            <span className="dot dot-em" />
            все системы стабильны
          </span>
          {authed === null ? null : authed ? (
            <Link
              href="/dashboard"
              className="hidden md:inline-flex brand rounded-full px-4 py-1.5 text-[12.5px]"
            >
              Открыть дашборд →
            </Link>
          ) : (
            <>
              <Link href="/login" className="hidden md:inline-flex ghost rounded-full px-3.5 py-1.5 text-[12.5px]">Войти</Link>
              <Link href="/register" className="hidden md:inline-flex brand rounded-full px-4 py-1.5 text-[12.5px]">Получить доступ</Link>
            </>
          )}
          {/* Hamburger — visible only on mobile */}
          <button
            className="md:hidden flex flex-col justify-center items-center w-9 h-9 gap-[5px] rounded-lg"
            style={{ background: "rgba(255,255,255,0.06)", border: "1px solid var(--line)" }}
            onClick={() => setMobileOpen((o) => !o)}
            aria-label={mobileOpen ? "Закрыть меню" : "Открыть меню"}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? (
              <>
                <span className="block w-4 h-[1.5px] bg-white" style={{ transform: "rotate(45deg) translate(3.5px,3.5px)" }} />
                <span className="block w-4 h-[1.5px] bg-white" style={{ transform: "rotate(-45deg) translate(3.5px,-3.5px)" }} />
              </>
            ) : (
              <>
                <span className="block w-4 h-[1.5px]" style={{ background: "rgba(255,255,255,0.7)" }} />
                <span className="block w-4 h-[1.5px]" style={{ background: "rgba(255,255,255,0.7)" }} />
                <span className="block w-4 h-[1.5px]" style={{ background: "rgba(255,255,255,0.7)" }} />
              </>
            )}
          </button>
        </div>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div
          className="md:hidden"
          style={{
            background: "rgba(10,12,14,0.97)",
            backdropFilter: "blur(20px)",
            borderTop: "1px solid var(--line)",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <nav className="max-w-[1320px] mx-auto px-6 py-4 flex flex-col gap-1">
            <a
              href="#product"
              className="nav-link py-2.5 text-[14px]"
              onClick={() => setMobileOpen(false)}
            >
              Продукт
            </a>
            <a
              href="#sources"
              className="nav-link py-2.5 text-[14px]"
              onClick={() => setMobileOpen(false)}
            >
              Возможности
            </a>
            <Link
              href="/plans"
              className="nav-link py-2.5 text-[14px]"
              onClick={() => setMobileOpen(false)}
            >
              Цены
            </Link>
            <div className="hairline mt-2 pt-3 flex flex-col gap-2">
              {authed === null ? null : authed ? (
                <Link
                  href="/dashboard"
                  className="brand rounded-full px-4 py-2.5 text-[13px] text-center"
                  onClick={() => setMobileOpen(false)}
                >
                  Открыть дашборд →
                </Link>
              ) : (
                <>
                  <Link
                    href="/login"
                    className="ghost rounded-full px-4 py-2.5 text-[13px] text-center"
                    onClick={() => setMobileOpen(false)}
                  >
                    Войти
                  </Link>
                  <Link
                    href="/register"
                    className="brand rounded-full px-4 py-2.5 text-[13px] text-center"
                    onClick={() => setMobileOpen(false)}
                  >
                    Получить доступ
                  </Link>
                </>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}

/* ── Hero + Live mini-card ──────────────────────────────────── */

function HeroLiveCard() {
  const stats = useStats();
  // Rotating company/city/score pool driving the hero feed: real samples when
  // available, else the hardcoded COMPANY_POOL fallback. Keeps [co, city, score].
  const heroPool = useMemo<Array<[string, string, number]>>(() => {
    if (stats?.samples.length) {
      return stats.samples.map((s) => [s.company, s.city, s.score] as [string, string, number]);
    }
    return COMPANY_POOL.map(([co, city, , score]) => [co, city, score] as [string, string, number]);
  }, [stats]);
  const pick = useCallback(
    () => heroPool[Math.floor(Math.random() * heroPool.length)],
    [heroPool],
  );
  // Always-current picker so the long-lived feed ticker (started once on
  // scroll-into-view) keeps drawing from real samples once they load.
  const pickRef = useRef(pick);
  useEffect(() => {
    pickRef.current = pick;
  }, [pick]);

  const [count, setCount] = useState(0);
  const [feed, setFeed] = useState<
    Array<{ id: string; co: string; meta: string; score: number; out?: boolean }>
  >([]);
  const seedRef = useRef(false);
  const sectionRef = useRef<HTMLDivElement | null>(null);

  // The hero number is the REAL demo-base lead count — no fabricated growth.
  useEffect(() => {
    if (stats) setCount(stats.totals.leads);
  }, [stats]);

  // start the sample feed rotation when the section scrolls into view
  useEffect(() => {
    if (!sectionRef.current) return;
    const io = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (!en.isIntersecting || seedRef.current) continue;
        seedRef.current = true;
        // seed 3 rows
        const seed: typeof feed = [];
        for (let k = 0; k < 3; k++) {
          const [co, city, score] = pick();
          seed.unshift({ id: `${Date.now()}-${k}`, co, meta: city, score });
        }
        setFeed(seed);
        // rotate sample companies through the feed (showcase, not new leads)
        const feedTimer = scheduleTickFeed();
        return () => {
          clearTimeout(feedTimer);
        };
      }
    }, { threshold: 0.3 });
    io.observe(sectionRef.current);
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scheduleTickFeed = useCallback(() => {
    return window.setTimeout(function pushLead() {
      const [co, city, score] = pickRef.current();
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
    <div ref={sectionRef} className="col-span-1 lg:col-span-4 lg:pl-6 reveal" style={{ animationDelay: "0.34s" }}>
      <div className="panel elev-2 p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="dot dot-em" />
            <span className="text-[12px] t-72">демо-база · реальный пример</span>
          </div>
        </div>
        <div className="h1 tnum hero-bignum" style={{ fontSize: 84 }}>
          {count.toLocaleString("ru-RU")}
        </div>
        <div className="text-[12px] t-72 mt-1">лидов в демо-базе</div>
        <div className="mt-4 flex items-baseline gap-3 text-[12px]">
          <span className="mono tnum" style={{ color: "var(--green)" }}>
            {stats ? Math.round(stats.rates.enrichment * 100) : 0}%
          </span>
          <span className="t-48">обогащено</span>
        </div>

        <div className="mt-5 hairline pt-4">
          <div className="eyebrow mb-3">из базы</div>
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
            <div className="mono mt-0.5 tnum text-white text-[13px]">
              {stats ? Math.round(stats.rates.qualified * 100) : "21.0"}%
            </div>
          </div>
          <div>
            <div className="t-48">средний score</div>
            <div className="mono mt-0.5 tnum text-white text-[13px]">
              {stats ? Math.round(stats.avg_score) : 72} / 100
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Letter-by-letter reveal helper ────────────────────────────────
   Splits text into per-letter <span class="letter"> chunks (each with a
   --letter-index so the keyframe staggers 28ms/letter), but groups them by
   WORD inside an inline-block .letter-word with a real breakable space
   between words. So letters within a word stay together while the headline
   still wraps across lines on narrow screens — the previous &nbsp; version
   forced one unbreakable line that blew past the mobile viewport. */
function SplitLetters({ text, startIndex = 0 }: { text: string; startIndex?: number }) {
  const words = text.split(" ");
  let idx = startIndex;
  const out: React.ReactNode[] = [];
  words.forEach((word, wi) => {
    const letters = Array.from(word).map((ch) => {
      const li = idx++;
      return (
        <span key={li} className="letter" style={{ ["--letter-index" as never]: li }}>
          {ch}
        </span>
      );
    });
    out.push(
      <span key={`w${wi}`} className="letter-word">
        {letters}
      </span>,
    );
    // Breakable space between words (skip after the last word).
    if (wi < words.length - 1) {
      idx++; // keep the cascade timing consistent with the space
      out.push(" ");
    }
  });
  return <>{out}</>;
}

function HeroSection() {
  return (
    <section className="relative overflow-hidden" style={{ minHeight: "100vh" }}>
      {/* Animated mesh gradient backdrop — stands in for a cinematic video
          loop until Higgsfield credits are topped up. Three radial blobs
          drift on Lissajous-like trajectories, giving the dark canvas a
          living quality without dragging WebGL into the bundle. */}
      <div className="mesh-bg" aria-hidden>
        <div className="mesh-aux" />
      </div>
      {/* Hero scenery drifts upward as the user scrolls — gives the impression
          that the page is sliding into the canvas, not the canvas underneath
          the page. Each plane has its own parallax speed for depth. */}
      <div className="field parallax-slow" />
      <div className="grid-lines parallax-mid" />
      <div className="grain" />

      <div className="relative z-10 max-w-[1320px] mx-auto px-6 pt-24 pb-20">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-end">
          <div className="col-span-1 lg:col-span-8 min-w-0">
            <div className="flex flex-wrap items-center gap-3 mb-7 reveal" style={{ animationDelay: "0.05s" }}>
              <span className="panel-thin px-3 py-1 text-[11px] flex items-center gap-2">
                <span className="dot dot-em" />
                раннее открытие
              </span>
              <span className="t-48 text-[12px]">для B2B-команд продаж в РФ</span>
            </div>
            <h1
              className="h1 letter-reveal"
              style={{ fontSize: "clamp(34px,9vw,128px)" }}
            >
              <SplitLetters text="Лиды, которые " />
              <span style={{ color: "var(--mint)" }} className="serif">
                <SplitLetters text="созревают" startIndex={14} />
              </span>
              <br />
              <SplitLetters text="до того, как вы их откроете." startIndex={23} />
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
              <Magnetic strength={14}>
                <Link
                  href="/register"
                  className="brand rounded-full px-5 py-2.5 text-[13.5px] flex items-center gap-2"
                >
                  Получить доступ
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </Link>
              </Magnetic>
              <Magnetic strength={10}>
                <a
                  href="#product"
                  className="ghost rounded-full px-5 py-2.5 text-[13.5px] flex items-center gap-2 cursor-pointer"
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                  Посмотреть продукт · 2 мин
                </a>
              </Magnetic>
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

const PROMPT_TAGS: Array<{ text: string; chip: string }> = [
  { text: "кормовые добавки", chip: "продукт" },
  { text: "крупного рогатого скота", chip: "отрасль · КРС" },
  { text: "фермерские хозяйства", chip: "ОКВЭД 01.4*" },
  { text: "Сибирского ФО", chip: "регион · СФО" },
  { text: "от 200 голов", chip: "размер" },
  { text: "email и закупщиком", chip: "контакт" },
];

function PromptDemo() {
  const stats = useStats();
  // Real pipeline figures where the endpoint backs them; the two raw funnel
  // counts (12 410 → 384 → 217) have no source and stay illustrative.
  const srcCount = stats?.sources.length ?? 8;            // 01 · парсинг
  const smtpPct = stats ? Math.round(stats.rates.email * 100) : 78; // 04 · SMTP+MX
  const finalLeads = stats?.funnel.added ?? 134;          // 05 · готово
  const regionCount = stats?.by_city.length ?? 9;         // subtitle

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

  // Inline highlight of the matched phrases (mint underline). The entity chips
  // are rendered as a separate row below the prompt (see render) so they can
  // never overlap the wrapping prompt text.
  const Tagged = () => {
    const parts: React.ReactNode[] = [];
    let remaining = targetText;
    let key = 0;
    PROMPT_TAGS.forEach((tag, idx) => {
      const at = remaining.indexOf(tag.text);
      if (at < 0) return;
      if (at > 0) parts.push(<span key={key++}>{remaining.slice(0, at)}</span>);
      parts.push(
        <span key={key++} className={"ptag" + (idx < litCount ? " lit" : "")}>
          {tag.text}
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
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          <div className="col-span-1 lg:col-span-5">
            <div className="eyebrow mb-3">шаг 01 · описание</div>
            <h2 className="h2" style={{ fontSize: "clamp(28px,4.4vw,64px)" }}>
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

          <div ref={wrapRef} className="col-span-1 lg:col-span-7">
            <div className="panel elev-1 p-5">
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

              {/* Extracted entities — light up one-by-one. Kept as a row BELOW
                  the prompt (not floating chips inside it) so they can never
                  overlap the wrapping prompt text. */}
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                {PROMPT_TAGS.map((t, i) => {
                  const lit = phase === "parsed" && i < litCount;
                  return (
                    <span
                      key={t.chip}
                      className="chip chip-sans"
                      style={{
                        fontSize: "10px",
                        opacity: lit ? 1 : 0.32,
                        color: lit ? "var(--mint)" : "rgba(255,255,255,0.45)",
                        borderColor: lit ? "rgba(168,197,192,0.40)" : "var(--line-2)",
                        transition: "opacity .35s ease, color .35s ease, border-color .35s ease",
                      }}
                    >
                      {t.chip}
                    </span>
                  );
                })}
              </div>

              <div className="mt-5 grid grid-cols-2 sm:grid-cols-5 gap-2 text-[11px]">
                {[
                  ["01 · парсинг", `${srcCount} источников`, 100, "var(--mint)"],
                  // 02/03 raw funnel counts are illustrative (no endpoint source).
                  ["02 · матчинг", "12 410 → 384", 100, "var(--mint)"],
                  ["03 · дедуп", "→ 217", 100, "var(--mint)"],
                  ["04 · обогащение", "SMTP+MX", smtpPct, "var(--mint)"],
                  ["05 · готово", `${phase === "parsed" ? finalLeads : 0} лидов`, 100, "var(--green)"],
                ].map(([label, val, w], i) => (
                  <div key={i} className={`panel-flat elev-1 px-3 py-3${i === 4 && phase === "parsed" ? " ring-1 ring-[var(--mint)]/20" : ""}`}>
                    <div className="t-40 mono text-[10px]">{label as string}</div>
                    <div className="text-white tnum mt-1">{val as string}</div>
                    <div className="score-bar score-bar--sm mt-2" style={{ "--score": (w as number) / 100 } as React.CSSProperties}>
                      <div className="score-bar__fill" />
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-5 flex items-center gap-3 t-48 text-[11px] hairline pt-4">
                <span className="mono">{regionCount} регионов · ОКВЭД 01.4*</span>
                <span className="mx-2">·</span>
                <span>отбор по выручке &gt; 60M ₽</span>
                <Link href="/register" className="ml-auto text-[12px] flex items-center gap-2 hover:text-white transition-colors">
                  смотреть результат
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </Link>
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
    <section id="product" className="relative">
      <div className="max-w-[1320px] mx-auto px-6 pt-6 pb-24">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between mb-7">
          <div>
            <div className="eyebrow mb-3">шаг 02 · работа с результатом</div>
            <h2 className="h2" style={{ fontSize: "clamp(28px,4.4vw,64px)" }}>
              Один экран от обзора
              <br />
              до карточки лида.
            </h2>
          </div>
          <div className="seg self-start sm:self-auto" role="tablist" aria-label="Вид дашборда">
            {[
              { k: "overview", label: "Обзор" },
              { k: "project", label: "Проект" },
              { k: "lead", label: "Лид" },
            ].map((v) => (
              <button
                key={v.k}
                id={`tab-${v.k}`}
                className={"seg-btn" + (view === v.k ? " active" : "")}
                role="tab"
                aria-selected={view === v.k}
                aria-controls={`panel-${v.k}`}
                onClick={() => setView(v.k as typeof view)}
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>

        {/* On phones the app mockup keeps its desktop proportions and scrolls
            horizontally inside this container, instead of crushing the rail +
            dashboards into 320px. .frame-scroll handles the overflow + min-width. */}
        <div className="frame-scroll">
        <div className="frame elev-2">
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
              <ViewOverview active={view === "overview"} tabId="tab-overview" panelId="panel-overview" />
              <ViewProject active={view === "project"} tabId="tab-project" panelId="panel-project" />
              <ViewLead active={view === "lead"} tabId="tab-lead" panelId="panel-lead" />
            </main>
          </div>
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

// Illustrative funnel midpoints with no dedicated /public/landing field —
// kept as fallbacks so the pipeline reads sensibly when no data is loaded.
const DEMO_FN_QUEUE = 142580;
const DEMO_FN_PARSER = 111210;
const DEMO_FN_DEDUP = 76994;
const DEMO_FN_ENRICH = 51328;
const DEMO_FN_READY = 29942;

// Decorative sparkline shapes reused for the source-mix rows (geometry only).
const SRC_SPARK_PATHS = [
  "M0 12 L10 11 L20 8 L30 9 L40 6 L50 7 L60 4 L70 5 L80 3",
  "M0 8 L10 10 L20 7 L30 9 L40 8 L50 6 L60 7 L70 5 L80 6",
  "M0 6 L10 8 L20 7 L30 11 L40 9 L50 12 L60 10 L70 13 L80 11",
  "M0 14 L10 12 L20 13 L30 10 L40 11 L50 9 L60 10 L70 8 L80 9",
  "M0 11 L10 11 L20 12 L30 10 L40 12 L50 11 L60 13 L70 12 L80 14",
];

// Original hardcoded source-mix rows — fallback when stats aren't loaded.
const DEMO_SOURCE_ROWS: Array<{ name: string; pct: number; num: string }> = [
  { name: "ЕГРЮЛ / ФНС", pct: 42, num: "59 884" },
  { name: "СПАРК / API", pct: 26, num: "37 070" },
  { name: "Отраслевые", pct: 18, num: "25 664" },
  { name: "Парс сайтов", pct: 9, num: "12 832" },
  { name: "Импорт CSV", pct: 5, num: "7 130" },
];

// Original hardcoded leads-table rows — fallback when no real samples exist.
type TableRow = {
  src: string;
  color: string;
  co: string;
  city: string;
  score: number;
  inn?: string;
  hasEmail?: boolean;
  hasPhone?: boolean;
};
const DEMO_TABLE_ROWS: TableRow[] = [
  { src: "2G", color: "var(--sky)", co: "Птицефабрика «Юг»", inn: "ИНН 7017234567", city: "Томск", score: 92 },
  { src: "ЕГ", color: "var(--amber)", co: "АО «Сибирская аграрная»", inn: "ИНН 7017012345", city: "Томск", score: 88 },
  { src: "ЯК", color: "var(--green)", co: "КФХ «Турунтаево»", inn: "ИНН 7014099887", city: "с. Турунтаево", score: 81 },
  { src: "2G", color: "var(--sky)", co: "Межениновская ПТФ", inn: "ИНН 7014048561", city: "с. Межениновка", score: 78 },
  { src: "ЕГ", color: "var(--amber)", co: "ООО «Томь-Агро»", inn: "ИНН 7017341290", city: "Северск", score: 74 },
  { src: "ЯК", color: "var(--green)", co: "СПК «Нелюбино»", inn: "ИНН 7014011230", city: "с. Нелюбино", score: 64 },
];

function ViewOverview({ active, tabId, panelId }: { active: boolean; tabId?: string; panelId?: string }) {
  const stats = useStats();
  // counters — real totals/funnel when loaded, else original hardcoded values.
  const liveRef = useCountUp<HTMLSpanElement>(stats?.funnel.found ?? 142580, { thin: true });
  const totalRef = useCountUp<HTMLSpanElement>(stats?.totals.leads ?? 2847, { thin: true });
  const enrichedRef = useCountUp<HTMLSpanElement>(stats?.totals.enriched ?? 1923, { thin: true });
  const emailRef = useCountUp<HTMLSpanElement>(stats?.totals.with_email ?? 1456, { thin: true });
  const scoreRef = useCountUp<HTMLSpanElement>(stats ? Math.round(stats.avg_score) : 72);
  // Funnel: queue→found, enrich→enriched, ready→qualified are real; the two
  // intermediate stages have no endpoint field → DEMO_* fallbacks.
  const fnQueueRef = useCountUp<HTMLSpanElement>(stats?.funnel.found ?? DEMO_FN_QUEUE, { thin: true });
  const fnParserRef = useCountUp<HTMLSpanElement>(stats?.funnel.added ?? DEMO_FN_PARSER, { thin: true });
  const fnDedupRef = useCountUp<HTMLSpanElement>(stats?.funnel.added ?? DEMO_FN_DEDUP, { thin: true });
  const fnEnrichRef = useCountUp<HTMLSpanElement>(stats?.funnel.enriched ?? DEMO_FN_ENRICH, { thin: true });
  const fnReadyRef = useCountUp<HTMLSpanElement>(stats?.funnel.qualified ?? DEMO_FN_READY, { thin: true });

  // Source-mix list (источники · 7 дней) + heatmap rows: derive from real
  // source counts → RU labels with % share; fall back to the original rows.
  const srcTotal = stats?.sources.reduce((a, s) => a + s.count, 0) ?? 0;
  const sourceRows =
    stats && srcTotal > 0
      ? stats.sources.map((s) => ({
          name: sourceLabel(s.source),
          pct: Math.round((s.count / srcTotal) * 100),
          num: thinFmt(s.count),
        }))
      : null;

  // Heatmap rows: the per-hour curve shape is decorative (no real per-hour
  // data), so we keep the shapes but relabel the rows with real source names
  // when available. Fall back to the original HEATMAP_SOURCES labels.
  const heatmapRows: typeof HEATMAP_SOURCES =
    stats && stats.sources.length > 0
      ? HEATMAP_SOURCES.map((row, i) => ({
          name: stats.sources[i] ? sourceLabel(stats.sources[i].source) : row.name,
          curve: row.curve,
        }))
      : HEATMAP_SOURCES;

  // Pulse stream: ts/tag/num are decorative telemetry; the real part is the
  // company + city · source. Overlay real samples onto the existing rows
  // (preserving count) so the scroller looks identical but names are real.
  const pulseRows =
    stats && stats.samples.length > 0
      ? PULSE_FEED.map((row, i) => {
          const s = stats.samples[i % stats.samples.length];
          return { ...row, co: s.company, meta: `${s.city} · ${sourceLabel(s.source)}` };
        })
      : PULSE_FEED;

  return (
    <section id={panelId} role="tabpanel" aria-labelledby={tabId} className={"view" + (active ? " active" : "")}>
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
            <div key={i} className="stat-tile elev-1">
              <div className="stat-tile__label">{label as string}</div>
              <div className="stat-tile__value tnum">
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
              {[...pulseRows, ...pulseRows].map((row, i) => (
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
            {heatmapRows.map((s) => (
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
            {(sourceRows ?? DEMO_SOURCE_ROWS).map((r, i) => (
              <SourceRow
                key={r.name}
                name={r.name}
                pct={r.pct}
                num={r.num}
                path={SRC_SPARK_PATHS[i % SRC_SPARK_PATHS.length]}
              />
            ))}
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
        // Deterministic jitter seeded by (i, v) so SSR and client compute the
        // SAME value — kills the hydration mismatch + repaint flicker that
        // Math.random() caused on every re-render.
        const seed = Math.sin((i + 1) * 12.9898 + v * 78.233) * 43758.5453;
        const rnd = seed - Math.floor(seed);
        const a = Math.max(0.04, Math.min(0.92, v + (rnd - 0.5) * 0.08)).toFixed(3);
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

function ViewProject({ active, tabId, panelId }: { active: boolean; tabId?: string; panelId?: string }) {
  const stats = useStats();
  // Real project totals when loaded, else original hardcoded demo values.
  const collectedRef = useCountUp<HTMLSpanElement>(stats?.funnel.added ?? 134);
  const emailedRef = useCountUp<HTMLSpanElement>(stats?.totals.with_email ?? 71);
  const qualRef = useCountUp<HTMLSpanElement>(stats?.totals.qualified ?? 17);

  // Leads table: render from real samples (company/city/score/source) with
  // contacts masked to ✓/— badges — never invent emails/phones. Falls back
  // to the original 6 demo rows. Keep the existing "демо-данные" label.
  const tableRows: TableRow[] | null =
    stats && stats.samples.length > 0
      ? stats.samples.slice(0, 6).map((s) => {
          const badge = sourceBadge(s.source);
          return {
            src: badge.src,
            color: badge.color,
            co: s.company,
            city: s.city,
            score: s.score,
            hasEmail: s.has_email,
            hasPhone: s.has_phone,
          };
        })
      : null;
  const tableTotal = stats?.funnel.added ?? 134;

  return (
    <section id={panelId} role="tabpanel" aria-labelledby={tabId} className={"view" + (active ? " active" : "")}>
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
            <div key={i} className="stat-tile elev-1">
              <div className="stat-tile__label">{label as string}</div>
              <div className="stat-tile__value tnum">
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
            <div className="flex items-center gap-2 text-[12px]">
              <span className="text-white">Лиды</span>
              <span className="t-40 ml-1 mono">{tableTotal}</span>
              <span className="panel-thin px-2 py-0.5 text-[9px] mono t-40">демо-данные</span>
            </div>
            <div className="seg" style={{ padding: 2 }}>
              <button className="seg-btn active" style={{ padding: "4px 10px", fontSize: 11 }}>Все</button>
              <button className="seg-btn" style={{ padding: "4px 10px", fontSize: 11 }}>Q · {stats?.totals.qualified ?? 17}</button>
            </div>
          </div>
          <table className="lt">
            <thead>
              <tr><th>Компания</th><th>Город</th><th className="text-right">Score</th></tr>
            </thead>
            <tbody>
              {(tableRows ?? DEMO_TABLE_ROWS).map((row, i) => (
                <tr key={i}>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="mono text-[10px]" style={{ color: row.color }}>{row.src}</span>
                      <span style={{ fontWeight: i === 0 ? 500 : 400 }}>{row.co}</span>
                    </div>
                    {"inn" in row && row.inn ? (
                      <div className="t-40 mono text-[10px] mt-0.5">{row.inn}</div>
                    ) : (
                      <div className="t-40 mono text-[10px] mt-0.5">
                        email {"hasEmail" in row && row.hasEmail ? "✓" : "—"} · тел {"hasPhone" in row && row.hasPhone ? "✓" : "—"}
                      </div>
                    )}
                  </td>
                  <td className="t-72">{row.city}</td>
                  <td className="text-right">
                    <div className="flex items-center gap-2 justify-end">
                      <div className="score-bar score-bar--sm" style={{ "--score": row.score / 100 } as React.CSSProperties}>
                        <div className="score-bar__fill" />
                      </div>
                      <span className="mono">{row.score}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-5 py-3 hairline flex items-center text-[11px]">
            <span className="t-40">показано {(tableRows ?? DEMO_TABLE_ROWS).length} из {tableTotal}</span>
            <Link href="/register" className="ml-auto text-white flex items-center gap-1.5 hover:opacity-80 transition-opacity">
              смотреть все
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

function BubbleChart() {
  const stats = useStats();
  // Build the scatter dataset. Real path: by_city → X=средний score,
  // Y=лидов, bubble size=объём (count). The fabricated "выручка" axis is
  // dropped entirely. Fallback path: the original BUBBLE_DATA (revenue X,
  // qualified-sized bubbles) so the chart is byte-identical with no data.
  const real = Boolean(stats && stats.by_city.length > 0);
  const points: Array<{ short: string; x: number; y: number; size: number; primary?: boolean }> =
    real && stats
      ? (() => {
          const top = Math.max(...stats.by_city.map((c) => c.count));
          return stats.by_city.map((c) => ({
            short: c.city,
            x: c.avg_score,
            y: c.count,
            size: c.count,
            primary: c.count === top,
          }));
        })()
      : BUBBLE_DATA.map((d) => ({ short: d.short, x: d.rev, y: d.leads, size: d.qual, primary: d.primary }));

  const VW = 760, VH = 360;
  const ML = 64, MR = 24, MT = 24, MB = 44;
  const W = VW - ML - MR;
  const H = VH - MT - MB;
  // Axis domains: real data derives padded score/volume ranges; fallback
  // keeps the exact original constants so geometry is unchanged.
  const niceCeil = (v: number) => Math.max(5, Math.ceil(v / 5) * 5);
  const xMin = real ? 0 : 30;
  const xMax = real ? 100 : 200;
  const yMin = 0;
  const yMax = real ? niceCeil(Math.max(...points.map((p) => p.y)) * 1.15) : 55;
  const rMin = 6, rMax = 32;
  const sizeMax = Math.max(...points.map((p) => p.size));
  const X = (v: number) => ML + ((v - xMin) / (xMax - xMin)) * W;
  const Y = (v: number) => MT + H - ((v - yMin) / (yMax - yMin)) * H;
  const R = (q: number) => rMin + (Math.sqrt(q) / Math.sqrt(sizeMax || 1)) * (rMax - rMin);

  const xTicks = real ? [20, 40, 60, 80, 100] : [40, 80, 120, 160, 200];
  const yTicks = real
    ? Array.from({ length: 5 }, (_, i) => Math.round(((i + 1) / 5) * yMax))
    : [10, 20, 30, 40, 50];

  // medians
  const medX = [...points].map((d) => d.x).sort((a, b) => a - b)[Math.floor(points.length / 2)];
  const medY = [...points].map((d) => d.y).sort((a, b) => a - b)[Math.floor(points.length / 2)];

  // Subtitle / axis copy — honest sums from real data, else original demo text.
  const regionCount = real && stats ? stats.by_city.length : 9;
  const totalLeads = real && stats ? stats.totals.leads : 134;

  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduceMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setReduceMotion(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return (
    <div className={"bubble-wrap" + (hoverIdx !== null ? " has-hover" : "")}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="eyebrow">регионы · сводка</div>
          <div className="text-[15px] light mt-1">{real ? "Лиды по score и объёму" : "Лиды по выручке и объёму"}</div>
        </div>
        <div className="t-40 mono text-[10px] text-right">
          {regionCount} регионов
          <br />
          {totalLeads} лида
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
            <text key={`xl${t}`} x={X(t)} y={VH - MB + 18} textAnchor="middle">{real ? t : `${t}M`}</text>
          ))}
          <text x={ML} y={MT - 8} fill="rgba(255,255,255,0.55)" fontSize="10.5">лиды собрано</text>
          <text x={VW - MR} y={VH - 12} textAnchor="end" fill="rgba(255,255,255,0.55)" fontSize="10.5">{real ? "средний score →" : "медианная выручка, ₽M →"}</text>
        </g>

        {/* medians */}
        <g>
          <line x1={X(medX)} y1={MT} x2={X(medX)} y2={MT + H} stroke="rgba(168,197,192,0.18)" strokeWidth="0.6" strokeDasharray="2,3" />
          <line x1={ML} y1={Y(medY)} x2={VW - MR} y2={Y(medY)} stroke="rgba(168,197,192,0.18)" strokeWidth="0.6" strokeDasharray="2,3" />
          <text x={VW - MR - 4} y={Y(medY) - 4} textAnchor="end" fontFamily="Geist Mono" fontSize="8.5" fill="rgba(168,197,192,0.45)">медиана</text>
        </g>

        {/* bubbles */}
        <g>
          {points.map((d, i) => {
            const cx = X(d.x), cy = Y(d.y), r = R(d.size);
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
                      {!reduceMotion && <animate attributeName="r" values={`${r + 2};${r + 12};${r + 2}`} dur="2.8s" repeatCount="indefinite" />}
                      {!reduceMotion && <animate attributeName="stroke-opacity" values="0.5;0;0.5" dur="2.8s" repeatCount="indefinite" />}
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
                  {real ? `${d.y} лид · score ${Math.round(d.x)}` : `${d.y} лид · ${d.size} qual`}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="bubble-legend mt-3 flex items-center gap-5 text-[11px] t-48 flex-wrap">
        <span className="flex items-center gap-2">
          <span className="bub-dot" style={{ width: 6, height: 6 }} />
          {real ? "меньше лидов" : "< 30 qual."}
        </span>
        <span className="flex items-center gap-2">
          <span className="bub-dot" style={{ width: 10, height: 10 }} />
          {real ? "средне" : "30–60 qual."}
        </span>
        <span className="flex items-center gap-2">
          <span className="bub-dot" style={{ width: 15, height: 15 }} />
          {real ? "больше лидов" : "60+ qual."}
        </span>
        <span className="ml-auto mono">{real ? "размер · объём" : "размер · qualified"}</span>
      </div>
    </div>
  );
}

/* ── View: Lead ──────────────────────────────────────── */

function ViewLead({ active, tabId, panelId }: { active: boolean; tabId?: string; panelId?: string }) {
  const stats = useStats();
  // Drive the lead card from the top real sample when available. Identity +
  // score are real; sub-scores, ЛПР, address, timeline & notes have no
  // endpoint source and stay as labelled demo data. Contacts are masked to
  // ✓/— from has_email/has_phone — never synthesised into fake addresses.
  const lead = stats?.samples[0];
  const leadCo = lead?.company ?? "Птицефабрика «Юг»";
  const leadCity = lead?.city ?? "Томск";
  const leadScore = lead?.score ?? 92;
  const leadSrc = lead ? sourceLabel(lead.source) : "2GIS+ЕГРЮЛ";
  const scoreRef = useCountUp<HTMLSpanElement>(leadScore);
  return (
    <section id={panelId} role="tabpanel" aria-labelledby={tabId} className={"view" + (active ? " active" : "")}>
      <div className="flex items-end justify-between mb-6 flex-wrap gap-6">
        <div>
          <div className="eyebrow">лид · {leadSrc}</div>
          <div className="h1 mt-2" style={{ fontSize: 56 }}>{leadCo}</div>
          <div className="text-[13px] t-72 mt-1">
            {lead ? leadCo : "ООО «Птицефабрика Юг»"} <span className="t-28">·</span>{" "}
            <span className="mono">{lead ? `источник ${leadSrc}` : "ИНН 7017234567"}</span> <span className="t-28">·</span> {leadCity}
            {" "}<span className="panel-thin px-2 py-0.5 text-[10px] mono align-middle ml-1">демо-данные</span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-none">
          <button
            className="ghost rounded-full px-3.5 py-2 text-[12.5px] opacity-50 cursor-not-allowed"
            disabled
            title="доступно в приложении"
            style={{ pointerEvents: "none" }}
          >
            В кампанию
          </button>
          <button
            className="brand rounded-full px-4 py-2 text-[12.5px] opacity-50 cursor-not-allowed"
            disabled
            title="доступно в приложении"
            style={{ pointerEvents: "none" }}
          >
            Связаться
          </button>
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
              style={{ width: `${leadScore}%`, background: "var(--mint)", boxShadow: "0 0 12px rgba(168,197,192,0.45)" }}
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
              <span className="mono">{lead ? (lead.has_email ? "email найден" : "email не найден") : "info@ptf-yug.ru"}</span>
              <span className="ml-auto t-40 text-[10px]">{lead ? (lead.email_valid ? "SMTP+MX ✓" : lead.has_email ? "не проверен" : "—") : "SMTP+MX ✓"}</span>
            </div>
            <div className="flex items-center gap-3">
              <svg className="t-48" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" />
              </svg>
              <span className="mono">{lead ? (lead.has_phone ? "телефон найден" : "телефон не найден") : "+7 382 245-18-90"}</span>
              <span className="ml-auto t-40 text-[10px]">{lead ? (lead.has_phone ? "✓" : "—") : "основной"}</span>
            </div>
            <div className="flex items-center gap-3">
              <svg className="t-48" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="12" r="9" />
                <path d="M3 12h18M12 3a13 13 0 010 18 13 13 0 010-18z" />
              </svg>
              <span className="mono">{lead ? "сайт — демо" : "ptf-yug.ru"}</span>
              <span className="ml-auto t-40 text-[10px]">{lead ? "демо-данные" : "site online"}</span>
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
              ["14:23", <>обогащён <span className="t-48">· score {leadScore}</span></>],
              ["14:21", "подтверждён email · SMTP 220"],
              ["14:19", <>сматчен с ЕГРЮЛ <span className="mono t-40">7017234567</span></>],
              ["14:18", <>попал в очередь <span className="t-48">· источник: {leadSrc}</span></>],
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
  const stats = useStats();
  // Real rates for the KPI tiles; deliver→email, контактность(ЛПР)→phone,
  // совпадение→enrichment. Fall back to the original demo percentages.
  const deliverPct = stats ? Math.round(stats.rates.email * 100) : 94;
  const matchPct = stats ? Math.round(stats.rates.enrichment * 100) : 88;
  const lprPct = stats ? Math.round(stats.rates.phone * 100) : 71;
  const avgScore = stats ? Math.round(stats.avg_score) : 72;
  return (
    <section id="sources" className="relative">
      <div className="max-w-[1320px] mx-auto px-6 py-24">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 mb-14">
          <div className="col-span-1 lg:col-span-6">
            <div className="eyebrow mb-3">шаг 03 · что внутри</div>
            <h2 className="h2" style={{ fontSize: "clamp(28px,4.4vw,64px)" }}>
              Не каталог компаний.
              <br />
              Машина по производству лидов.
            </h2>
          </div>
          <div className="col-span-1 lg:col-span-6 lg:pt-10 text-[15px] t-72 light leading-[1.55]">
            База подключена к 8 верифицированным источникам, обновляется ежедневно и работает
            как единая поверхность. Никаких CSV из неизвестных папок.
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-12 gap-5">
          <div className="col-span-1 md:col-span-4 panel-flat elev-1 p-6 transition-shadow duration-200 hover:shadow-elev-2">
            <div className="flex items-center justify-between"><div className="eyebrow">обогащение</div><span className="mono t-40 text-[10px]">01</span></div>
            <h3 className="h3 mt-3" style={{ fontSize: 24 }}>Email, телефон, ЛПР, выручка — для каждой компании.</h3>
            <p className="t-72 text-[13px] mt-3 leading-[1.55]">SMTP+MX-проверка, валидация по ФНС, сопоставление ЛПР с открытыми профилями.</p>
            <div className="mt-5 hairline pt-4 grid grid-cols-3 gap-2">
              {[
                ["deliver", `${deliverPct}%`],
                ["match", `${matchPct}%`],
                ["ЛПР", `${lprPct}%`],
              ].map(([label, val]) => (
                <div key={label} className="stat-tile" style={{ padding: "8px 10px" }}>
                  <div className="stat-tile__label">{label}</div>
                  <div className="stat-tile__value tnum" style={{ fontSize: 16 }}>{val}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="col-span-1 md:col-span-4 panel-flat elev-1 p-6 transition-shadow duration-200 hover:shadow-elev-2">
            <div className="flex items-center justify-between"><div className="eyebrow">scoring</div><span className="mono t-40 text-[10px]">02</span></div>
            <h3 className="h3 mt-3" style={{ fontSize: 24 }}>100-балльный скоринг под ваш промпт.</h3>
            <p className="t-72 text-[13px] mt-3 leading-[1.55]">Соответствие, контактность, платёжеспособность — три оси, прозрачные веса, объяснение для каждого балла.</p>
            <div className="mt-5 hairline pt-4">
              <div className="flex items-center justify-between text-[11px] t-48 mb-2"><span>средний</span><span className="mono">{avgScore} / 100</span></div>
              <div className="score-bar" style={{ "--score": avgScore / 100 } as React.CSSProperties}>
                <div className="score-bar__fill" />
              </div>
            </div>
          </div>
          <div className="col-span-1 md:col-span-4 panel-flat elev-1 p-6 transition-shadow duration-200 hover:shadow-elev-2">
            <div className="flex items-center justify-between"><div className="eyebrow">экспорт</div><span className="mono t-40 text-[10px]">03</span></div>
            <h3 className="h3 mt-3" style={{ fontSize: 24 }}>CSV, API, webhook прямо в CRM.</h3>
            <p className="t-72 text-[13px] mt-3 leading-[1.55]">Bitrix24, amoCRM, Pipedrive — нативные коннекторы. По API — 50 запросов в секунду.</p>
            <div className="mt-5 hairline pt-4 flex flex-wrap gap-2 text-[11px]">
              {["Bitrix24", "amoCRM", "Pipedrive", "webhook"].map((c) => (
                <span key={c} className="badge badge--source">{c}</span>
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
        <div className="panel elev-3 p-10 lg:p-14 text-center">
          <div className="eyebrow mb-5">раннее открытие</div>
          <h2 className="h2 max-w-[820px] mx-auto" style={{ fontSize: "clamp(30px,4.8vw,72px)" }}>
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
            <a href="mailto:support@usebaza.ru" className="ghost rounded-full px-6 py-3 text-[14px] cursor-pointer">Связаться с командой</a>
          </div>
        </div>
      </div>
    </section>
  );
}

function FooterSection() {
  return (
    <footer className="hairline">
      <div className="max-w-[1320px] mx-auto px-6 py-10 grid grid-cols-2 md:grid-cols-12 gap-8 t-48 text-[12px]">
        <div className="col-span-2 md:col-span-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-6 h-6 rounded-md" style={{ background: "linear-gradient(135deg,#A8C5C0,#8AA0B5)" }} />
            <span className="text-white text-[14px]" style={{ fontWeight: 500 }}>база</span>
          </div>
          <p className="leading-[1.55] max-w-[260px]">
            Лид-инжиниринг для команд продаж. Промпт → готовая воронка.
          </p>
        </div>
        {[
          { title: "Продукт", items: [
            { label: "Возможности", href: "#product" },
            { label: "Источники", href: "#sources" },
            { label: "Цены", href: "/plans" },
          ] },
          { title: "Документы", items: [
            { label: "Политика конфиденциальности", href: "/privacy" },
            { label: "Оферта", href: "/terms" },
          ] },
          { title: "Контакты", items: [
            { label: "support@usebaza.ru", href: "mailto:support@usebaza.ru" },
          ] },
        ].map((g) => (
          <div key={g.title} className="col-span-1 md:col-span-2">
            <div className="text-white mb-3 text-[12px]">{g.title}</div>
            <div className="space-y-2">
              {g.items.map((i) => (
                <div key={i.label}>
                  <a href={i.href} className="transition-colors hover:text-white">{i.label}</a>
                </div>
              ))}
            </div>
          </div>
        ))}
        <div className="col-span-1 md:col-span-2 md:text-right">
          <div className="text-white mb-3 text-[12px]">Статус</div>
          <div className="flex md:justify-end items-center gap-2">
            <span className="dot dot-em" />
            <span>Работает</span>
          </div>
        </div>
      </div>
      <div className="hairline">
        <div className="max-w-[1320px] mx-auto px-6 py-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 t-40 text-[11px]">
          <div>© 2026 База · usebaza.ru</div>
          <div className="mono">LTR</div>
        </div>
      </div>
    </footer>
  );
}

/* ── Marquee band ───────────────────────────────────────────────────
   Goonies-style running text — pure CSS keyframe (defined in globals.css
   under .marquee). Track is duplicated so the loop is seamless. */
function MarqueeBand() {
  const tokens = [
    "лидогенерация без перекупщиков",
    "ЕГРЮЛ · СПАРК · 2ГИС · Yandex Maps · SearXNG",
    "обогащение в фоне",
    "AI-фильтр покупателей",
    "интеграция Bitrix24 · AmoCRM",
    "хранение данных в РФ",
    "оплата в копейках",
    "от 2 ₽ за обогащённый контакт",
  ];
  // Duplicate the tokens so the -50% translate at the end of the loop
  // lands on a visually identical frame — seam disappears.
  const loop = [...tokens, ...tokens];
  return (
    <div className="marquee" aria-hidden>
      <div className="marquee-track">
        {loop.map((t, i) => (
          <span key={`${t}-${i}`} className="marquee-token">
            <span className={i % 2 === 0 ? "dot dot-mt" : "dot dot-em"} />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ── Page wrapper ──────────────────────────────────── */

export function LandingPage() {
  useCursorSpotlight();
  // Single fetch of /public/landing on mount; shared with every demo block
  // via context. Null until data arrives → blocks keep their hardcoded
  // fallbacks, so first paint is unchanged (no loading flash / layout shift).
  const stats = useLandingStats();
  return (
    <StatsContext.Provider value={stats}>
    <div className="min-h-screen bg-[var(--bg)] text-white">
      <CornerMeta />
      <TopNav />
      <HeroSection />
      <MarqueeBand />
      {/* Each major section gets a fade-up + blur-clear entry as it scrolls
          into view. PromptDemo uses scale so the typed-prompt feels like
          it's stepping forward, the rest use the default `up` variant. */}
      <Reveal variant="scale">
        <PromptDemo />
      </Reveal>
      <Reveal>
        <ProductFrame />
      </Reveal>
      <Reveal>
        <FeaturesSection />
      </Reveal>
      <Reveal>
        <CtaSection />
      </Reveal>
      <FooterSection />
    </div>
    </StatsContext.Provider>
  );
}

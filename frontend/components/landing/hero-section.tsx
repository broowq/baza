"use client";

import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";
import { motion } from "framer-motion";

import { Button } from "@/components/ui/button";

/**
 * Hero — full-bleed cinematic glass hero.
 * See /DESIGN.md §5 (hero layout) and §1 (atmosphere).
 *
 * Headline copy from /search_tuning/new_landing_copy.md.
 */
export function HeroSection() {
  return (
    <section className="relative isolate overflow-hidden px-4 pb-24 pt-32 sm:px-6 md:pb-32 md:pt-40">
      {/* Aurora backdrop — drifting blobs behind glass */}
      <div className="aurora-bg pointer-events-none absolute inset-0 -z-10" aria-hidden />

      {/* Subtle dot grid overlay (very faint) */}
      <div
        className="pointer-events-none absolute inset-0 -z-10 opacity-[0.4]"
        style={{
          backgroundImage:
            "radial-gradient(rgba(255,255,255,0.06) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
          maskImage: "radial-gradient(ellipse 60% 50% at 50% 30%, black 30%, transparent 90%)",
          WebkitMaskImage: "radial-gradient(ellipse 60% 50% at 50% 30%, black 30%, transparent 90%)",
        }}
      />

      <div className="relative mx-auto max-w-5xl text-center">
        {/* Eyebrow pill */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <span className="inline-flex items-center gap-2 rounded-full border border-white/[0.12] bg-white/[0.05] px-4 py-1.5 text-xs font-medium text-white/[0.72] backdrop-blur-xl">
            <Sparkles size={12} className="text-brand" />
            ИИ-поиск B2B-клиентов
          </span>
        </motion.div>

        {/* Headline */}
        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mt-8 text-4xl font-light leading-[1.05] tracking-tight text-white sm:text-5xl md:text-6xl lg:text-7xl"
        >
          Найди{" "}
          <span className="font-extralight italic text-white/[0.85]">100&nbsp;клиентов</span>
          <br />
          за минуту — по одному промпту
        </motion.h1>

        {/* Subheadline */}
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-white/[0.64] sm:text-lg"
        >
          Опиши свой бизнес одной фразой — ИИ соберёт базу компаний с проверенными
          email, телефонами и данными ФНС. Без фильтров по ОКВЭД и часов в Excel.
        </motion.p>

        {/* CTAs */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row"
        >
          <Link href="/register">
            <Button variant="brand" size="lg" className="px-7">
              Попробовать бесплатно
              <ArrowRight size={16} />
            </Button>
          </Link>
          <Link href="#how-it-works">
            <Button variant="secondary" size="lg" className="px-7">
              Как это работает
            </Button>
          </Link>
        </motion.div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.5 }}
          className="mt-5 text-xs text-white/[0.44]"
        >
          10 бесплатных лидов · без кредитной карты · ~60 секунд до результата
        </motion.p>
      </div>

      {/* Floating mock leads — three glass cards demonstrating the product */}
      <motion.div
        initial={{ opacity: 0, y: 32 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.6 }}
        className="relative mx-auto mt-20 hidden max-w-5xl md:block"
      >
        <div className="grid grid-cols-3 gap-4">
          <MockLeadCard
            company="Птицефабрика «Юг»"
            city="Томск"
            score={92}
            email="info@ptitsa-yug.ru"
            tilt="-rotate-1"
            source="2GIS"
          />
          <MockLeadCard
            company="Агрохолдинг СТЕПЬ"
            city="Ростов-на-Дону"
            score={87}
            email="office@ahstep.ru"
            tilt=""
            source="ЕГРЮЛ"
          />
          <MockLeadCard
            company="Юрьевецкая п/ф"
            city="Иваново"
            score={78}
            email="sales@upf33.ru"
            tilt="rotate-1"
            source="Я.Карты"
          />
        </div>
      </motion.div>
    </section>
  );
}

function MockLeadCard({
  company,
  city,
  score,
  email,
  tilt,
  source,
}: {
  company: string;
  city: string;
  score: number;
  email: string;
  tilt: string;
  source: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-white/[0.10] bg-white/[0.04] p-5 backdrop-blur-2xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)] transform-gpu ${tilt}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-wider text-white/[0.40]">
            {source}
          </div>
          <div className="mt-1.5 truncate text-sm font-medium text-white">
            {company}
          </div>
          <div className="mt-0.5 text-xs text-white/[0.52]">{city}</div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] uppercase tracking-wider text-white/[0.40]">Score</div>
          <div className="mt-0.5 text-2xl font-extralight text-white">{score}</div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-1.5 text-xs">
        <span className="size-1.5 shrink-0 rounded-full bg-status-online shadow-[0_0_6px_rgba(52,211,153,0.7)]" />
        <span className="truncate text-white/[0.72]">{email}</span>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { ArrowRight, ChevronRight, Sparkles, Check } from "lucide-react";
import { motion } from "framer-motion";

import { Button } from "@/components/ui/button";
import { SmartCTA } from "@/components/landing/smart-cta";

export function HeroSection() {
  return (
    <section className="relative overflow-hidden px-4 pb-20 pt-24 sm:px-6 md:pb-28 md:pt-32">
      {/* ── Grid background pattern ── */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(to right, rgba(128,128,128,0.08) 1px, transparent 1px), linear-gradient(to bottom, rgba(128,128,128,0.08) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          maskImage:
            "radial-gradient(ellipse 60% 50% at 50% 0%, black 30%, transparent 100%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 60% 50% at 50% 0%, black 30%, transparent 100%)",
        }}
      />

      <div className="relative mx-auto max-w-6xl">
        <div className="text-center">
          {/* Eyebrow badge */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0 }}
          >
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white/80 px-4 py-1.5 text-sm font-medium text-[#191C1F] backdrop-blur-sm dark:border-[#2A2C2F] dark:bg-[#1A1C1F]/80 dark:text-gray-300">
              <Sparkles size={14} className="text-amber-500" />
              Новая версия
              <ChevronRight size={14} className="text-gray-400" />
            </div>
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-5xl font-bold leading-[1.05] tracking-tight sm:text-6xl md:text-7xl lg:text-8xl"
          >
            <span className="bg-gradient-to-br from-black from-30% to-black/40 bg-clip-text text-transparent dark:from-white dark:from-30% dark:to-white/40">
              Находите клиентов
            </span>
            <br />
            <span className="bg-gradient-to-br from-black from-30% to-black/40 bg-clip-text text-transparent dark:from-white dark:from-30% dark:to-white/40">
              быстрее с помощью ИИ
            </span>
          </motion.h1>

          {/* Subtitle */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground"
          >
            Автоматический сбор и обогащение B2B лидов из 5+ источников.
            <br className="hidden sm:block" />
            Экономьте часы ручной работы.
          </motion.p>

          {/* CTAs */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="mt-10 flex flex-wrap items-center justify-center gap-4"
          >
            <SmartCTA />
            <Link href="#pricing">
              <Button
                variant="secondary"
                size="lg"
                className="h-12 rounded-full border-none bg-[#F7F7F8] px-8 text-base font-semibold text-[#191C1F] shadow-none hover:bg-[#EDEDF0] dark:bg-[#1A1C1F] dark:text-white dark:hover:bg-[#242628]"
              >
                Посмотреть тарифы
              </Button>
            </Link>
          </motion.div>

          {/* Trust line */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.5 }}
            className="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-gray-400 dark:text-gray-500"
          >
            <span className="inline-flex items-center gap-1.5">
              <Check size={14} className="text-emerald-500" />
              Бесплатно
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Check size={14} className="text-emerald-500" />
              Без карты
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Check size={14} className="text-emerald-500" />
              Self-hosted
            </span>
          </motion.div>
        </div>

        {/* ── Dashboard Mockup ── */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          className="mx-auto mt-16 max-w-5xl"
        >
          <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-xl dark:border-[#2A2C2F] dark:bg-[#1A1C1F]">
            {/* Window chrome */}
            <div className="flex items-center gap-2 border-b border-gray-100 px-5 py-3 dark:border-[#2A2C2F]">
              <div className="flex gap-2">
                <div className="h-3 w-3 rounded-full bg-[#ff5f57]" />
                <div className="h-3 w-3 rounded-full bg-[#febc2e]" />
                <div className="h-3 w-3 rounded-full bg-[#28c840]" />
              </div>
              <div className="ml-4 flex-1 rounded-lg bg-[#F7F7F8] px-4 py-1.5 font-mono text-xs text-gray-400 dark:bg-[#111214] dark:text-gray-500">
                app.baza.io/dashboard
              </div>
            </div>

            {/* Dashboard content */}
            <div className="p-6 md:p-8">
              {/* Stat cards */}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {[
                  { label: "Всего лидов", value: "2,847", trend: "+12%" },
                  { label: "Обогащено", value: "1,923", trend: "+8%" },
                  { label: "С email", value: "1,456", trend: "+15%" },
                  { label: "Средний score", value: "72", trend: "+3" },
                ].map((s) => (
                  <div
                    key={s.label}
                    className="rounded-xl border border-gray-100 bg-[#F7F7F8] p-4 dark:border-[#2A2C2F] dark:bg-[#111214]"
                  >
                    <p className="text-[11px] text-gray-400 dark:text-gray-500">
                      {s.label}
                    </p>
                    <div className="mt-1.5 flex items-baseline gap-2">
                      <p className="text-xl font-bold text-[#191C1F] dark:text-white">
                        {s.value}
                      </p>
                      <span className="text-[10px] font-medium text-emerald-500">
                        {s.trend}
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Table */}
              <div className="mt-5 overflow-hidden rounded-xl border border-gray-100 dark:border-[#2A2C2F]">
                <div className="grid grid-cols-5 gap-2 bg-[#F7F7F8] px-5 py-2.5 text-[11px] font-medium text-gray-400 dark:bg-[#111214] dark:text-gray-500">
                  <span>Компания</span>
                  <span>Город</span>
                  <span>Email</span>
                  <span>Телефон</span>
                  <span className="text-right">Score</span>
                </div>
                {[
                  { c: "ТехноПром", city: "Москва", email: "info@technoprom.ru", phone: "+7 495 123-45-67", score: 92 },
                  { c: "СтройМастер", city: "СПб", email: "sale@stroymaster.ru", phone: "+7 812 987-65-43", score: 87 },
                  { c: "АгроТрейд", city: "Казань", email: "opt@agrotrade.ru", phone: "+7 843 555-12-34", score: 76 },
                  { c: "МеталлПроф", city: "Екб", email: "info@metallprof.ru", phone: "+7 343 222-33-44", score: 71 },
                  { c: "ФудСервис", city: "Нск", email: "zakaz@foodserv.ru", phone: "+7 383 111-22-33", score: 68 },
                ].map((r) => (
                  <div
                    key={r.c}
                    className="grid grid-cols-5 items-center gap-2 border-t border-gray-50 px-5 py-3 text-[12px] dark:border-[#1A1C1F]"
                  >
                    <span className="font-medium text-[#191C1F] dark:text-white">
                      {r.c}
                    </span>
                    <span className="text-gray-400 dark:text-gray-500">
                      {r.city}
                    </span>
                    <span className="text-[#191C1F] dark:text-white">
                      {r.email}
                    </span>
                    <span className="font-mono text-gray-400 dark:text-gray-500">
                      {r.phone}
                    </span>
                    <span className="text-right">
                      <span
                        className={`inline-flex min-w-[2.5rem] justify-center rounded-md px-2 py-0.5 text-[11px] font-bold ${
                          r.score >= 85
                            ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400"
                            : r.score >= 75
                              ? "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400"
                              : "bg-gray-100 text-gray-500 dark:bg-gray-500/10 dark:text-gray-400"
                        }`}
                      >
                        {r.score}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

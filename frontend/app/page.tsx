import Link from "next/link";
import {
  ArrowRight,
  Check,
  Database,
  FileSpreadsheet,
  Globe,
  Mail,
  MapPin,
  Search,
  Sparkles,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { FaqAccordion } from "@/components/landing/faq-accordion";
import { HeroSection } from "@/components/landing/hero-section";
import { SmartCTA, SmartLink } from "@/components/landing/smart-cta";

/* ─────────────────────── Data ─────────────────────── */

const plans = [
  {
    name: "Starter",
    price: "Бесплатно",
    priceSub: "навсегда",
    highlight: false,
    cta: "Начать бесплатно",
    features: [
      "1 000 лидов/мес",
      "3 проекта",
      "1 пользователь",
      "Экспорт в CSV",
      "Скоринг лидов",
    ],
  },
  {
    name: "Pro",
    price: "2 900 ₽",
    priceSub: "/мес",
    highlight: true,
    cta: "Выбрать Pro",
    features: [
      "10 000 лидов/мес",
      "20 проектов",
      "5 пользователей",
      "Экспорт в CSV",
      "Скоринг лидов",
      "Обогащение контактов",
      "Приоритетная поддержка",
    ],
  },
  {
    name: "Team",
    price: "7 900 ₽",
    priceSub: "/мес",
    highlight: false,
    cta: "Выбрать Team",
    features: [
      "50 000 лидов/мес",
      "100 проектов",
      "20 пользователей",
      "Экспорт в CSV",
      "Скоринг лидов",
      "Обогащение контактов",
      "Выделенная поддержка",
      "SLA 99.9%",
    ],
  },
];

const steps = [
  {
    num: "01",
    title: "Настройте проект",
    desc: "Укажите нишу, географию и целевые сегменты",
    icon: Search,
  },
  {
    num: "02",
    title: "Запустите сбор",
    desc: "Выберите объём: 100, 500 или 1 000 лидов",
    icon: Zap,
  },
  {
    num: "03",
    title: "Обогатите данные",
    desc: "Email, телефон, адрес — автоматически",
    icon: Mail,
  },
  {
    num: "04",
    title: "Экспортируйте",
    desc: "CSV готов для загрузки в CRM",
    icon: Database,
  },
];

const faqs = [
  {
    q: "Как происходит сбор лидов?",
    a: "БАЗА использует 5 источников: Яндекс Карты, 2ГИС, SearXNG, Bing и maps-поиск. Фильтрует агрегаторы, нормализует домены. Для каждого домена сканирует контактные страницы.",
  },
  {
    q: "Нужен ли API-ключ Bing?",
    a: "Нет. Bing — опциональный источник. По умолчанию работает SearXNG + Яндекс Карты + 2ГИС. Bing подключается через .env.",
  },
  {
    q: "Где хранятся данные?",
    a: "В вашей PostgreSQL. Мы не передаём данные третьим лицам. Полный контроль.",
  },
  {
    q: "Можно ли деплоить на свой сервер?",
    a: "Да. Docker compose up и всё работает. Self-hosted, без зависимости от облака.",
  },
];

/* ─────────────────────── Page ─────────────────────── */

export default function HomePage() {
  return (
    <main className="min-h-screen bg-white text-[#191C1F] selection:bg-gray-200 dark:bg-[#111214] dark:text-white">

      {/* ==================== HERO ==================== */}
      <HeroSection />

      {/* ==================== STATS BAR ==================== */}
      <section className="bg-[#F7F7F8] px-4 py-16 sm:px-6 dark:bg-[#1A1C1F]">
        <div className="mx-auto grid max-w-4xl grid-cols-2 gap-4 md:grid-cols-3">
          {[
            { value: "50 000+", label: "лидов в месяц", icon: Globe },
            { value: "5 источников", label: "поиска", icon: Search },
            { value: "221 город", label: "России и СНГ", icon: MapPin },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-2xl bg-white p-6 text-center dark:bg-[#111214]"
            >
              <div className="mx-auto mb-3 inline-flex h-10 w-10 items-center justify-center rounded-full bg-[#F7F7F8] dark:bg-[#1A1C1F]">
                <s.icon size={18} className="text-gray-400" />
              </div>
              <p className="text-2xl font-bold text-[#191C1F] dark:text-white sm:text-3xl md:text-4xl">
                {s.value}
              </p>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ==================== FEATURES ==================== */}
      <section className="px-4 py-24 sm:px-6">
        <div className="mx-auto max-w-6xl">
          <div className="text-center">
            <p className="text-sm font-semibold uppercase tracking-widest text-gray-400">Возможности</p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-[#191C1F] dark:text-white sm:text-4xl md:text-5xl">
              Всё для{" "}
              <span className="text-[#191C1F] dark:text-white">
                лидогенерации
              </span>
            </h2>
            <p className="mt-4 text-base text-gray-500 dark:text-gray-400 sm:text-lg">от сбора до экспорта в CRM — в одном продукте</p>
          </div>

          {/* Bento grid */}
          <div className="mt-16 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {/* Large card 1 — Search */}
            <div className="col-span-1 rounded-3xl bg-[#F7F7F8] p-6 transition-shadow duration-300 hover:shadow-lg dark:bg-[#1A1C1F] sm:p-8 sm:col-span-2 lg:col-span-2">
              <div className="mb-5 inline-flex h-12 w-12 items-center justify-center rounded-full bg-white dark:bg-[#111214]">
                <Search size={22} className="text-gray-400" />
              </div>
              <h3 className="text-2xl font-semibold text-[#191C1F] dark:text-white">Умный поиск лидов</h3>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-gray-500 dark:text-gray-400">
                Яндекс Карты, 2ГИС, SearXNG и Bing — 5 источников одновременно. Фильтрация мусора, дедупликация, нормализация доменов.
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {["Яндекс Карты", "2ГИС", "SearXNG", "Bing", "Maps"].map((src) => (
                  <span
                    key={src}
                    className="rounded-full bg-white px-3 py-1.5 text-[11px] font-medium text-gray-500 dark:bg-[#111214] dark:text-gray-400"
                  >
                    {src}
                  </span>
                ))}
              </div>
            </div>

            {/* Large card 2 — Enrich */}
            <div className="col-span-1 rounded-3xl bg-[#F7F7F8] p-6 transition-shadow duration-300 hover:shadow-lg dark:bg-[#1A1C1F] sm:p-8 sm:col-span-2 lg:col-span-2">
              <div className="mb-5 inline-flex h-12 w-12 items-center justify-center rounded-full bg-white dark:bg-[#111214]">
                <Sparkles size={22} className="text-gray-400" />
              </div>
              <h3 className="text-2xl font-semibold text-[#191C1F] dark:text-white">Обогащение контактов</h3>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-gray-500 dark:text-gray-400">
                Email, телефон и адрес автоматически. JSON-LD и schema.org парсинг. До 8 страниц на сайт.
              </p>
              <div className="mt-5 flex flex-col gap-2">
                {[
                  { icon: Mail, label: "info@company.ru" },
                  { icon: MapPin, label: "ул. Ленина, 42" },
                  { icon: Globe, label: "company.ru" },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="flex items-center gap-2.5 rounded-xl bg-white px-3 py-2 text-[11px] dark:bg-[#111214]"
                  >
                    <item.icon size={12} className="text-gray-400" />
                    <span className="text-gray-500 dark:text-gray-400">{item.label}</span>
                    <Check size={12} className="ml-auto text-emerald-500" />
                  </div>
                ))}
              </div>
            </div>

            {/* Small cards */}
            {[
              {
                icon: TrendingUp,
                title: "Скоринг 0-100",
                desc: "Умная оценка каждого лида по контактам, нише и домену. Горячие лиды сверху.",
              },
              {
                icon: FileSpreadsheet,
                title: "Экспорт в CSV",
                desc: "Выгрузка с контактами, статусами и скором в один клик.",
              },
              {
                icon: Users,
                title: "Командная работа",
                desc: "Организации с ролями: Owner, Admin, Member. Инвайты по email.",
              },
              {
                icon: Zap,
                title: "Realtime задачи",
                desc: "Celery + SSE для живого статуса. Не нужно обновлять страницу.",
              },
            ].map((f) => (
              <div
                key={f.title}
                className="rounded-3xl bg-[#F7F7F8] p-8 transition-shadow duration-300 hover:shadow-lg dark:bg-[#1A1C1F]"
              >
                <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-full bg-white dark:bg-[#111214]">
                  <f.icon size={20} className="text-gray-400" />
                </div>
                <h3 className="text-xl font-semibold text-[#191C1F] dark:text-white">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-gray-500 dark:text-gray-400">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ==================== HOW IT WORKS ==================== */}
      <section className="bg-[#F7F7F8] px-4 py-24 sm:px-6 dark:bg-[#1A1C1F]">
        <div className="mx-auto max-w-5xl">
          <div className="text-center">
            <p className="text-sm font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">Процесс</p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-[#191C1F] dark:text-white sm:text-4xl md:text-5xl">
              Четыре{" "}
              <span className="text-[#191C1F] dark:text-white">
                простых шага
              </span>
            </h2>
            <p className="mt-4 text-base text-gray-500 dark:text-gray-400 sm:text-lg">от нуля до горячей базы</p>
          </div>

          <div className="relative mt-20">
            {/* Connecting line — desktop */}
            <div className="absolute left-0 right-0 top-10 hidden h-px bg-gray-200 dark:bg-[#2A2C2F] md:block" />

            <div className="grid grid-cols-1 gap-10 sm:grid-cols-2 md:grid-cols-4 md:gap-6">
              {steps.map((item) => (
                <div key={item.num} className="relative text-center">
                  {/* Step circle */}
                  <div className="relative mx-auto mb-6 flex h-20 w-20 items-center justify-center">
                    <div className="flex h-full w-full items-center justify-center rounded-2xl border border-gray-200 bg-white dark:border-[#2A2C2F] dark:bg-[#111214]">
                      <item.icon size={28} className="text-gray-400" />
                    </div>
                  </div>
                  <div className="mb-2 inline-flex rounded-full bg-gray-100 dark:bg-white/10 px-3 py-0.5 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                    Шаг {item.num}
                  </div>
                  <h3 className="mt-1 text-lg font-semibold text-[#191C1F] dark:text-white">{item.title}</h3>
                  <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">{item.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ==================== PRICING ==================== */}
      <section className="px-4 py-24 sm:px-6" id="pricing">
        <div className="mx-auto max-w-5xl">
          <div className="text-center">
            <p className="text-sm font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">Тарифы</p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-[#191C1F] dark:text-white sm:text-4xl md:text-5xl">
              Прозрачные{" "}
              <span className="text-[#191C1F] dark:text-white">
                цены
              </span>
            </h2>
            <p className="mt-4 text-base text-gray-500 dark:text-gray-400 sm:text-lg">платите только за то, что используете</p>
          </div>

          <div className="mt-16 grid grid-cols-1 items-start gap-5 md:grid-cols-3">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={`flex flex-col rounded-3xl p-8 ${
                  plan.highlight
                    ? "relative bg-[#191C1F] text-white dark:bg-white dark:text-[#191C1F] md:-my-4 md:py-12"
                    : "border border-gray-200 bg-white dark:border-[#2A2C2F] dark:bg-[#1A1C1F]"
                }`}
              >
                {/* Popular badge */}
                {plan.highlight && (
                  <span className="absolute -top-3.5 left-1/2 -translate-x-1/2 rounded-full bg-[#191C1F] px-5 py-1 text-xs font-bold text-white dark:bg-white dark:text-[#191C1F]">
                    Популярный
                  </span>
                )}

                <div className="mb-8">
                  <p className={`text-sm font-medium ${plan.highlight ? "text-gray-400 dark:text-gray-500" : "text-gray-500 dark:text-gray-400"}`}>
                    {plan.name}
                  </p>
                  <div className="mt-3 flex items-baseline gap-1">
                    <span className={`text-3xl font-bold sm:text-4xl md:text-5xl ${plan.highlight ? "text-white dark:text-[#191C1F]" : "text-[#191C1F] dark:text-white"}`}>
                      {plan.price}
                    </span>
                    <span className={`text-sm ${plan.highlight ? "text-gray-400 dark:text-gray-500" : "text-gray-500 dark:text-gray-400"}`}>
                      {plan.priceSub}
                    </span>
                  </div>
                </div>

                <ul className={`flex-1 space-y-3.5 text-sm ${plan.highlight ? "text-gray-300 dark:text-gray-600" : "text-gray-500 dark:text-gray-400"}`}>
                  {plan.features.map((item) => (
                    <li key={item} className="flex items-start gap-3">
                      <div className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                        plan.highlight ? "bg-white/10 dark:bg-[#191C1F]/10" : "bg-[#F7F7F8] dark:bg-[#111214]"
                      }`}>
                        <Check size={12} className={plan.highlight ? "text-gray-400" : "text-gray-400 dark:text-gray-500"} />
                      </div>
                      {item}
                    </li>
                  ))}
                </ul>

                <SmartLink className="mt-8 block">
                  <Button
                    className={`w-full rounded-full ${
                      plan.highlight
                        ? "bg-white text-[#191C1F] shadow-none hover:bg-gray-100 dark:bg-[#191C1F] dark:text-white dark:hover:bg-[#2C2F33]"
                        : "bg-[#F7F7F8] text-[#191C1F] shadow-none hover:bg-[#EDEDF0] dark:bg-[#111214] dark:text-white dark:hover:bg-[#1A1C1F]"
                    }`}
                  >
                    {plan.cta}
                    {plan.highlight && <ArrowRight className="ml-2" size={16} />}
                  </Button>
                </SmartLink>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ==================== FAQ ==================== */}
      <section className="bg-[#F7F7F8] px-4 py-24 sm:px-6 dark:bg-[#1A1C1F]">
        <div className="mx-auto max-w-3xl">
          <div className="text-center">
            <p className="text-sm font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">FAQ</p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-[#191C1F] dark:text-white sm:text-4xl md:text-5xl">
              Вопросы и ответы
            </h2>
          </div>
          <div className="mt-12">
            <FaqAccordion items={faqs} />
          </div>
        </div>
      </section>

      {/* ==================== FINAL CTA ==================== */}
      <section className="px-4 py-24 text-center sm:px-6">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-3xl font-bold tracking-tight text-[#191C1F] dark:text-white sm:text-4xl md:text-5xl lg:text-6xl">
            Готовы заполнить{" "}
            <span className="text-[#191C1F] dark:text-white">
              воронку?
            </span>
          </h2>
          <p className="mx-auto mt-6 max-w-lg text-base text-gray-500 dark:text-gray-400 sm:text-lg">
            Регистрация за 30 секунд. Без кредитной карты. Первые 1 000 лидов бесплатно.
          </p>
          <div className="mt-10">
            <SmartCTA />
          </div>
        </div>
      </section>

      {/* ==================== FOOTER ==================== */}
      <footer className="border-t border-gray-200 px-4 py-12 sm:px-6 dark:border-[#2A2C2F]">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-6 md:flex-row">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#191C1F] text-xs font-bold text-white dark:bg-white dark:text-[#191C1F]">
              Б
            </div>
            <span className="text-base font-semibold text-[#191C1F] dark:text-white">БАЗА</span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-4 text-sm text-gray-500 dark:text-gray-400 sm:gap-8">
            <Link href="/plans" className="transition-colors duration-200 hover:text-[#191C1F] dark:hover:text-white">
              Тарифы
            </Link>
            <Link href="/register" className="transition-colors duration-200 hover:text-[#191C1F] dark:hover:text-white">
              Регистрация
            </Link>
            <Link href="#" className="transition-colors duration-200 hover:text-[#191C1F] dark:hover:text-white">
              Документация
            </Link>
            <Link href="/privacy" className="transition-colors duration-200 hover:text-[#191C1F] dark:hover:text-white">
              Конфиденциальность
            </Link>
            <Link href="/terms" className="transition-colors duration-200 hover:text-[#191C1F] dark:hover:text-white">
              Условия
            </Link>
          </div>
          <p className="text-sm text-gray-400 dark:text-gray-500">&copy; 2026 БАЗА. Все права защищены.</p>
        </div>
      </footer>
    </main>
  );
}

import Link from "next/link";
import {
  ArrowRight,
  Brain,
  CheckCircle2,
  Database,
  FileSpreadsheet,
  Globe2,
  Mail,
  ShieldCheck,
  Sparkles,
  Target,
  Workflow,
  Zap,
} from "lucide-react";

import { HeroSection } from "@/components/landing/hero-section";
import { FaqAccordion } from "@/components/landing/faq-accordion";
import { Button } from "@/components/ui/button";

/* ─────────────────────── Data ─────────────────────── */

const stats = [
  { value: "850K+", label: "компаний в базе" },
  { value: "94%", label: "доставляемость email" },
  { value: "<60", label: "секунд до первого результата" },
  { value: "16", label: "источников данных" },
];

const steps = [
  {
    num: "01",
    title: "Опиши свой бизнес",
    desc: "Одна фраза — «Продаю кормовые добавки в Томске». ИИ сам поймёт, кто покупает.",
  },
  {
    num: "02",
    title: "ИИ найдёт твоих клиентов",
    desc: "Не конкурентов. Птицефабрики, фермы, агрохолдинги — те, кто реально закупает.",
  },
  {
    num: "03",
    title: "Получи готовую базу",
    desc: "Excel, CSV или прямая выгрузка в AmoCRM/Bitrix24. С email, телефонами, ОКВЭД и адресами.",
  },
];

const features = [
  {
    icon: Brain,
    title: "Промпт вместо фильтров",
    desc: "Никаких ОКВЭД-кодов и фильтров — пишешь как говоришь, ИИ строит стратегию поиска.",
  },
  {
    icon: ShieldCheck,
    title: "Верифицированные email",
    desc: "MX-проверка каждого адреса. Зелёный чек = письмо дойдёт. Красный — bounce.",
  },
  {
    icon: Database,
    title: "Данные ФНС + 2ГИС + Яндекс",
    desc: "16 источников одновременно: открытый ЕГРЮЛ, карты, веб-поиск. Без серых баз.",
  },
  {
    icon: Workflow,
    title: "Воркфлоу под B2B-продажи",
    desc: "Теги, заметки, напоминания, статусы. Не «выгрузил и забыл», а живая база.",
  },
  {
    icon: Zap,
    title: "Webhook в твою CRM",
    desc: "Каждый новый лид сразу в Bitrix24, AmoCRM или твою систему. Real-time.",
  },
  {
    icon: FileSpreadsheet,
    title: "Excel и CSV-экспорт",
    desc: "Гиперссылки на телефон, email, сайт. Откроется в Excel, Numbers, Google Sheets без танцев.",
  },
];

const plans: Array<{
  name: string;
  price: string;
  sub: string;
  highlight: boolean;
  cta: string;
  query?: { plan: string };
  features: string[];
}> = [
  {
    name: "Free",
    price: "0 ₽",
    sub: "/навсегда",
    highlight: false,
    cta: "Попробовать",
    features: [
      "10 лидов / месяц",
      "1 проект",
      "Базовое обогащение",
      "CSV-экспорт",
    ],
  },
  {
    name: "Starter",
    price: "1 490 ₽",
    sub: "/мес",
    highlight: false,
    cta: "Выбрать Starter",
    query: { plan: "starter" },
    features: [
      "100 лидов / месяц",
      "3 проекта",
      "MX-верификация email",
      "CSV + Excel",
      "Webhook в CRM",
    ],
  },
  {
    name: "Pro",
    price: "4 990 ₽",
    sub: "/мес",
    highlight: true,
    cta: "Выбрать Pro",
    query: { plan: "pro" },
    features: [
      "500 лидов / месяц",
      "10 проектов",
      "Полное обогащение",
      "Все источники + ЕГРЮЛ",
      "Командная работа (3)",
      "Приоритетная поддержка",
    ],
  },
  {
    name: "Team",
    price: "12 990 ₽",
    sub: "/мес",
    highlight: false,
    cta: "Выбрать Team",
    query: { plan: "team" },
    features: [
      "2 000 лидов / месяц",
      "Без лимита проектов",
      "Командная работа (10)",
      "White-label экспорт",
      "API-доступ",
      "Выделенный менеджер",
    ],
  },
];

const testimonials = [
  {
    quote:
      "За месяц закрыли на 3.2 млн ₽. Раньше менеджер по 4 часа в день копался в 2ГИС — теперь он работает с уже готовой базой.",
    author: "Артём К.",
    role: "Директор по продажам, агропром",
  },
  {
    quote:
      "Перешли с Контур.Компаса. БАЗА в 6 раз дешевле и в 2 раза быстрее. Главное — ИИ сам понимает «кто покупатель», нам не надо учить менеджера ОКВЭДам.",
    author: "Мария С.",
    role: "Founder, маркетинговое агентство",
  },
  {
    quote:
      "Подключили webhook в AmoCRM — лиды сами падают в воронку. Это первый продукт, после которого процесс стал proactive, а не reactive.",
    author: "Денис Р.",
    role: "B2B Sales Manager, IT-интегратор",
  },
];

/* ─────────────────────── Page ─────────────────────── */

export default function Home() {
  return (
    <main className="relative min-h-screen bg-canvas text-white">
      {/* HERO */}
      <HeroSection />

      {/* SOCIAL PROOF STRIP */}
      <section className="border-y border-white/[0.06] bg-white/[0.02] py-12 backdrop-blur-xl">
        <div className="mx-auto max-w-6xl px-6">
          <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
            {stats.map((s) => (
              <div key={s.label} className="text-center">
                <div className="text-3xl font-extralight tracking-tight text-white md:text-4xl">
                  {s.value}
                </div>
                <div className="mt-1 text-xs uppercase tracking-wider text-white/[0.48]">
                  {s.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PROBLEM */}
      <section className="px-6 py-24 md:py-32">
        <div className="mx-auto max-w-3xl">
          <div className="section-eyebrow">Проблема</div>
          <h2 className="mt-3 text-3xl font-light tracking-tight text-white md:text-5xl">
            Найти B2B-клиентов в России — это боль
          </h2>
          <div className="mt-8 space-y-5 text-base leading-relaxed text-white/[0.72] md:text-lg">
            <p>
              Контур.Компас даёт миллион ЮЛ — но ты должен сам знать ОКВЭД,
              регион, размер штата и десяток других фильтров. Менеджер тратит
              часы на настройку запросов, и всё равно половина — мусор.
            </p>
            <p>
              Export-Base продаёт сырые выгрузки. Без воркфлоу, без статусов,
              без обогащения. Купил Excel — и сам его обзваниваешь.
            </p>
            <p>
              Ручной парсинг 2ГИС / Яндекса — это 20 копий на 100 страницах,
              ноль автоматизации, и каптчи каждые 30 минут.
            </p>
            <p className="text-white">
              <span className="font-medium">БАЗА работает по-другому.</span>{" "}
              Опиши бизнес — получи база. Никаких фильтров.
            </p>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how-it-works" className="px-6 py-24 md:py-32">
        <div className="mx-auto max-w-6xl">
          <div className="text-center">
            <div className="section-eyebrow">Как работает</div>
            <h2 className="mt-3 text-3xl font-light tracking-tight text-white md:text-5xl">
              Три шага до первой сделки
            </h2>
          </div>

          <div className="mt-16 grid gap-6 md:grid-cols-3">
            {steps.map((step) => (
              <div
                key={step.num}
                className="rounded-3xl border border-white/[0.10] bg-white/[0.04] p-8 backdrop-blur-2xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]"
              >
                <div className="text-5xl font-extralight tracking-tight text-white/[0.32]">
                  {step.num}
                </div>
                <h3 className="mt-6 text-lg font-medium text-white">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-white/[0.64]">
                  {step.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section className="px-6 py-24 md:py-32">
        <div className="mx-auto max-w-6xl">
          <div className="text-center">
            <div className="section-eyebrow">Возможности</div>
            <h2 className="mt-3 text-3xl font-light tracking-tight text-white md:text-5xl">
              Всё, что нужно для B2B-аутрича
            </h2>
          </div>

          <div className="mt-14 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {features.map((f) => (
              <div
                key={f.title}
                className="rounded-2xl border border-white/[0.10] bg-white/[0.04] p-6 backdrop-blur-xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)] transition-colors duration-200 hover:bg-white/[0.06] hover:border-white/[0.14]"
              >
                <f.icon size={20} className="text-white/[0.72]" strokeWidth={1.5} />
                <h3 className="mt-4 text-base font-medium text-white">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-white/[0.64]">
                  {f.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="px-6 py-24 md:py-32">
        <div className="mx-auto max-w-6xl">
          <div className="text-center">
            <div className="section-eyebrow">Тарифы</div>
            <h2 className="mt-3 text-3xl font-light tracking-tight text-white md:text-5xl">
              Платишь только за результат
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-white/[0.64]">
              Все тарифы включают MX-верификацию email. Отмена в один клик. Без скрытых комиссий.
            </p>
          </div>

          <div className="mt-14 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={`relative flex flex-col rounded-3xl border p-6 backdrop-blur-2xl ${
                  plan.highlight
                    ? "border-brand/30 bg-brand/[0.04] shadow-[0_0_40px_rgba(255,106,0,0.15),inset_0_1px_0_0_rgba(255,255,255,0.10)]"
                    : "border-white/[0.10] bg-white/[0.04] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]"
                }`}
              >
                {plan.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="rounded-full bg-brand px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-black">
                      Популярный
                    </span>
                  </div>
                )}
                <h3 className="text-sm font-medium uppercase tracking-wider text-white/[0.64]">
                  {plan.name}
                </h3>
                <div className="mt-3 flex items-baseline gap-1">
                  <span className="text-4xl font-extralight tracking-tight text-white">
                    {plan.price}
                  </span>
                  <span className="text-sm text-white/[0.48]">{plan.sub}</span>
                </div>
                <ul className="mt-6 flex-1 space-y-2.5">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-white/[0.72]">
                      <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-status-online" strokeWidth={2} />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href={plan.query ? { pathname: "/register", query: plan.query } : "/register"}
                  className="mt-8"
                >
                  <Button
                    variant={plan.highlight ? "brand" : "secondary"}
                    size="default"
                    className="w-full"
                  >
                    {plan.cta}
                  </Button>
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TESTIMONIALS */}
      <section className="px-6 py-24 md:py-32">
        <div className="mx-auto max-w-6xl">
          <div className="text-center">
            <div className="section-eyebrow">Отзывы</div>
            <h2 className="mt-3 text-3xl font-light tracking-tight text-white md:text-5xl">
              Так говорят клиенты
            </h2>
          </div>

          <div className="mt-14 grid gap-4 md:grid-cols-3">
            {testimonials.map((t, i) => (
              <div
                key={i}
                className="rounded-2xl border border-white/[0.10] bg-white/[0.04] p-6 backdrop-blur-xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]"
              >
                <p className="text-sm leading-relaxed text-white/[0.84]">«{t.quote}»</p>
                <div className="mt-5 flex items-center gap-3 border-t border-white/[0.06] pt-4">
                  <div className="flex size-9 items-center justify-center rounded-full border border-white/[0.10] bg-white/[0.04] text-xs font-medium text-white/[0.72]">
                    {t.author.split(" ")[0][0]}
                    {t.author.split(" ")[1]?.[0] ?? ""}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-white">{t.author}</div>
                    <div className="truncate text-xs text-white/[0.48]">{t.role}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="px-6 py-24 md:py-32">
        <div className="mx-auto max-w-3xl">
          <div className="text-center">
            <div className="section-eyebrow">FAQ</div>
            <h2 className="mt-3 text-3xl font-light tracking-tight text-white md:text-5xl">
              Частые вопросы
            </h2>
          </div>
          <div className="mt-14">
            <FaqAccordion />
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="relative isolate overflow-hidden px-6 py-32">
        <div className="aurora-bg pointer-events-none absolute inset-0 -z-10" aria-hidden />
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="text-4xl font-light tracking-tight text-white md:text-6xl">
            Начни первую рассылку{" "}
            <span className="font-extralight italic text-white/[0.72]">сегодня</span>
          </h2>
          <p className="mx-auto mt-5 max-w-xl text-base text-white/[0.64] md:text-lg">
            10 бесплатных лидов прямо сейчас. Без кредитки. Без скрытых
            подписок. Получишь первых клиентов за 60 секунд.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/register">
              <Button variant="brand" size="lg" className="px-8">
                Попробовать бесплатно
                <ArrowRight size={16} />
              </Button>
            </Link>
            <Link href="/plans">
              <Button variant="secondary" size="lg" className="px-8">
                Все тарифы
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-white/[0.06] px-6 py-12">
        <div className="mx-auto max-w-6xl">
          <div className="grid gap-8 md:grid-cols-4">
            <div>
              <Link href="/" className="text-base font-medium text-white">
                БАЗА
              </Link>
              <p className="mt-3 text-sm text-white/[0.48]">
                B2B-лидогенерация на ИИ. Для российского рынка.
              </p>
            </div>
            <div>
              <h4 className="text-xs font-medium uppercase tracking-wider text-white/[0.48]">
                Продукт
              </h4>
              <ul className="mt-4 space-y-2 text-sm text-white/[0.72]">
                <li><Link href="/plans" className="hover:text-white">Тарифы</Link></li>
                <li><Link href="#how-it-works" className="hover:text-white">Как работает</Link></li>
                <li><Link href="/register" className="hover:text-white">Регистрация</Link></li>
              </ul>
            </div>
            <div>
              <h4 className="text-xs font-medium uppercase tracking-wider text-white/[0.48]">
                Юр
              </h4>
              <ul className="mt-4 space-y-2 text-sm text-white/[0.72]">
                <li><Link href="/privacy" className="hover:text-white">Политика конфиденциальности</Link></li>
                <li><Link href="/terms" className="hover:text-white">Условия использования</Link></li>
              </ul>
            </div>
            <div>
              <h4 className="text-xs font-medium uppercase tracking-wider text-white/[0.48]">
                Контакты
              </h4>
              <ul className="mt-4 space-y-2 text-sm text-white/[0.72]">
                <li><a href="mailto:hi@usebaza.ru" className="hover:text-white">hi@usebaza.ru</a></li>
                <li><a href="https://t.me/usebaza" className="hover:text-white">Telegram</a></li>
              </ul>
            </div>
          </div>
          <div className="mt-12 flex flex-col items-center justify-between gap-3 border-t border-white/[0.06] pt-6 text-xs text-white/[0.48] md:flex-row">
            <div>© {new Date().getFullYear()} БАЗА. Все права защищены.</div>
            <div>usebaza.ru</div>
          </div>
        </div>
      </footer>
    </main>
  );
}

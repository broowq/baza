"use client";

import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";

import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";

type PlanRow = {
  id: string;
  name: string;
  projects_limit: number;
  users_limit: number;
  leads_limit_per_month: number;
  searches_per_month?: number;
  can_invite_members: boolean;
  price_monthly_rub?: number;
  price_monthly_usd?: number;
  payment_provider: string;
};

const EXTRA_FEATURES: Record<string, string[]> = {
  starter: ["2ГИС + SearXNG поиск", "Экспорт в CSV", "Скоринг лидов"],
  pro: [
    "2ГИС + Яндекс Карты + SearXNG",
    "Экспорт в CSV",
    "Скоринг лидов",
    "Обогащение контактов",
    "Приоритетная поддержка",
  ],
  team: [
    "2ГИС + Яндекс Карты + SearXNG",
    "Экспорт в CSV",
    "Скоринг лидов",
    "Обогащение контактов",
    "Выделенная поддержка",
    "SLA 99.9%",
  ],
};

function getRublePrice(plan: PlanRow): { price: string; sub: string } {
  const rub = plan.price_monthly_rub ?? 0;
  if (rub === 0) return { price: "Бесплатно", sub: "навсегда" };
  return { price: `${rub.toLocaleString("ru-RU")} ₽`, sub: "/мес" };
}

export default function PlansPage() {
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningPlan, setRunningPlan] = useState<string | null>(null);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const fetchPlans = () => {
    setLoading(true);
    api<PlanRow[]>("/plans")
      .then(setPlans)
      .catch(() => toast.error("Не удалось загрузить тарифы"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsLoggedIn(!!getToken());
    }
    fetchPlans();
  }, []);

  const startCheckout = async (plan: string) => {
    try {
      setRunningPlan(plan);
      const response = await api<{ checkout_url: string; message: string }>("/billing/checkout", {
        method: "POST",
        body: JSON.stringify({ plan }),
      });
      toast.success(response.message);
      window.open(response.checkout_url, "_blank", "noopener,noreferrer");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось создать checkout");
    } finally {
      setRunningPlan(null);
    }
  };

  return (
    <main className="relative min-h-screen overflow-hidden px-4 py-16 sm:px-6">
      <div className="field" />
      <div className="grid-lines" />
      <div className="grain" />

      <div className="relative z-10 mx-auto max-w-5xl">
        {isLoggedIn && (
          <div className="mb-8">
            <Link href="/dashboard" className="text-[12px] t-48 hover:text-white transition-colors">
              ← Дашборд
            </Link>
          </div>
        )}

        {/* Header */}
        <div className="mb-12 sm:mb-20 text-center">
          <div className="eyebrow mb-4">тарифы</div>
          <h1 className="h1 mb-4" style={{ fontSize: 56, lineHeight: 1.05 }}>
            Выберите тариф под ваш рост.
          </h1>
          <p className="mx-auto max-w-md text-[14px] t-72">
            Платите только за то, что используете. Без скрытых комиссий.
          </p>
        </div>

        {loading && (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border border-white/10 border-t-white/60" />
          </div>
        )}

        {!loading && plans.length === 0 && (
          <div className="panel p-10 text-center">
            <p className="t-72 text-[13px] mb-4">Не удалось загрузить тарифы.</p>
            <button
              onClick={fetchPlans}
              className="ghost rounded-full px-5 py-2 text-[13px]"
            >
              Попробовать снова
            </button>
          </div>
        )}

        {/* Plan cards */}
        <div className="grid items-stretch gap-5 md:grid-cols-3">
          {plans.map((plan) => {
            const key = plan.id.toLowerCase();
            const isPro = key === "pro";
            const isStarter = key === "starter";
            const rublePrice = getRublePrice(plan);
            const extras = EXTRA_FEATURES[key] ?? [];

            return (
              <div
                key={plan.id}
                className={`relative flex flex-col p-7 ${isPro ? "panel md:scale-[1.02]" : "panel-flat panel-flat--lg"}`}
                style={
                  isPro
                    ? {
                        boxShadow:
                          "inset 0 1px 0 0 rgba(255,255,255,0.08), 0 0 0 1px rgba(168,197,192,0.28), 0 30px 80px -28px rgba(168,197,192,0.25), 0 24px 60px -28px rgba(0,0,0,0.7)",
                      }
                    : undefined
                }
              >
                {isPro && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-[11px] mono text-black">
                      популярный
                    </span>
                  </div>
                )}

                <div className="eyebrow mb-3">{plan.name}</div>

                <div className="flex items-baseline gap-2">
                  <span
                    className="tnum text-white"
                    style={{ fontSize: 40, fontWeight: 200, letterSpacing: "-0.02em" }}
                  >
                    {rublePrice.price}
                  </span>
                  <span className="text-[12px] t-48">{rublePrice.sub}</span>
                </div>

                <div className="hairline my-6" />

                <ul className="flex-1 space-y-3">
                  <FeatureItem>
                    {plan.searches_per_month ?? "∞"} сборов/мес
                  </FeatureItem>
                  <FeatureItem>
                    до {plan.leads_limit_per_month.toLocaleString("ru-RU")} лидов
                  </FeatureItem>
                  <FeatureItem>{plan.projects_limit} проектов</FeatureItem>
                  <FeatureItem>
                    {plan.users_limit}{" "}
                    {plan.users_limit === 1 ? "пользователь" : "пользователей"}
                  </FeatureItem>
                  {extras.map((feat) => (
                    <FeatureItem key={feat}>{feat}</FeatureItem>
                  ))}
                </ul>

                <button
                  onClick={() => !isStarter && startCheckout(plan.id)}
                  disabled={isStarter || runningPlan === plan.id}
                  className={
                    isPro
                      ? "brand mt-8 w-full rounded-full px-5 py-3 text-[13.5px] flex items-center justify-center gap-2 disabled:opacity-50 disabled:pointer-events-none"
                      : "ghost mt-8 w-full rounded-full px-5 py-3 text-[13.5px] flex items-center justify-center gap-2 disabled:opacity-50 disabled:pointer-events-none"
                  }
                >
                  {runningPlan === plan.id ? (
                    <span className="flex items-center gap-2">
                      <span className="h-4 w-4 animate-spin rounded-full border border-current border-t-transparent" />
                      Создаём…
                    </span>
                  ) : isStarter ? (
                    <>Текущий тариф</>
                  ) : (
                    <>
                      Перейти на {plan.name}
                      <ArrowRight size={14} />
                    </>
                  )}
                </button>
              </div>
            );
          })}
        </div>

        {/* Bottom CTA */}
        <div className="mt-16 text-center">
          <p className="text-[13px] t-72">
            Нужен индивидуальный тариф?{" "}
            <Link
              href="mailto:hello@usebaza.ru"
              className="text-white underline underline-offset-4 hover:t-72 transition-colors"
            >
              Напишите нам
            </Link>
          </p>
        </div>

        <p className="mt-12 text-center text-[11px] t-40">
          © 2026 База · usebaza.ru
        </p>
      </div>
    </main>
  );
}

function FeatureItem({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-3 text-[13px] t-84">
      <span className="dot dot-mt" />
      {children}
    </li>
  );
}

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
  can_invite_members: boolean;
  price_monthly_rub?: number;
  price_monthly_usd?: number;
  payment_provider: string;
};

const EXTRA_FEATURES: Record<string, string[]> = {
  starter: ["2ГИС + SearXNG поиск", "Экспорт в CSV", "Скоринг лидов"],
  // growth = тир «Team» (enum-значение team занято тиром Business)
  growth: [
    "2ГИС + Яндекс Карты + SearXNG",
    "Экспорт в CSV",
    "Скоринг лидов",
    "Обогащение контактов",
  ],
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
    "приоритетный SLA",
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
  // null = anonymous (no current plan); "free"/"starter"/"growth"/"pro"/"team" when logged in.
  // Used to honestly mark the user's actual plan as "Текущий тариф" instead of
  // hardcoding Starter — which was wrong for anyone on Pro/Business.
  const [currentPlan, setCurrentPlan] = useState<string | null>(null);
  // Согласие на автопродление (сохранение карты в ЮKassa + ежемесячные
  // автосписания). По умолчанию включено; отключается тут же или в настройках.
  const [autoRenew, setAutoRenew] = useState(true);

  const fetchPlans = () => {
    setLoading(true);
    api<PlanRow[]>("/plans")
      .then(setPlans)
      .catch(() => toast.error("Не удалось загрузить тарифы"))
      .finally(() => setLoading(false));
  };

  const fetchCurrentPlan = () => {
    api<{ plan?: string }>("/organizations/me")
      .then((org) => setCurrentPlan(org?.plan ?? null))
      .catch(() => setCurrentPlan(null)); // anon/no-org → no current plan, all clickable
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      const loggedIn = !!getToken();
      setIsLoggedIn(loggedIn);
      if (loggedIn) fetchCurrentPlan();
    }
    fetchPlans();
  }, []);

  const startCheckout = async (plan: string) => {
    if (!isLoggedIn) {
      toast.info("Войдите в аккаунт, чтобы оплатить тариф");
      return;
    }
    try {
      setRunningPlan(plan);
      const response = await api<{ checkout_url: string; message: string }>("/billing/checkout", {
        method: "POST",
        body: JSON.stringify({ plan, auto_renew: autoRenew }),
      });
      if (response.message) toast.success(response.message);
      // Same-tab redirect → ЮKassa возвращает на /billing/return после оплаты.
      window.location.assign(response.checkout_url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Не удалось создать checkout");
      setRunningPlan(null);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden px-4 py-16 sm:px-6">
      <div className="field" />
      <div className="grid-lines" />
      <div className="grain" />

      {/* max-w-6xl: 4 тира в ряд на xl — в 5xl карточкам тесно (цена переносится) */}
      <div className="relative z-10 mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-12 sm:mb-20 text-center">
          <div className="eyebrow mb-4">тарифы</div>
          <h1 className="h1 mb-4" style={{ fontSize: "clamp(34px, 8vw, 56px)", lineHeight: 1.05 }}>
            Выберите тариф <span className="serif-i c-mint">под ваш рост.</span>
          </h1>
          <p className="mx-auto max-w-[560px] caption">
            Платите только за то, что используете. Без скрытых комиссий и без обязательств.
          </p>
        </div>

        {loading && (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border border-[var(--line-2)] border-t-[var(--t-56)]" />
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

        {/* Auto-renew consent (только для залогиненных — анониму нечего оплачивать) */}
        {isLoggedIn && !loading && plans.length > 0 && (
          <label className="mt-10 flex cursor-pointer items-start justify-center gap-2.5 text-left sm:items-center">
            <input
              type="checkbox"
              checked={autoRenew}
              onChange={(e) => setAutoRenew(e.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-[var(--mint)] sm:mt-0"
            />
            <span className="text-[12px] t-72 max-w-[560px]">
              Автопродление: согласен на сохранение способа оплаты и ежемесячные
              списания по тарифу. Отключить можно в любой момент в настройках.
            </span>
          </label>
        )}

        {/* Plan cards (v3): 4 тира — на десктопе в один ряд, на планшете 2×2 */}
        <div className="grid items-start gap-5 md:grid-cols-2 xl:grid-cols-4 mt-12">
          {plans.map((plan) => {
            const key = plan.id.toLowerCase();
            const isPro = key === "pro";
            const isStarter = key === "starter";
            const isCurrent = currentPlan !== null && key === currentPlan.toLowerCase();
            const rublePrice = getRublePrice(plan);
            const extras = EXTRA_FEATURES[key] ?? [];

            return (
              <div
                key={plan.id}
                className={isPro ? "pro-card p-7" : "panel-flat p-7 relative"}
              >
                {isPro && <span className="pro-tag">популярный</span>}

                <div className="eyebrow">{plan.name}</div>

                <div className="mt-5">
                  <div className="h2 tnum" style={{ fontSize: 40, lineHeight: 1 }}>
                    {rublePrice.price}
                    {rublePrice.sub === "/мес" && (
                      <span
                        className="t-40 mono"
                        style={{ fontSize: 14, fontWeight: 300, letterSpacing: 0 }}
                      >
                        {" "}{rublePrice.sub}
                      </span>
                    )}
                  </div>
                  <div className="mono-cap mt-2">
                    {isStarter ? "для старта"
                      : key === "growth" ? "первый шаг с Яндекс.Картами"
                      : isPro ? "для растущих команд"
                      : "для отделов продаж и сетей"}
                  </div>
                </div>

                <div
                  className="hairline my-6"
                  style={isPro ? { borderColor: "rgba(168,197,192,0.18)" } : undefined}
                />

                <div>
                  <div className="feat">
                    <span className="b" />
                    <span>
                      До {plan.leads_limit_per_month.toLocaleString("ru-RU")} лидов в месяц
                    </span>
                  </div>
                  <div className="feat">
                    <span className="b" />
                    <span>Сбор дозами, без повторов</span>
                  </div>
                  <div className="feat">
                    <span className="b" />
                    <span>
                      {plan.projects_limit === 999 || plan.projects_limit > 100
                        ? "Безлимит проектов"
                        : `${plan.projects_limit} проектов`}
                    </span>
                  </div>
                  <div className="feat">
                    <span className="b" />
                    <span>
                      {plan.users_limit}{" "}
                      {plan.users_limit === 1 ? "пользователь" : plan.users_limit < 5 ? "пользователя" : "пользователей"}
                    </span>
                  </div>
                  {extras.map((feat) => (
                    <div key={feat} className="feat">
                      <span className="b" />
                      <span>{feat}</span>
                    </div>
                  ))}
                </div>

                <button
                  onClick={() => !isCurrent && startCheckout(plan.id)}
                  disabled={isCurrent || runningPlan === plan.id}
                  className={
                    isPro
                      ? "btn btn-brand w-full mt-7"
                      : "btn btn-ghost w-full mt-7"
                  }
                  style={{ height: 42 }}
                >
                  {runningPlan === plan.id ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border border-current border-t-transparent" />
                      Создаём…
                    </>
                  ) : isCurrent ? (
                    <>Текущий тариф</>
                  ) : (
                    <>
                      Перейти на {plan.name}
                      <ArrowRight size={13} />
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
              href="mailto:support@usebaza.ru"
              className="text-[var(--t-100)] underline underline-offset-4 hover:t-72 transition-colors"
            >
              Напишите нам
            </Link>
          </p>
        </div>

        <p className="mt-12 text-center text-[11px] t-40">
          © 2026 База · usebaza.ru
        </p>
      </div>
    </div>
  );
}


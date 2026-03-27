"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Check, Sparkles } from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";
import { motion } from "framer-motion";

import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

type PlanRow = {
  id: string;
  name: string;
  projects_limit: number;
  users_limit: number;
  leads_limit_per_month: number;
  can_invite_members: boolean;
  price_monthly_usd: number;
  payment_provider: string;
};

const RUBLE_PRICES: Record<string, { price: string; sub: string }> = {
  starter: { price: "Бесплатно", sub: "навсегда" },
  pro: { price: "2 900 ₽", sub: "/мес" },
  team: { price: "7 900 ₽", sub: "/мес" },
};

const EXTRA_FEATURES: Record<string, string[]> = {
  starter: ["Экспорт в CSV", "Скоринг лидов"],
  pro: ["Экспорт в CSV", "Скоринг лидов", "Обогащение контактов", "Приоритетная поддержка"],
  team: ["Экспорт в CSV", "Скоринг лидов", "Обогащение контактов", "Выделенная поддержка", "SLA 99.9%"],
};

const CHECK_COLORS: Record<string, string> = {
  starter: "bg-emerald-500/15 text-emerald-400",
  pro: "bg-violet-500/15 text-violet-400",
  team: "bg-sky-500/15 text-sky-400",
};

function getRublePrice(plan: PlanRow): { price: string; sub: string } {
  const key = plan.id.toLowerCase();
  if (key in RUBLE_PRICES) return RUBLE_PRICES[key];
  const nameKey = plan.name.toLowerCase();
  if (nameKey in RUBLE_PRICES) return RUBLE_PRICES[nameKey];
  if (plan.price_monthly_usd === 0) return { price: "Бесплатно", sub: "навсегда" };
  return { price: `${plan.price_monthly_usd} $`, sub: "/мес" };
}

const cardVariants = {
  hidden: { opacity: 0, y: 40 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      delay: i * 0.15,
      duration: 0.5,
      ease: [0.25, 0.4, 0.25, 1],
    },
  }),
};

const headerVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: [0.25, 0.4, 0.25, 1] },
  },
};

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
    <main className="relative min-h-screen overflow-hidden bg-white px-4 py-16 dark:bg-[#09090b] sm:px-6">
      {/* Background ambient glow */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-0 h-[600px] w-[900px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-500/[0.07] blur-[120px]" />
        <div className="absolute bottom-0 left-0 h-[400px] w-[400px] -translate-x-1/2 translate-y-1/2 rounded-full bg-sky-500/[0.05] blur-[100px]" />
        <div className="absolute bottom-0 right-0 h-[400px] w-[400px] translate-x-1/2 translate-y-1/2 rounded-full bg-emerald-500/[0.05] blur-[100px]" />
      </div>

      <div className="relative mx-auto max-w-5xl">
        {isLoggedIn && (
          <div className="mb-4">
            <Link
              href="/dashboard"
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              &larr; Дашборд
            </Link>
          </div>
        )}

        {/* Header */}
        <motion.div
          className="mb-20 text-center"
          initial="hidden"
          animate="visible"
          variants={headerVariants}
        >
          <Badge variant="secondary" className="mb-6 gap-1.5 px-3 py-1 text-xs">
            <Sparkles className="size-3" />
            Тарифы
          </Badge>
          <h1 className="text-4xl font-bold tracking-tight md:text-5xl lg:text-6xl">
            <span className="bg-gradient-to-r from-foreground via-foreground/80 to-foreground/60 bg-clip-text text-transparent">
              Выберите тариф под ваш рост
            </span>
          </h1>
          <p className="mx-auto mt-4 max-w-md text-base text-muted-foreground md:text-lg">
            Платите только за то, что используете. Без скрытых комиссий.
          </p>
        </motion.div>

        {/* Loading spinner */}
        {loading && (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground/20 border-t-foreground" />
          </div>
        )}

        {/* Empty state */}
        {!loading && plans.length === 0 && (
          <div className="py-12 text-center">
            <p className="text-muted-foreground">Не удалось загрузить тарифы.</p>
            <Button onClick={fetchPlans} variant="outline" className="mt-4">
              Попробовать снова
            </Button>
          </div>
        )}

        {/* Plan cards */}
        <div className="grid items-center gap-6 md:grid-cols-3">
          {plans.map((plan, index) => {
            const key = plan.id.toLowerCase();
            const isPro = key === "pro";
            const rublePrice = getRublePrice(plan);
            const isStarter = key === "starter";
            const extras = EXTRA_FEATURES[key] ?? [];
            const checkColor = CHECK_COLORS[key] ?? CHECK_COLORS.starter;

            return (
              <motion.div
                key={plan.id}
                custom={index}
                initial="hidden"
                animate="visible"
                variants={cardVariants}
                className={`relative flex flex-col rounded-2xl border p-8 transition-shadow duration-300 ${
                  isPro
                    ? "z-10 scale-105 border-violet-500/30 bg-white/5 shadow-2xl shadow-violet-500/20 backdrop-blur-md dark:bg-white/[0.08]"
                    : "border-white/10 bg-white/5 backdrop-blur-md hover:border-white/20 dark:bg-white/[0.04]"
                }`}
              >
                {/* Popular badge for Pro */}
                {isPro && (
                  <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-500/10 px-4 py-1 text-xs font-semibold ring-1 ring-violet-500/20 backdrop-blur-sm">
                      <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-violet-400 bg-clip-text text-transparent animate-[gradient_3s_ease-in-out_infinite]">
                        Популярный
                      </span>
                    </span>
                  </div>
                )}

                {/* Plan name */}
                <p className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
                  {plan.name}
                </p>

                {/* Price */}
                <div className="mt-4 flex items-baseline gap-1.5">
                  <span className="text-4xl font-bold tracking-tight tabular-nums text-foreground md:text-5xl">
                    {rublePrice.price}
                  </span>
                  <span className="text-sm text-muted-foreground">{rublePrice.sub}</span>
                </div>

                <Separator className="my-6 bg-white/10" />

                {/* Features list */}
                <ul className="flex-1 space-y-3.5">
                  <li className="flex items-center gap-3 text-sm text-foreground/80">
                    <FeatureCheck colorClass={checkColor} />
                    {plan.leads_limit_per_month.toLocaleString("ru-RU")} лидов/мес
                  </li>
                  <li className="flex items-center gap-3 text-sm text-foreground/80">
                    <FeatureCheck colorClass={checkColor} />
                    {plan.projects_limit} проектов
                  </li>
                  <li className="flex items-center gap-3 text-sm text-foreground/80">
                    <FeatureCheck colorClass={checkColor} />
                    {plan.users_limit} пользователей
                  </li>
                  {extras.map((feat) => (
                    <li key={feat} className="flex items-center gap-3 text-sm text-foreground/80">
                      <FeatureCheck colorClass={checkColor} />
                      {feat}
                    </li>
                  ))}
                </ul>

                {/* CTA Button */}
                <button
                  className={`mt-8 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold transition-all duration-200 ${
                    isStarter
                      ? "bg-foreground/10 text-muted-foreground cursor-not-allowed"
                      : isPro
                        ? "bg-violet-500 text-white shadow-lg shadow-violet-500/25 hover:bg-violet-600 hover:shadow-violet-500/40"
                        : "bg-foreground/10 text-foreground hover:bg-foreground/15"
                  }`}
                  onClick={() => !isStarter && startCheckout(plan.id)}
                  disabled={isStarter || runningPlan === plan.id}
                >
                  {runningPlan === plan.id ? (
                    <span className="flex items-center gap-2">
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                      Создаём...
                    </span>
                  ) : isStarter ? (
                    <>Текущий тариф</>
                  ) : (
                    <>
                      Перейти на {plan.name}
                      <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </motion.div>
            );
          })}
        </div>

        {/* Bottom CTA */}
        <motion.div
          className="mt-20 text-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8, duration: 0.5 }}
        >
          <p className="text-sm text-muted-foreground">
            Нужен индивидуальный тариф?{" "}
            <Link
              href="mailto:hello@baza.io"
              className="font-medium text-foreground underline underline-offset-4 transition-colors hover:text-foreground/80"
            >
              Напишите нам
            </Link>
          </p>
        </motion.div>
      </div>
    </main>
  );
}

function FeatureCheck({ colorClass }: { colorClass: string }) {
  return (
    <div
      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${colorClass}`}
    >
      <Check size={12} strokeWidth={3} />
    </div>
  );
}

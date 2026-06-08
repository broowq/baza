"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowRight, CheckCircle2, Clock, XCircle } from "lucide-react";

import { api } from "@/lib/api";
import { formatPlan } from "@/lib/plans";

type SubscriptionResp = {
  id?: string;
  plan_id?: string;
  status?: "none" | "pending" | "active" | "canceled" | string;
  current_period_end?: string | null;
  payment_id?: string | null;
};

type Phase = "checking" | "active" | "pending" | "canceled" | "error";

function ReturnBody() {
  const search = useSearchParams();
  const subscriptionId = search?.get("subscription_id") ?? null;
  const [phase, setPhase] = useState<Phase>("checking");
  const [attempt, setAttempt] = useState(0);
  const [planId, setPlanId] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  // Webhook ЮKassa может прийти с задержкой 1–5 с. Поллим
  // /billing/subscription каждые 2 с до 20 попыток (≈ 40 с) — этого
  // хватает в 99% случаев. Если webhook задержался — пользователь
  // увидит «обрабатываем», подписка активируется в фоне.
  useEffect(() => {
    let cancelled = false;
    const maxAttempts = 20;

    const tick = async (i: number) => {
      try {
        const sub = await api<SubscriptionResp>("/billing/subscription");
        if (cancelled) return;
        if (sub.plan_id) setPlanId(sub.plan_id);

        if (sub.status === "active") {
          setPhase("active");
          return;
        }
        if (sub.status === "canceled") {
          setPhase("canceled");
          return;
        }
        if (i >= maxAttempts) {
          // Платёж создан, но webhook ещё не пришёл — это нормально для
          // долгой задержки на стороне ЮKassa. Показываем «в обработке».
          setPhase("pending");
          return;
        }
        setAttempt(i + 1);
        setTimeout(() => {
          if (!cancelled) tick(i + 1);
        }, 2000);
      } catch (e) {
        if (cancelled) return;
        setErrMsg(e instanceof Error ? e.message : String(e));
        setPhase("error");
      }
    };

    tick(0);
    return () => {
      cancelled = true;
    };
    // subscriptionId — ID, по которому фронт ничего не запрашивает напрямую,
    // но участвует в return_url. Не вешаем его в зависимости, чтобы не
    // перезапускать поллер на пустых ререндерах.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="relative min-h-screen overflow-hidden px-4 py-24 sm:px-6">
      <div className="field" />
      <div className="grid-lines" />
      <div className="grain" />

      <div className="relative z-10 mx-auto max-w-xl">
        <div className="panel p-10 text-center">
          {phase === "checking" && (
            <>
              <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center">
                <span className="h-8 w-8 animate-spin rounded-full border border-white/15 border-t-white/70" />
              </div>
              <h1 className="h2 mb-3" style={{ fontSize: 28 }}>
                Подтверждаем платёж
              </h1>
              <p className="caption mb-2">
                Ждём подтверждение от ЮKassa. Обычно занимает 2–5 секунд.
              </p>
              <p className="mono-cap">попытка {attempt + 1} / 20</p>
            </>
          )}

          {phase === "active" && (
            <>
              <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center text-[#A8C5C0]">
                <CheckCircle2 size={44} strokeWidth={1.5} />
              </div>
              <h1 className="h2 mb-3" style={{ fontSize: 28 }}>
                Оплата прошла
              </h1>
              <p className="caption mb-6">
                {planId
                  ? `Тариф «${formatPlan(planId)}» активирован, лимиты подняты.`
                  : "Тариф активирован, лимиты подняты."}
              </p>
              <Link href="/dashboard" className="btn btn-brand inline-flex" style={{ height: 42 }}>
                В дашборд <ArrowRight size={13} />
              </Link>
            </>
          )}

          {phase === "pending" && (
            <>
              <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center text-white/70">
                <Clock size={44} strokeWidth={1.5} />
              </div>
              <h1 className="h2 mb-3" style={{ fontSize: 28 }}>
                Платёж в обработке
              </h1>
              <p className="caption mb-6">
                ЮKassa получила платёж, но подтверждение задерживается.
                Подписка активируется автоматически, как только webhook
                дойдёт. Можно закрыть эту страницу — мы пришлём email при
                активации.
              </p>
              <Link href="/dashboard" className="btn btn-ghost inline-flex" style={{ height: 42 }}>
                В дашборд <ArrowRight size={13} />
              </Link>
            </>
          )}

          {phase === "canceled" && (
            <>
              <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center text-white/70">
                <XCircle size={44} strokeWidth={1.5} />
              </div>
              <h1 className="h2 mb-3" style={{ fontSize: 28 }}>
                Платёж отменён
              </h1>
              <p className="caption mb-6">
                Платёж не прошёл или был отменён. Деньги не списаны. Попробуйте ещё раз
                или выберите другой тариф.
              </p>
              <Link href="/plans" className="btn btn-brand inline-flex" style={{ height: 42 }}>
                К тарифам <ArrowRight size={13} />
              </Link>
            </>
          )}

          {phase === "error" && (
            <>
              <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center text-white/70">
                <XCircle size={44} strokeWidth={1.5} />
              </div>
              <h1 className="h2 mb-3" style={{ fontSize: 28 }}>
                Не удалось проверить статус
              </h1>
              <p className="caption mb-2">
                {errMsg ?? "Что-то пошло не так. Подписка проверится сама в дашборде."}
              </p>
              <Link href="/dashboard" className="btn btn-ghost inline-flex mt-6" style={{ height: 42 }}>
                В дашборд <ArrowRight size={13} />
              </Link>
            </>
          )}

          <p className="mono-cap mt-10">
            Вопросы по оплате —{" "}
            <a href="mailto:support@usebaza.ru" className="text-white underline underline-offset-2">
              support@usebaza.ru
            </a>
          </p>
        </div>
      </div>
    </main>
  );
}

export default function BillingReturnPage() {
  return (
    <Suspense fallback={
      <main className="relative min-h-screen overflow-hidden px-4 py-24 sm:px-6">
        <div className="field" />
        <div className="grid-lines" />
        <div className="grain" />
        <div className="relative z-10 mx-auto max-w-xl">
          <div className="panel p-10 text-center">
            <span className="mx-auto block h-8 w-8 animate-spin rounded-full border border-white/15 border-t-white/70" />
          </div>
        </div>
      </main>
    }>
      <ReturnBody />
    </Suspense>
  );
}

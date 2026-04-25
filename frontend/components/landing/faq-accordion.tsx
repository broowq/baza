"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

export type FaqItem = { q: string; a: string };

const DEFAULT_ITEMS: FaqItem[] = [
  {
    q: "Откуда вы берёте данные?",
    a: "16 источников: открытый ЕГРЮЛ от ФНС, 2ГИС, Яндекс Карты, Bing, web-поиск (SearXNG), Rusprofile. Все источники легальные, парсинг идёт по их публичным API и страницам.",
  },
  {
    q: "Это легально?",
    a: "Да. Мы зарегистрированы как оператор персональных данных в Роскомнадзоре, юр.лица — это публичная информация ФНС. На сайте опубликованы Политика конфиденциальности и Оферта.",
  },
  {
    q: "Насколько точны email и телефоны?",
    a: "Каждый email проходит MX-проверку (~94% доставляемость). Телефоны нормализуются под формат E.164 и валидируются через phonenumbers. На странице лида видны зелёный/красный значки качества.",
  },
  {
    q: "В чём отличие от Контур.Компас?",
    a: "Компас работает по фильтрам ОКВЭД + регион + штат. БАЗА — по промпту. Описываешь свой бизнес одной фразой, ИИ сам решает, кто покупатель. Плюс мы в 6 раз дешевле и сразу даём webhook в CRM.",
  },
  {
    q: "Какие форматы экспорта?",
    a: "CSV (UTF-8 BOM, открывается в Excel), XLSX с гиперссылками на email/телефон/сайт, real-time webhook в Bitrix24/AmoCRM/любую кастомную CRM. На Pro+ — API-доступ.",
  },
  {
    q: "Как отменить подписку?",
    a: "В личном кабинете → Тарифы → «Отменить». Без звонков менеджеру. Деньги за неиспользованный период возвращаются на карту в течение 3 дней.",
  },
];

export function FaqAccordion({ items = DEFAULT_ITEMS }: { items?: FaqItem[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {items.map((faq, i) => {
        const isOpen = openIndex === i;
        return (
          <div
            key={faq.q}
            className="rounded-2xl border border-white/[0.10] bg-white/[0.04] backdrop-blur-xl transition-colors duration-200 hover:bg-white/[0.06]"
          >
            <button
              onClick={() => setOpenIndex(isOpen ? null : i)}
              aria-expanded={isOpen}
              className="flex w-full items-center justify-between px-5 py-4 text-left sm:px-6"
            >
              <h3 className="text-sm font-medium text-white sm:text-base">
                {faq.q}
              </h3>
              <ChevronDown
                size={18}
                className={`shrink-0 text-white/[0.48] transition-transform duration-200 ${
                  isOpen ? "rotate-180" : ""
                }`}
              />
            </button>
            <div
              className="grid transition-all duration-200"
              style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
            >
              <div className="overflow-hidden">
                <p className="px-5 pb-5 text-sm leading-relaxed text-white/[0.64] sm:px-6">
                  {faq.a}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

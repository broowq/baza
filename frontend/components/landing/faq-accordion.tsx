"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

type FaqItem = { q: string; a: string };

export function FaqAccordion({ items }: { items: FaqItem[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {items.map((faq, i) => {
        const isOpen = openIndex === i;
        return (
          <div
            key={faq.q}
            className="rounded-2xl border border-slate-200/70 bg-white/90 backdrop-blur-xl transition-all duration-300 dark:border-white/[0.08] dark:bg-white/[0.04] hover:dark:bg-white/[0.06]"
          >
            <button
              onClick={() => setOpenIndex(isOpen ? null : i)}
              aria-expanded={isOpen}
              className="flex w-full items-center justify-between px-6 py-4 text-left"
            >
              <h3 className="font-semibold text-slate-900 dark:text-white">{faq.q}</h3>
              <ChevronDown
                size={18}
                className={`shrink-0 text-slate-400 transition-transform duration-300 ${isOpen ? "rotate-180" : ""}`}
              />
            </button>
            <div
              className="grid transition-all duration-300"
              style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
            >
              <div className="overflow-hidden">
                <p className="px-6 pb-4 text-sm text-slate-500 dark:text-slate-400">{faq.a}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

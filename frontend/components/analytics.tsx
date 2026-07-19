"use client";

import Script from "next/script";
import { useEffect, useState } from "react";

const COOKIE_CONSENT_KEY = "baza_cookie_consent";

/**
 * Яндекс.Метрика (с вебвизором) грузится ТОЛЬКО после явного согласия на
 * cookie (ревью 20.07: раньше скрипт и запись сессий стартовали безусловно,
 * вопреки собственной политике §11 и требованию к cookie-согласию). Кнопка
 * «Отклонить» теперь реально отключает аналитику.
 *
 * Согласие читается из localStorage (baza_cookie_consent="accepted") + слушаем
 * кастомное событие baza-cookie-consent, чтобы включиться сразу после клика
 * «Принять» без перезагрузки.
 */
export default function Analytics() {
  const id = process.env.NEXT_PUBLIC_YANDEX_METRIKA_ID;
  const [consented, setConsented] = useState(false);

  useEffect(() => {
    const read = () => setConsented(localStorage.getItem(COOKIE_CONSENT_KEY) === "accepted");
    read();
    window.addEventListener("baza-cookie-consent", read);
    return () => window.removeEventListener("baza-cookie-consent", read);
  }, []);

  if (!id || !consented) return null;

  return (
    <>
      <Script id="yandex-metrika" strategy="afterInteractive">
        {`
          (function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
          m[i].l=1*new Date();
          for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r)return;}
          k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})
          (window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");
          ym(${id},"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});
        `}
      </Script>
      <noscript>
        <div>
          <img
            src={`https://mc.yandex.ru/watch/${id}`}
            style={{ position: "absolute", left: "-9999px" }}
            alt=""
          />
        </div>
      </noscript>
    </>
  );
}

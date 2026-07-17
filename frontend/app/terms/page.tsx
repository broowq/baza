import Link from "next/link";
import type { Route } from "next";

export const metadata = {
  title: "Условия использования — БАЗА",
  description: "Условия использования SaaS-платформы БАЗА (usebaza.ru).",
};

export default function TermsPage() {
  return (
    <main className="relative min-h-screen px-4 sm:px-6 py-12 sm:py-16">
      <div className="canvas-bg" />
      <div className="grain" />

      <article className="relative z-10 mx-auto max-w-[760px]">
        <header className="mb-10">
          <div className="eyebrow mb-3">правовой документ</div>
          <h1 className="h1 mb-3" style={{ fontSize: "clamp(28px,6vw,44px)", lineHeight: 1.1 }}>
            Условия использования
          </h1>
          <p className="mono-cap">
            Дата вступления в силу: 1 января 2026 г. ·{" "}
            <Link href={"/privacy" as Route} className="underline underline-offset-2 text-white">
              политика обработки ПД
            </Link>
          </p>
        </header>

        <Sec n="1" title="Описание Сервиса">
          <P>
            Настоящие Условия использования (далее — Условия) регулируют
            порядок доступа и использования SaaS-платформы БАЗА (далее —
            Сервис). Используя Сервис, вы подтверждаете согласие с настоящими
            Условиями.
          </P>
          <P>
            БАЗА — мультитенантная B2B-платформа для поиска, обогащения и
            управления коммерческими лидами. Сервис предоставляет инструменты
            для автоматического сбора контактных данных из открытых источников,
            скоринга, экспорта и командной работы.
          </P>
        </Sec>

        <Sec n="2" title="Обязанности пользователя">
          <Ul>
            <li>Предоставлять достоверные регистрационные данные.</li>
            <li>Обеспечивать конфиденциальность учётных данных.</li>
            <li>Использовать Сервис в соответствии с законодательством РФ.</li>
            <li>
              Не использовать Сервис для рассылки спама, мошенничества или
              иной незаконной деятельности.
            </li>
            <li>
              Не превышать лимиты тарифного плана и не пытаться обойти
              технические ограничения.
            </li>
          </Ul>
        </Sec>

        <Sec n="3" title="Тарифы и оплата">
          <P>
            Стоимость подписки определяется выбранным тарифным планом. Оплата
            производится ежемесячно в рублях РФ. Сервис является цифровым:
            доступ к оплаченным функциям предоставляется онлайн автоматически
            сразу после поступления оплаты, услуга оказывается дистанционно,
            физическая доставка товаров отсутствует. При отмене подписки
            доступ к платным функциям сохраняется до конца оплаченного
            периода. Возврат средств осуществляется в соответствии с
            законодательством РФ о защите прав потребителей.
          </P>
        </Sec>

        <Sec n="4" title="Данные и интеллектуальная собственность">
          <P>
            Данные, собранные вами через Сервис, принадлежат вашей
            организации. Мы не претендуем на права собственности на
            пользовательские данные. Программное обеспечение, дизайн и
            контент Сервиса являются интеллектуальной собственностью БАЗА.
          </P>
        </Sec>

        <Sec n="5" title="Ограничение ответственности">
          <P>
            Сервис предоставляется &laquo;как есть&raquo;. Мы не гарантируем
            бесперебойную работу и не несём ответственности за упущенную
            выгоду, потерю данных или косвенные убытки, возникшие в результате
            использования Сервиса. Максимальная ответственность ограничена
            суммой, оплаченной пользователем за последние 3 месяца.
          </P>
        </Sec>

        <Sec n="6" title="Прекращение использования">
          <P>
            Вы можете удалить учётную запись в любое время через настройки
            аккаунта. Мы оставляем за собой право приостановить или прекратить
            доступ к Сервису в случае нарушения настоящих Условий. При
            прекращении действия аккаунта данные удаляются в соответствии с
            Политикой конфиденциальности.
          </P>
        </Sec>

        <Sec n="7" title="Применимое право">
          <P>
            Настоящие Условия регулируются законодательством Российской
            Федерации. Все споры подлежат рассмотрению в суде по
            месту нахождения оператора Сервиса.
          </P>
        </Sec>

        <Sec n="8" title="Контакты">
          <P>
            По вопросам, связанным с настоящими Условиями, обращайтесь:{" "}
            <a href="mailto:support@usebaza.ru" className="text-white underline underline-offset-2">
              support@usebaza.ru
            </a>
            .
          </P>
        </Sec>

        <Sec n="9" title="Реквизиты Исполнителя">
          <P>Услуги по настоящим Условиям оказывает:</P>
          <Ul>
            <li>Полное наименование: Общество с ограниченной ответственностью «ПРО ЛЕС»</li>
            <li>Сокращённое наименование: ООО «ПРО ЛЕС»</li>
            <li>ОГРН: 1215400050117</li>
            <li>ИНН: 5406817586</li>
            <li>КПП: 540601001</li>
            <li>Юридический адрес: 630007, г. Новосибирск, ул. Коммунистическая, влд. 6, оф. 205</li>
            <li>
              Электронная почта:{" "}
              <a href="mailto:support@usebaza.ru" className="text-white underline underline-offset-2">
                support@usebaza.ru
              </a>
            </li>
          </Ul>
        </Sec>

        <footer className="mono-cap mt-14 pt-6 border-t border-[var(--line)] flex flex-wrap items-center justify-between gap-4">
          <Link href={"/" as Route} className="text-white/48 hover:text-white transition-colors">
            &larr; На главную
          </Link>
          <span>
            © 2026 БАЗА · usebaza.ru · вопросы на{" "}
            <a href="mailto:support@usebaza.ru" className="text-white">support@usebaza.ru</a>
          </span>
        </footer>
      </article>
    </main>
  );
}

/* ── Inline section/list helpers ────────────────────────────────── */

function Sec({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="h3 mb-4 flex items-baseline gap-3">
        <span className="mono-cap" style={{ fontSize: 12 }}>{n}</span>
        <span>{title}</span>
      </h2>
      <div className="space-y-3 text-[14px] t-84 leading-[1.65]">
        {children}
      </div>
    </section>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p>{children}</p>;
}

function Ul({ children }: { children: React.ReactNode }) {
  return <ul className="list-disc pl-5 space-y-1.5 marker:text-[var(--mint)]">{children}</ul>;
}

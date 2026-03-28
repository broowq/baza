import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";

export const metadata = {
  title: "Условия использования - БАЗА",
};

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-white px-4 sm:px-6 py-10 sm:py-16 dark:bg-[#111214]">
      <div className="mx-auto max-w-3xl">
        <Card className="border-0 bg-transparent shadow-none ring-0">
          <CardContent className="prose prose-gray max-w-none dark:prose-invert">
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#191C1F] dark:text-white">
              Условия использования
            </h1>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              Дата вступления в силу: 1 января 2026 г.
            </p>

            <p className="mt-6 leading-relaxed text-gray-600 dark:text-gray-300">
              Настоящие Условия использования (далее — Условия) регулируют
              порядок доступа и использования SaaS-платформы БАЗА (далее —
              Сервис). Используя Сервис, вы подтверждаете согласие с настоящими
              Условиями.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              1. Описание Сервиса
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              БАЗА — мультитенантная B2B-платформа для поиска, обогащения и
              управления коммерческими лидами. Сервис предоставляет инструменты
              для автоматического сбора контактных данных из открытых источников,
              скоринга, экспорта и командной работы.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              2. Обязанности пользователя
            </h2>
            <ul className="mt-4 list-disc space-y-2 pl-6 text-gray-600 dark:text-gray-300">
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
            </ul>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              3. Тарифы и оплата
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Стоимость подписки определяется выбранным тарифным планом. Оплата
              производится ежемесячно в рублях РФ. При отмене подписки доступ к
              платным функциям сохраняется до конца оплаченного периода.
              Возврат средств осуществляется в соответствии с законодательством
              РФ о защите прав потребителей.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              4. Данные и интеллектуальная собственность
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Данные, собранные вами через Сервис, принадлежат вашей
              организации. Мы не претендуем на права собственности на
              пользовательские данные. Программное обеспечение, дизайн и
              контент Сервиса являются интеллектуальной собственностью БАЗА.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              5. Ограничение ответственности
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Сервис предоставляется &laquo;как есть&raquo;. Мы не гарантируем
              бесперебойную работу и не несём ответственности за упущенную
              выгоду, потерю данных или косвенные убытки, возникшие в результате
              использования Сервиса. Максимальная ответственность ограничена
              суммой, оплаченной пользователем за последние 3 месяца.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              6. Прекращение использования
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Вы можете удалить учётную запись в любое время через настройки
              аккаунта. Мы оставляем за собой право приостановить или прекратить
              доступ к Сервису в случае нарушения настоящих Условий. При
              прекращении действия аккаунта данные удаляются в соответствии с
              Политикой конфиденциальности.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              7. Применимое право
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Настоящие Условия регулируются законодательством Российской
              Федерации. Все споры подлежат рассмотрению в суде по
              месту нахождения оператора Сервиса.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              8. Контакты
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              По вопросам, связанным с настоящими Условиями, обращайтесь:{" "}
              <a
                href="mailto:support@baza.io"
                className="text-[#191C1F] underline dark:text-white"
              >
                support@baza.io
              </a>
              .
            </p>

            <div className="mt-12 border-t border-gray-200 pt-6 dark:border-[#2A2C2F]">
              <Link
                href="/"
                className="text-sm text-gray-500 transition-colors hover:text-[#191C1F] dark:text-gray-400 dark:hover:text-white"
              >
                &larr; На главную
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}

import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";

export const metadata = {
  title: "Политика конфиденциальности - БАЗА",
};

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-white px-4 sm:px-6 py-10 sm:py-16 dark:bg-[#111214]">
      <div className="mx-auto max-w-3xl">
        <Card className="border-0 bg-transparent shadow-none ring-0">
          <CardContent className="prose prose-gray max-w-none dark:prose-invert">
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#191C1F] dark:text-white">
              Политика конфиденциальности
            </h1>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              Дата вступления в силу: 1 января 2026 г.
            </p>

            <p className="mt-6 leading-relaxed text-gray-600 dark:text-gray-300">
              Настоящая Политика конфиденциальности описывает порядок сбора,
              использования и защиты персональных данных пользователей сервиса
              БАЗА (далее — Сервис), разработанного и предоставляемого в
              соответствии с Федеральным законом от 27.07.2006 N 152-ФЗ
              &laquo;О персональных данных&raquo;.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              1. Какие данные мы собираем
            </h2>
            <ul className="mt-4 list-disc space-y-2 pl-6 text-gray-600 dark:text-gray-300">
              <li>
                <strong>Регистрационные данные:</strong> имя, адрес электронной
                почты, название организации, пароль (хранится в хешированном
                виде).
              </li>
              <li>
                <strong>Платёжные данные:</strong> информация об оплате
                обрабатывается через сертифицированного платёжного провайдера.
                Мы не храним данные банковских карт.
              </li>
              <li>
                <strong>Данные об использовании:</strong> IP-адрес, тип
                браузера, время визитов, действия в личном кабинете.
              </li>
              <li>
                <strong>Данные лидов:</strong> информация, собранная Сервисом в
                рамках ваших проектов, принадлежит вашей организации.
              </li>
            </ul>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              2. Как мы используем данные
            </h2>
            <ul className="mt-4 list-disc space-y-2 pl-6 text-gray-600 dark:text-gray-300">
              <li>Предоставление и поддержка функционала Сервиса.</li>
              <li>Обработка платежей и управление подписками.</li>
              <li>Отправка транзакционных уведомлений (подтверждение email, сброс пароля).</li>
              <li>Улучшение качества Сервиса и аналитика использования.</li>
              <li>Обеспечение безопасности и предотвращение мошенничества.</li>
            </ul>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              3. Файлы cookie
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Сервис использует файлы cookie для аутентификации (refresh-токен),
              хранения пользовательских предпочтений и аналитики. Вы можете
              управлять cookie через настройки браузера. Отключение обязательных
              cookie может привести к ограничению функционала.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              4. Хранение данных
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Персональные данные хранятся на серверах, расположенных на
              территории Российской Федерации, в течение всего срока действия
              вашей учётной записи. После удаления аккаунта данные удаляются в
              течение 30 дней, за исключением случаев, когда законодательство
              требует более длительного хранения. Резервные копии удаляются в
              течение 90 дней.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              5. Права пользователей (152-ФЗ)
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              В соответствии с Федеральным законом N 152-ФЗ вы имеете право:
            </p>
            <ul className="mt-4 list-disc space-y-2 pl-6 text-gray-600 dark:text-gray-300">
              <li>Получить информацию о хранимых персональных данных.</li>
              <li>Потребовать уточнения, блокирования или уничтожения данных.</li>
              <li>Отозвать согласие на обработку персональных данных.</li>
              <li>Обжаловать действия оператора в Роскомнадзор.</li>
            </ul>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Для реализации своих прав направьте запрос на{" "}
              <a
                href="mailto:support@baza.io"
                className="text-[#191C1F] underline dark:text-white"
              >
                support@baza.io
              </a>
              . Мы ответим в течение 10 рабочих дней.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              6. Передача данных третьим лицам
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              Мы не передаём персональные данные третьим лицам, за исключением
              случаев, предусмотренных законодательством РФ, а также
              обработчиков платежей и хостинг-провайдеров, действующих на
              основании договоров о конфиденциальности.
            </p>

            <h2 className="mt-10 text-xl font-semibold text-[#191C1F] dark:text-white">
              7. Контактная информация
            </h2>
            <p className="mt-4 leading-relaxed text-gray-600 dark:text-gray-300">
              По всем вопросам, связанным с обработкой персональных данных,
              обращайтесь по адресу:{" "}
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

# Yandex Search API v2 — подключение (замена мёртвого SearXNG)

Веб-поиск в БАЗЕ ищет сайты компаний, у которых нет карточки на Картах, чтобы
из них обогащением достать email. Прежний SearXNG на проде вернул мусор
(глобальные движки на RU-запросы отдают маркетплейсы, у Яндекс-движка капча).
Официальный **Yandex Search API v2** (Yandex Cloud) даёт RU-выдачу без капчи.

Код уже готов и включается **автоматически**, как только в
`/opt/baza/.env.production` появятся два ключа (иначе — тихий фолбэк на SearXNG).

## Что получить (5–10 минут, разово)

1. Зайти в консоль **Yandex Cloud**: <https://console.yandex.cloud>.
2. Убедиться, что есть **платёжный аккаунт** (Search API платный — копейки за
   1000 запросов; без привязанного платёжного аккаунта API не работает).
3. Найти **ID каталога** (folder): консоль → нужный каталог → в обзоре строка
   «Идентификатор» вида `b1g...`. Это `YANDEX_SEARCH_FOLDER_ID`.
4. Создать **сервисный аккаунт**: каталог → «Сервисные аккаунты» → создать,
   выдать роль `search-api.executor` (или `search-api.webSearch.user`).
5. Создать этому аккаунту **API-ключ**: сервисный аккаунт → «Создать новый
   ключ» → «API-ключ». Скопировать секрет — это `YANDEX_SEARCH_API_KEY`
   (показывается один раз).
6. В консоли включить сервис **Search API** для каталога (если попросит).

## Прописать на сервере

В `/opt/baza/.env.production` (секреты в репозиторий НЕ коммитятся) добавить:

```
YANDEX_SEARCH_API_KEY=<ключ из шага 5>
YANDEX_SEARCH_FOLDER_ID=<folder id из шага 3>
# необязательно: регион выдачи (пусто = вся Россия, что нам и нужно; 213 = Москва)
YANDEX_SEARCH_REGION=
```

Затем передеплоить: `cd /opt/baza && ./deploy.sh`.

## Проверить, что заработало (с сервера)

```
docker compose -f docker-compose.prod.yml exec -T backend python - <<'PY'
from app.core.config import get_settings
from app.services import lead_collection as lc
import httpx
s = get_settings()
print("configured:", lc._yandex_search_configured(s))
with httpx.Client() as c:
    items = lc._yandex_search_fetch_page(c, "пилорама Томск контакты", 1, s)
print("получено сайтов компаний:", len(items))
for it in items[:5]:
    print(" -", it["domain"], "|", it["company"][:40])
PY
```

Ждём непустой список **реальных сайтов компаний** (не ozon/avito/wikipedia —
их фильтр агрегаторов выбрасывает). Если пусто/ошибка — проверить ключ, роль
сервисного аккаунта и включённый платёжный аккаунт; код тем временем молча
работает через SearXNG (и пишет громкий WARNING в логи backend: «Yandex Search
настроен, но веб-проход вернул 0 сайтов»).

Заодно проверить **2-ю страницу** (пагинация 0-индексная — page=2 должен дать
ДРУГИЕ сайты, не дубли page=1): в скрипте заменить последний аргумент `1` на `2`
и сравнить домены. Это единственное, что нельзя было выверить без ключа.

## Как это устроено в коде

- `app/core/config.py` — поля `yandex_search_api_key`, `yandex_search_folder_id`,
  `yandex_search_region`, `yandex_search_timeout_seconds`.
- `app/services/lead_collection.py`:
  - `_yandex_search_configured()` — гейт по наличию ключа+folder;
  - `_yandex_search_fetch_page()` — POST `v2/web/search` (sync), декод base64-XML;
  - `_parse_yandex_search_xml()` — разбор схемы `yandexsearch>…>doc` в кандидатов
    (та же форма, что у SearXNG); агрегаторы отсекаются `is_aggregator_domain`;
  - веб-проход в `_search_leads_one_tier` использует Yandex Search при
    настроенном ключе, на ошибке API разово откатывается на SearXNG.
- Источник лида помечается `yandex_search` (в карточке — «Яндекс.Поиск»),
  вес источника 30 (надёжнее SearXNG-скрейпа 26).

Тесты: `backend/tests/test_yandex_search.py`, dispatcher — в
`backend/tests/test_lead_collection.py` (`test_web_pass_*`).

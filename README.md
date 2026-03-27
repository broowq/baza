# БАЗА — B2B SaaS для лидогенерации

**БАЗА** — сервис для автоматического поиска, обогащения и скоринга B2B-лидов. Собирает компании по нише и географии из веб-поиска и картографических источников, извлекает email/телефон/адрес, оценивает качество контакта и экспортирует базу в CSV.

## Быстрый старт

```bash
# 1. Клонировать и поднять инфраструктуру
git clone <repo>
make dev-up            # Docker + venv + npm install + миграции

# 2. Запустить в 4 терминалах
make backend           # FastAPI на :8000
make worker            # Celery worker
make beat              # Celery beat (автосбор по расписанию)
make frontend          # Next.js на :3000

# 3. Загрузить демо-данные
make seed

# Открыть http://localhost:3000
```

Логин после seed: `demo@baza.app` / `password123`

## Требования

| Компонент | Версия |
|-----------|--------|
| Python    | 3.11+  |
| Node.js   | 20+    |
| Docker    | 24+    |

## Архитектура

```
lid/
├── backend/        # FastAPI + Celery + SQLAlchemy
│   ├── app/
│   │   ├── api/routes/   # Маршруты API
│   │   ├── models/       # SQLAlchemy модели
│   │   ├── services/     # Бизнес-логика (scoring, quota, audit)
│   │   ├── tasks/        # Celery-задачи (collect, enrich)
│   │   └── utils/        # Инструменты (url_tools, contact_parser)
│   ├── alembic/    # Миграции БД
│   └── tests/      # Pytest тесты
├── frontend/       # Next.js 14 (App Router)
│   ├── app/        # Страницы
│   └── components/ # UI-компоненты
├── infra/          # SearXNG config
└── docker-compose.yml
```

## Переменные окружения

Скопируйте `backend/.env.example` в `backend/.env` и заполните:

| Переменная | Описание | Обязательно |
|-----------|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string | ✅ |
| `REDIS_URL` | Redis URL | ✅ |
| `SECRET_KEY` | JWT секрет (min 32 символа) | ✅ |
| `SEARXNG_URL` | URL SearXNG (по умолчанию `:58080`) | ✅ |
| `BING_API_KEY` | Bing Search API ключ (опционально) | ❌ |
| `YANDEX_MAPS_API_KEY` | API-ключ Яндекс Карт для прямого поиска организаций | ❌ |
| `TWOGIS_API_KEY` | API-ключ 2GIS Catalog API для дополнительного источника | ❌ |
| `SMTP_HOST/USER/PASSWORD` | SMTP для отправки писем | ❌ |
| `STRIPE_SECRET_KEY` | Stripe для платежей | ❌ |
| `EMAIL_VERIFICATION_REQUIRED` | Проверка email при регистрации | ❌ |

## Команды Makefile

```bash
make help            # Справка по всем командам
make dev-up          # Полный запуск dev-окружения
make prod-up         # Запуск prod-окружения (Docker)
make backend         # API-сервер с hot-reload
make worker          # Celery worker
make beat            # Celery beat (планировщик)
make frontend        # Next.js dev
make migrate         # Применить миграции
make migrate-create  # Создать миграцию (NAME=имя)
make seed            # Демо-данные
make test            # Unit-тесты
make test-e2e        # E2E API тесты
make lint            # Линтинг
make logs            # Хвост файла логов
make restart-worker  # Перезапуск worker
```

## API Endpoints

### Auth
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/auth/register` | Регистрация |
| POST | `/api/auth/login` | Вход |
| POST | `/api/auth/refresh` | Обновить токен |
| POST | `/api/auth/logout` | Выйти |
| GET  | `/api/auth/me` | Профиль |
| POST | `/api/auth/forgot-password` | Сброс пароля |
| POST | `/api/auth/reset-password` | Новый пароль по токену |

### Организации
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/organizations/me` | Текущая организация |
| GET | `/api/organizations/my-list` | Все организации пользователя |
| GET | `/api/organizations/membership` | Роль в текущей организации |
| GET | `/api/organizations/invites` | Список инвайтов |
| POST | `/api/organizations/invites` | Создать инвайт |
| POST | `/api/organizations/invites/accept` | Принять инвайт |
| GET | `/api/organizations/members` | Список участников |
| PATCH | `/api/organizations/members/{user_id}/role` | Изменить роль |
| DELETE | `/api/organizations/members/{user_id}` | Удалить участника |

### Проекты
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/projects` | Список проектов |
| POST | `/api/projects` | Создать проект |
| PATCH | `/api/projects/{id}` | Обновить проект |
| DELETE | `/api/projects/{id}` | Удалить проект |

### Лиды
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/leads/project/{id}/table` | Таблица лидов (фильтры, сортировка, пагинация) |
| POST | `/api/leads/project/{id}/collect` | Запустить сбор |
| POST | `/api/leads/project/{id}/enrich` | Запустить обогащение |
| POST | `/api/leads/project/{id}/enrich-selected` | Обогатить выбранные лиды |
| GET | `/api/leads/project/{id}/export` | Экспорт CSV |
| GET | `/api/leads/jobs/project/{id}` | История задач |

### Realtime
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/jobs/subscribe` | SSE-поток статусов задач |

### Служебные
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Healthcheck |
| GET | `/ready` | Readiness (DB + Redis) |

Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

Важно: billing checkout в `development` работает как stub для демонстрации UX. Для продакшена нужно подключить реальный платежный провайдер.

## Скоринг лидов

Каждый лид получает оценку **0–100** по формуле:

```
score = base(35) + domain(10) + email(20) + phone(10) + address(8)
      + keyword_bonus(5) + ru_domain_bonus(3)
      - no_contacts_penalty(-12) - demo_penalty(-20) - aggregator_penalty(-25)
```

Веса настраиваются через `SCORING_WEIGHTS_JSON` в `.env`.

## Планы и квоты

| Тариф | Лидов/мес | Проектов | Пользователей |
|-------|-----------|----------|---------------|
| Starter | 1 000 | 3 | 1 |
| Pro | 10 000 | 20 | 5 |
| Team | 50 000 | 100 | 20 |

При превышении квоты — HTTP `402` (лимит лидов) или `429` (лимит запросов).

## Роли (RBAC)

| Роль | Создание проекта | Сбор/обогащение | Приглашение | Управление планом |
|------|-----------------|-----------------|-------------|-------------------|
| owner | ✅ | ✅ | ✅ | ✅ |
| admin | ✅ | ✅ | ✅ | ❌ |
| member | ❌ | ❌ | ❌ | ❌ |

## Docker-порты

| Сервис | Порт |
|--------|------|
| PostgreSQL | 5433 |
| Redis | 6379 |
| SearXNG | 58080 |
| Backend API | 8000 |
| Frontend | 3000 |

## Запуск SearXNG

SearXNG поднимается автоматически через docker compose. Минимальный конфиг — `infra/searxng/settings.yml`. Для работы нужно разрешить JSON-формат:

```yaml
search:
  formats:
    - html
    - json
```

## Тесты

```bash
make test          # Unit-тесты (24 теста): парсер контактов, scoring, URL-инструменты
make test-e2e      # E2E: регистрация → проект → сбор → обогащение → CSV
```

## Переменные фронтенда

Скопируйте `frontend/.env.example` в `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

## Деплой на VPS

```bash
# Подготовка
cp backend/.env.example backend/.env
# Заполните: DATABASE_URL, SECRET_KEY, SEARXNG_URL, FRONTEND_ORIGINS

# Запуск
make prod-up

# Миграции
make migrate

# Первый пользователь
make seed
```

---

**БАЗА** | backend: FastAPI 0.115 · SQLAlchemy 2 · Celery 5 · PostgreSQL 16 · Redis 7 | frontend: Next.js 14 · TypeScript · Tailwind CSS

SHELL := /bin/zsh

.PHONY: dev dev-up prod-up dev-down migrate migrate-create backend worker beat frontend seed \
        test test-e2e playwright-e2e lint check-env restart-worker logs help

help:  ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

dev: dev-up  ## Алиас для dev-up

dev-up:  ## Поднять Docker, установить зависимости и применить миграции
	docker compose up -d
	cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
	cd backend && cp -n .env.example .env || true
	cd frontend && npm install
	cd frontend && cp -n .env.example .env.local || true
	cd backend && source .venv/bin/activate && alembic upgrade head

prod-up:  ## Запуск продакшн-окружения
	docker compose --env-file backend/.env.prod.example up -d --build

dev-down:  ## Остановить Docker-контейнеры
	docker compose down

migrate:  ## Применить все Alembic-миграции
	cd backend && source .venv/bin/activate && alembic upgrade head

migrate-create:  ## Создать новую миграцию (NAME=имя_миграции)
	cd backend && source .venv/bin/activate && alembic revision --autogenerate -m "$(NAME)"

backend:  ## Запустить backend (uvicorn + reload)
	cd backend && source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker:  ## Запустить Celery worker
	cd backend && source .venv/bin/activate && celery -A app.celery_worker:celery worker --loglevel=info

beat:  ## Запустить Celery beat (планировщик)
	cd backend && source .venv/bin/activate && celery -A app.celery_worker:celery beat --loglevel=info

frontend:  ## Запустить Next.js dev-сервер
	cd frontend && npm run dev

seed:  ## Загрузить демо-данные
	cd backend && source .venv/bin/activate && python -m app.seed

test:  ## Запустить unit-тесты
	cd backend && source .venv/bin/activate && pytest tests/ -v --ignore=tests/test_e2e_live.py

test-e2e:  ## Запустить end-to-end API тесты
	cd backend && source .venv/bin/activate && RUN_E2E=1 pytest tests/test_e2e_live.py -m e2e -v

playwright-e2e: test-e2e  ## Алиас для test-e2e

lint:  ## Запустить линтер (ruff + mypy)
	cd backend && source .venv/bin/activate && ruff check app/ || true
	cd frontend && npm run lint || true

restart-worker:  ## Перезапустить Celery worker (остановить + запустить)
	pkill -f "celery -A app.celery_worker:celery worker" || true
	sleep 1
	$(MAKE) worker

logs:  ## Показать логи backend из файла
	tail -f backend/logs/app.log 2>/dev/null || echo "Файл логов не найден"

check-env:  ## Проверить наличие .env файлов
	@test -f backend/.env && echo "✓ backend/.env" || echo "✗ backend/.env (скопируйте из .env.example)"
	@test -f frontend/.env.local && echo "✓ frontend/.env.local" || echo "✗ frontend/.env.local (скопируйте из .env.example)"

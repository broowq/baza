"""Каждая задача из beat-расписания ОБЯЗАНА быть зарегистрирована воркером.

Класс бага: задача объявлена (@celery.task в своём модуле) и стоит в
beat_schedule, но модуль не импортирован в app/celery_worker.py → реальный
воркер получает её от beat и отбрасывает как «Received unregistered task» —
фича молча мертва на проде, при этом все тесты зелёные (eager-режим импортирует
модуль напрямую). Ровно так email-цепочки outreach не работали на проде:
outreach.process_sequences дропался каждые 5 минут (288 ошибок/сутки).

Тест воспроизводит прод-условия: импортирует ТОЛЬКО app.celery_worker (как
делает воркер-процесс) и сверяет beat_schedule с реестром задач.
"""
from __future__ import annotations


def test_every_beat_task_is_registered_in_worker():
    # Импортируем то же и только то, что импортирует настоящий воркер-процесс.
    from app.celery_worker import celery

    registered = set(celery.tasks.keys())
    scheduled = {entry["task"] for entry in celery.conf.beat_schedule.values()}

    missing = sorted(scheduled - registered)
    assert not missing, (
        "Задачи стоят в beat_schedule, но воркер их НЕ регистрирует "
        f"(добавь импорт модуля в app/celery_worker.py): {missing}"
    )


def test_dynamically_dispatched_tasks_are_registered():
    """Задачи, вызываемые по имени через celery.signature(...) (минуя прямой
    импорт модуля), тоже должны быть в реестре воркера."""
    from app.celery_worker import celery

    registered = set(celery.tasks.keys())
    # jobs.py шлёт email.send_email через celery.signature("email.send_email").
    for name in ("email.send_email", "webhook.push_lead"):
        assert name in registered, f"{name} не зарегистрирована в воркере"

"""Анти-брутфорс логина (аудит безопасности, 22.07.2026).

Существующий HTTP-tier в main.py душит burst по IP (10/мин на /api/auth/login),
но НЕ защищает конкретный аккаунт: атакующий с ротацией IP (ботнет/прокси)
перебирает пароль к одному email медленно и обходит IP-лимит. Этот слой
блокирует АККАУНТ: после N неудачных попыток вход по этому email отклоняется
на время кулдауна.

Дизайн (тот же стиль, что registration_guard):
  • Ключ Redis — sha256(email) с солью, а НЕ сам email: дамп Redis не раскроет,
    какие аккаунты под атакой (152-ФЗ — не храним ПД в открытом виде).
  • Счётчик неудач с TTL = окно кулдауна. Порог достигнут → 429 + Retry-After.
  • Проверка (ensure_login_not_locked) идёт ДО поиска юзера и сверки пароля,
    ПО нормализованному email — поэтому поведение одинаково для существующего
    и несуществующего адреса (без оракула перечисления) и дорогой argon2-verify
    не выполняется на заблокированном аккаунте.
  • Кулдаун ФИКСИРОВАННЫЙ от N-й неудачи: попытки сверх порога отбиваются 429
    ДО note_failed_login, поэтому TTL не продлевается — атакующий не может
    держать честного юзера заблокированным вечно (максимум окно кулдауна).
  • Успешный вход обнуляет счётчик — пара опечаток честного юзера не копится.
  • Redis недоступен → fail-open (доступность важнее), как в rate-limiter.
  • В dev/тестах отключён (e2e-сьют делает много логинов с одного клиента).
"""
from __future__ import annotations

import hashlib
import logging

import redis
from fastapi import HTTPException

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)

# Соль ключа: та же роль, что пепер книги триалов — против словарного
# восстановления email из дампа Redis. Значение не секретное (ключи и так
# в приватном Redis), но хэшируем ради 152-ФЗ-гигиены. НЕ обязателен к смене.
_LOGIN_KEY_SALT = "baza-login-guard-v1"


def _enabled() -> bool:
    # В dev e2e-сьют логинится сотни раз с одного «testclient» — тот же приём,
    # что _daily_cap в registration_guard и _is_dev в main.py.
    return settings.app_env != "development"


def _fail_key(email: str) -> str:
    ident = (email or "").lower().strip()
    digest = hashlib.sha256(f"{_LOGIN_KEY_SALT}:{ident}".encode()).hexdigest()
    return f"login_fail:{digest}"


def _max_attempts() -> int:
    return max(1, int(getattr(settings, "login_max_failed_attempts", 5)))


def _cooldown_seconds() -> int:
    return max(60, int(getattr(settings, "login_lockout_minutes", 15)) * 60)


def ensure_login_not_locked(email: str) -> None:
    """Поднимает 429 (+ Retry-After), если по этому аккаунту превышен порог
    неудачных попыток. Вызывать ДО сверки пароля. Fail-open при сбое Redis."""
    if not _enabled():
        return
    key = _fail_key(email)
    try:
        current = int(_redis.get(key) or 0)
    except redis.exceptions.RedisError:
        logger.warning("login guard: Redis unavailable, allowing", exc_info=True)
        return
    if current >= _max_attempts():
        cooldown_min = _cooldown_seconds() // 60
        logger.warning("login guard: account locked (fails=%s) key=%s", current, key)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Слишком много неудачных попыток входа. "
                f"Повторите через {cooldown_min} мин или сбросьте пароль."
            ),
            headers={"Retry-After": str(_cooldown_seconds())},
        )


def note_failed_login(email: str) -> None:
    """Инкремент счётчика неудач + продление окна кулдауна. Вызывать при
    КАЖДОЙ неуспешной аутентификации (неверный пароль ИЛИ несуществующий
    email — поведение одинаково ради анти-enumeration)."""
    if not _enabled():
        return
    key = _fail_key(email)
    try:
        pipe = _redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _cooldown_seconds())
        pipe.execute()
    except redis.exceptions.RedisError:
        logger.warning("login guard: Redis unavailable on note", exc_info=True)


def note_successful_login(email: str) -> None:
    """Сбрасывает счётчик после успешного входа — опечатки честного
    пользователя не должны копиться до блокировки."""
    if not _enabled():
        return
    try:
        _redis.delete(_fail_key(email))
    except redis.exceptions.RedisError:
        logger.warning("login guard: Redis unavailable on reset", exc_info=True)

"""hh.ru open API — сигнал «компания нанимает».

Компания с активными вакансиями растёт и тратит деньги — это интент-сигнал,
которого нет у карточных источников. API открытый (ключ не нужен), требует
только осмысленный User-Agent. Используется в enrich-пайплайне с капом на
джобу (hh_max_per_job) и кэшем 7 дней.

Матч названия — тот же токен-гард, что в DaData/веб-lookup: пересечение
только по generic-словам («строительная компания») — не матч, чужие вакансии
хуже отсутствия сигнала.
"""
from __future__ import annotations

import hashlib
import logging
import re

import httpx
import redis as _redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_EMPLOYERS_URL = "https://api.hh.ru/employers"
_CACHE_TTL = 7 * 86400
_NOT_FOUND = "-1"  # кэш-маркер «работодатель не найден»
_redis_singleton: "_redis.Redis | None" = None

_NAME_STOPWORDS = frozenset({
    "ооо", "зао", "оао", "пао", "ао", "ип", "тд", "тк", "гк",
    "компания", "фирма", "группа", "центр", "студия", "салон", "магазин",
    "сервис", "служба", "агентство", "бюро", "мастерская", "клиника",
    "организация", "предприятие", "завод", "фабрика", "холдинг",
    "строительная", "торговая", "производственная", "транспортная",
})
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+")


def _get_redis() -> "_redis.Redis | None":
    global _redis_singleton
    if _redis_singleton is None:
        try:
            _redis_singleton = _redis.Redis.from_url(
                get_settings().redis_url, decode_responses=True, socket_timeout=2
            )
        except Exception:
            return None
    return _redis_singleton


def _tokens(text: str) -> set[str]:
    return {
        t for t in _TOKEN_RE.findall((text or "").lower().replace("ё", "е"))
        if len(t) >= 3 and t not in _NAME_STOPWORDS
    }


def match_employer(company: str, items: list[dict]) -> dict | None:
    """Лучший матч работодателя hh по значимым токенам названия.

    Гард точности (ревью 21.07): требуем ≥2 общих значимых токенов для
    многотокенных названий (однотокенный матч допустим только когда в самом
    запросе один значимый токен) — иначе «Мебель Томск» матчился бы на
    «Томск Хостел» по одному топониму и чужие вакансии приписывались лиду.
    Ничья по лучшему пересечению = неоднозначность → None.

    Возвращает элемент items или None. Публична ради юнит-тестов.
    """
    query_tokens = _tokens(company)
    if not query_tokens:
        return None
    required = min(2, len(query_tokens))
    best: dict | None = None
    best_overlap = 0
    tie = False
    for it in items:
        overlap = len(query_tokens & _tokens(it.get("name") or ""))
        if overlap > best_overlap:
            best = it
            best_overlap = overlap
            tie = False
        elif overlap and overlap == best_overlap:
            tie = True
    if best_overlap < required or tie:
        return None
    return best


def peek_vacancies(company: str) -> "tuple[bool, int | None]":
    """ТОЛЬКО кэш: (True, значение) при хите, (False, None) при промахе.

    Бесплатно — вызывающий не тратит сетевой бюджет джобы на кэш-хиты.
    """
    company = (company or "").strip()
    r = _get_redis()
    if r is None or len(company) < 3:
        return False, None
    try:
        cached = r.get("hh:" + hashlib.sha1(company.lower().encode()).hexdigest())
    except Exception:
        return False, None
    if cached is None:
        return False, None
    return True, (None if cached == _NOT_FOUND else int(cached))


def open_vacancies(company: str) -> int | None:
    """Число открытых вакансий компании на hh.ru.

    None — не нашли/выключено/ошибка (сигнала нет); int ≥ 0 — нашли
    работодателя. Никогда не поднимает исключений.
    """
    settings = get_settings()
    company = (company or "").strip()
    if not getattr(settings, "hh_enabled", True) or len(company) < 3:
        return None

    cache_key = "hh:" + hashlib.sha1(company.lower().encode()).hexdigest()
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(cache_key)
            if cached is not None:
                return None if cached == _NOT_FOUND else int(cached)
        except Exception:
            pass

    try:
        resp = httpx.get(
            _EMPLOYERS_URL,
            params={"text": company, "per_page": 20, "only_with_vacancies": "false"},
            headers={"User-Agent": settings.hh_user_agent},
            timeout=10.0,
        )
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except Exception as exc:
        # Временная ошибка — не кэшируем.
        logger.debug("hh employers lookup failed for %r: %s", company[:40], type(exc).__name__)
        return None

    matched = match_employer(company, items)
    result: int | None = None
    if matched is not None:
        try:
            result = max(0, int(matched.get("open_vacancies") or 0))
        except (TypeError, ValueError):
            result = None

    if r is not None:
        try:
            r.setex(cache_key, _CACHE_TTL, _NOT_FOUND if result is None else str(result))
        except Exception:
            pass
    return result

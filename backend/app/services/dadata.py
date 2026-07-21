"""DaData Suggestions API — ЕГРЮЛ-справка по названию компании.

Зачем: до 21.07.2026 колонка Company.inn существовала, но НИ ОДИН источник её
не заполнял (2GIS/Yandex/Rusprofile не отдают ИНН), а статус юрлица мы не знали
вовсе — клиенту могла уйти ликвидированная компания, и никто бы не заметил.

DaData `suggest/party` по названию (+ городу) возвращает ИНН, статус
(ACTIVE/LIQUIDATED/…), основной ОКВЭД и дату регистрации. Бесплатный тариф —
10k запросов/сутки, ключ в env DADATA_API_KEY (пусто = сервис выключен).

Гарантии точности (тот же принцип, что в yandex_search_company_lookup):
  * матч названия — по значимым токенам (ООО/«компания»/отраслевые
    generic-слова не считаются); пересечение только по generic — НЕ матч;
  * если задан город — адрес ЕГРЮЛ обязан его содержать: чужой ИНН из
    другого региона хуже пустого;
  * два разных ИНН с равным матчем — неоднозначность, возвращаем {}.

Кэш Redis 30 дней, включая отрицательные вердикты (запрос платный по квоте).
"""
from __future__ import annotations

import hashlib
import json as _json
import logging
import re
from datetime import datetime, timezone

import httpx
import redis as _redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"
_CACHE_TTL = 30 * 86400
_redis_singleton: "_redis.Redis | None" = None

# Организационно-правовые формы и generic-слова названий: пересечение ТОЛЬКО
# по ним — не матч (см. _LOOKUP_STOPWORDS в lead_collection — тот же принцип).
_NAME_STOPWORDS = frozenset({
    "ооо", "зао", "оао", "пао", "ао", "ип", "тд", "тк", "гк", "нпо", "пкф",
    "нко", "анo", "ано", "фгуп", "гуп", "муп",
    "компания", "фирма", "группа", "центр", "студия", "салон", "магазин",
    "сервис", "служба", "агентство", "бюро", "мастерская", "клиника",
    "организация", "предприятие", "завод", "фабрика", "холдинг",
    "строительная", "торговая", "производственная", "транспортная",
    "юридическая", "медицинская", "туристическая", "рекламная", "оптовая",
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


def is_configured() -> bool:
    return bool((get_settings().dadata_api_key or "").strip())


def _parse_registration(ms: object) -> datetime | None:
    """DaData отдаёт дату регистрации в миллисекундах epoch."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


# Слова-обёртки гео-названий: для сравнения city лида с адресом ЕГРЮЛ они
# только мешают («Московская область» vs «Московская обл» в адресе DaData).
_GEO_WRAPPER_WORDS = frozenset({
    "область", "обл", "край", "республика", "респ", "город", "г", "гор",
    "округ", "ао", "автономный", "автономная", "район", "р-н", "пос",
    "посёлок", "поселок", "село", "деревня",
})


def _geo_core_tokens(city: str) -> list[str]:
    """Значимое ядро гео-строки: «Московская область» → ["московская"]."""
    return [
        t for t in _TOKEN_RE.findall((city or "").lower().replace("ё", "е"))
        if len(t) >= 3 and t not in _GEO_WRAPPER_WORDS
    ]


def _cache_key_for(name: str, city: str) -> str:
    return "dadata:" + hashlib.sha1(
        f"{name.lower()}|{(city or '').lower()}".encode()
    ).hexdigest()


def _decode_cached(raw: str) -> dict:
    got = _json.loads(raw)
    if got.get("registered_at"):
        try:
            got["registered_at"] = datetime.fromisoformat(got["registered_at"])
        except (TypeError, ValueError):
            got["registered_at"] = None
    return got


def peek_party(name: str, city: str = "") -> "dict | None":
    """ТОЛЬКО кэш: dict (включая пустой {}) при хите, None при промахе.

    Бесплатно — вызывающий не должен тратить сетевой бюджет на кэш-хиты
    (ревью 21.07: бюджет джобы сгорал на хитах, хвост лидов не обогащался).
    """
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(_cache_key_for((name or "").strip(), city))
        return _decode_cached(raw) if raw is not None else None
    except Exception:
        return None


def find_party(name: str, city: str = "") -> dict:
    """ЕГРЮЛ-справка по названию: {"inn", "status", "okved", "registered_at",
    "address", "full_name"} или {} (не найдено / неоднозначно / не настроено).

    registered_at — naive-UTC datetime или None. Никогда не поднимает исключений.
    """
    settings = get_settings()
    key = (settings.dadata_api_key or "").strip()
    name = (name or "").strip()
    if not key or len(name) < 3:
        return {}

    query_tokens = _tokens(name)
    if not query_tokens:
        # Название целиком из generic-слов («Торговая компания») — матч по нему
        # даст случайный ИНН случайного тёзки.
        return {}

    cache_key = _cache_key_for(name, city)
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(cache_key)
            if cached is not None:
                return _decode_cached(cached)
        except Exception:
            pass

    try:
        resp = httpx.post(
            _SUGGEST_URL,
            # type=LEGAL: ИП не запрашиваем вовсе — ИНН ИП является ПД
            # физлица; ограничиваемся юрлицами (ЕГРЮЛ), ревью 21.07.
            json={"query": name, "count": 8, "branch_type": ["MAIN"], "type": "LEGAL"},
            headers={
                "Authorization": f"Token {key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        suggestions = (resp.json() or {}).get("suggestions") or []
    except Exception as exc:
        # Временная ошибка — НЕ кэшируем, следующий enrich попробует снова.
        logger.warning("dadata find_party failed for %r: %s", name[:40], type(exc).__name__)
        return {}

    # Гео-гард по ЯДРУ названия («Московская область» → «московская»): DaData
    # сокращает обёртки в адресе («Московская обл»), substring по полной строке
    # ложно отбрасывал матчи (ревью 21.07).
    city_core = _geo_core_tokens(city)
    matches: list[dict] = []
    for s in suggestions:
        data = s.get("data") or {}
        if (data.get("type") or "") == "INDIVIDUAL":
            # Защита в глубину поверх type=LEGAL в запросе: ИНН ИП — ПД
            # физлица, не берём и не кэшируем.
            continue
        sug_name = " ".join(
            str(x) for x in (
                s.get("value") or "",
                ((data.get("name") or {}).get("full") or ""),
            )
        )
        if not (query_tokens & _tokens(sug_name)):
            continue
        address = ((data.get("address") or {}).get("value") or "").lower().replace("ё", "е")
        if city_core and not all(tok in address for tok in city_core):
            # Город задан, а адрес ЕГРЮЛ его не содержит — вероятно, тёзка из
            # другого региона. Чужой ИНН хуже пустого.
            continue
        matches.append(s)

    result: dict = {}
    if matches:
        # Среди матчей предпочитаем действующее юрлицо (ликвидированный тёзка
        # часто висит в реестре рядом с новым действующим).
        def _status(s: dict) -> str:
            return (((s.get("data") or {}).get("state") or {}).get("status") or "")

        active = [s for s in matches if _status(s) == "ACTIVE"]
        pool = active or matches
        # Без гео-подтверждения (city пуст) «смертный приговор» не выносим:
        # ошибочный матч тёзки навсегда пометил бы живую компанию
        # ликвидированной (ревью 21.07). Живой статус без города — ок.
        if not city_core and not active:
            pool = []
        inns = {((s.get("data") or {}).get("inn") or "") for s in pool}
        inns.discard("")
        if len(inns) == 1:
            best = pool[0]
            data = best.get("data") or {}
            result = {
                "inn": (data.get("inn") or "")[:20],
                "status": _status(best)[:20],
                "okved": (data.get("okved") or "")[:160],
                "registered_at": _parse_registration(
                    ((data.get("state") or {}).get("registration_date"))
                ),
                "address": ((data.get("address") or {}).get("value") or "")[:400],
                "full_name": (((data.get("name") or {}).get("short_with_opf"))
                              or best.get("value") or "")[:255],
            }
        # len(inns) > 1 → неоднозначно, result остаётся {}

    if r is not None:
        try:
            to_cache = dict(result)
            if isinstance(to_cache.get("registered_at"), datetime):
                to_cache["registered_at"] = to_cache["registered_at"].isoformat()
            r.setex(cache_key, _CACHE_TTL, _json.dumps(to_cache, ensure_ascii=False))
        except Exception:
            pass
    return result

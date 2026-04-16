import functools
import hashlib
import json as _json
import random
import time
from html import unescape
import logging
import re
from urllib.parse import quote_plus, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import pymorphy3
import redis

_morph = pymorphy3.MorphAnalyzer()

from app.core.config import get_settings
from app.utils.contact_parser import extract_contacts
from app.utils.url_tools import _is_safe_url, extract_domain, get_base_domain, is_aggregator_domain, is_junk_result, is_real_domain, normalize_url

# ─── Redis cache for 2GIS API ───────────────────────────────────────────────
# Caches raw API responses to avoid burning quota on repeated queries.
# Same "стоматология Казань" from two different users → 1 API call, not 2.
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
_CACHE_PREFIX = "2gis:v1:"

def _get_redis() -> redis.Redis | None:
    """Lazy Redis connection for caching (sync, uses DB 3 to avoid collisions)."""
    try:
        url = get_settings().redis_url  # e.g. redis://localhost:6379/0
        # Use DB 3 for 2GIS cache (0=app, 1=celery broker, 2=celery results)
        base = url.rsplit("/", 1)[0] if "/" in url else url
        return redis.Redis.from_url(f"{base}/3", decode_responses=True, socket_timeout=2)
    except Exception:
        return None


def _cache_key(prefix: str, *parts: str) -> str:
    """Build a stable cache key from arbitrary parts."""
    raw = "|".join(str(p).lower().strip() for p in parts)
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{_CACHE_PREFIX}{prefix}:{digest}"

DEFAULT_USER_AGENT = "BAZA-Bot/1.0 (+https://localhost)"
TAG_RE = re.compile(r"<[^>]+>")
logger = logging.getLogger("baza.lead_collection")

_YANDEX_SEARCH_URL = "https://search-maps.yandex.ru/v1/"
_MIN_RELEVANCE_SCORE = 26

_REJECT_TITLE_WORDS = [
    "википедия", "wikipedia", "погода", "weather", "форум",
    "рецепт", "скачать", "смотреть онлайн", "сериал", "фильм",
    "расписание поездов", "расписание автобусов", "lyrics",
    "значение слова", "толковый словарь", "энциклопедия",
    "рейтинг", "лучших", "лучшие", "лучший", "топ-10", "топ 10",
    "подборка", "обзор", "сравнение", "отзывы", "список компаний",
    "каталог компаний", "каталог фирм", "адреса и телефоны",
]

_REJECT_DOMAIN_PARTS = [
    "wiki", "forum", "blog", "news", "weather", "pogoda",
    "otvet", "answers", "slovar", "review", "rating",
]

_EDITORIAL_OR_DIRECTORY_DOMAINS = {
    "kp.ru",
    "markakachestva.ru",
    "oknatrade.ru",
    "pravda.ru",
    "dzen.ru",
    "vc.ru",
    "pikabu.ru",
}

_ARTICLE_OR_DIRECTORY_HINTS = [
    "рейтинг", "лучших", "лучшие", "лучший", "топ 10", "топ-10",
    "отзывы", "обзор", "сравнение", "подборка", "список компаний",
    "каталог компаний", "каталог фирм", "справочник", "адреса и телефоны",
]

_PATH_DIRECTORY_HINTS = [
    "/rating",
    "/ratings",
    "/review",
    "/reviews",
    "/otzyv",
    "/otzyvy",
    "/companies",
    "/company",
    "/catalog",
    "/luchshie",
    "/best",
    "/top",
    "/news",
    "/news/",
    "/sitemap",
    "/map",
    "/stars/",
    "/afisha",
    "/tag/",
    "/tags/",
    "/category/",
    "/articles/",
    "/article/",
    "/blog/",
]

# File extensions that indicate not-a-lead (documents, downloads)
_REJECT_URL_EXTENSIONS = (".xls", ".xlsx", ".pdf", ".doc", ".docx", ".zip", ".rar", ".xml")

_BIZ_SIGNAL_WORDS = [
    "купить", "заказать", "доставка", "прайс", "цена", "стоимость",
    "ооо", "оао", "зао", "ип ", "компания", "предприятие",
    "производств", "магазин", "услуг", "оптом", "каталог",
    "склад", "оборудован", "продаж", "аренд", "монтаж",
    "ремонт", "строительств", "поставщик", "подрядчик",
    "прайс-лист", "распродаж", "акция", "скидк",
    "официальный сайт", "официальный дилер",
    "звоните", "наш адрес", "контакты", "телефон:",
    "+7", "8 (", "info@", "sale@", "zakaz@",
]

_ALLOWED_TLDS = frozenset({
    "ru", "com", "net", "org", "su", "by", "kz", "ua", "uz", "kg", "am", "ge", "az",
    "info", "biz", "pro", "company", "online", "site", "clinic",
    "xn--p1ai",  # .рф
    "xn--p1acf",  # .рус
})

_SUSPICIOUS_RU_MARKET_TLDS = frozenset({
    "aw", "bh", "bj", "bm", "bn", "cw", "iq", "km", "mz", "ne", "ps", "tm", "vc", "wf", "zw",
})

_SOURCE_WEIGHTS = {
    "yandex_maps": 64,
    "2gis": 52,
    "maps_searxng": 40,
    "searxng": 26,
    "bing": 20,
}

_NEGATIVE_KEYWORDS = (
    "-wikipedia -википедия -погода -форум -блог -рецепт -словарь "
    "-реферат -скачать -рейтинг -лучшие -лучших -топ -обзор -отзывы -сравнение -список "
    "-вакансия -вакансии -работа -резюме -hh.ru -superjob "
    "-ликвидирован -ликвидация -банкрот -inn -огрн "
    "-sravni.ru -e-ecolog.ru -rusprofile.ru -list-org.com "
    "-продажа -купить -заказать -интернет-магазин "
    "-поставщик -дистрибьютор -оптовик "
    "-прайс-лист -каталог-товаров"
)

# Signals that a candidate is a SELLER/competitor, not a buyer/customer
_COMPETITOR_SIGNALS = [
    "продажа", "продаж", "продаём", "продаем", "продают",
    "купить", "заказать", "закажите", "оформить заказ",
    "магазин", "интернет-магазин", "маркетплейс",
    "поставщик", "дистрибьютор", "оптом", "оптовик",
    "производител", "изготовител", "собственное производство",
    "прайс", "каталог товаров", "ассортимент", "в наличии",
    "доставка по", "бесплатная доставка", "самовывоз",
    "скидк", "акци", "распродаж",
]


def _normalize_match_text(value: str) -> str:
    text = unescape(value or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def _build_match_terms(*parts: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for part in parts:
        normalized = _normalize_match_text(part)
        for token in re.findall(r"[a-zа-я0-9]+", normalized):
            if len(token) < 3:
                continue
            if token not in seen:
                seen.add(token)
                terms.append(token)
            # Get normal form (lemma) via pymorphy3
            parsed = _morph.parse(token)
            if parsed:
                lemma = parsed[0].normal_form.replace("ё", "е")
                if lemma not in seen:
                    seen.add(lemma)
                    terms.append(lemma)
                # Also add the stem (first 4 chars of lemma) for partial matching
                if len(lemma) >= 5:
                    stem = lemma[:4]
                    if stem not in seen:
                        seen.add(stem)
                        terms.append(stem)
    return terms


def _keyword_hits(text: str, terms: list[str]) -> int:
    normalized = _normalize_match_text(text)
    return sum(1 for term in terms if re.search(rf"(?<![а-яёa-z]){re.escape(term)}", normalized))


def _extract_tld(domain: str) -> str:
    parts = [part for part in (domain or "").lower().split(".") if part]
    return parts[-1] if parts else ""


def _looks_russian_market_geo(geography: str) -> bool:
    normalized = _normalize_match_text(geography)
    return bool(re.search(r"[а-я]", normalized)) or normalized in {"russia", "moscow", "saint petersburg"}


def _is_candidate_domain_allowed(domain: str, geography: str, source: str) -> bool:
    tld = _extract_tld(domain)
    if not tld or tld not in _ALLOWED_TLDS:
        return False
    if source in {"yandex_maps", "2gis"}:
        return True
    if _looks_russian_market_geo(geography) and tld in _SUSPICIOUS_RU_MARKET_TLDS:
        return False
    return True


def _strip_reference_terms(text: str, *parts: str) -> str:
    normalized = _normalize_match_text(text)
    for part in parts:
        normalized_part = _normalize_match_text(part)
        if not normalized_part:
            continue
        normalized = normalized.replace(normalized_part, " ")
        for token in re.findall(r"[a-zа-я0-9]+", normalized_part):
            if len(token) < 4:
                continue
            normalized = re.sub(rf"\b{re.escape(token)}\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _looks_synthetic_result(item: dict, niche: str, geography: str, segments: list[str] | None = None) -> bool:
    if item.get("source") in {"yandex_maps", "2gis", "maps_searxng"}:
        return False

    stripped = _strip_reference_terms(
        " ".join(filter(None, [item.get("company", ""), item.get("snippet", "")])),
        niche,
        geography,
        *(segments or []),
    )
    if not stripped:
        return False

    lowered = stripped.lower()
    latin_tokens = re.findall(r"\b[a-z]{4,}\b", lowered)
    cyrillic_tokens = re.findall(r"\b[а-я]{4,}\b", lowered)
    has_contact = bool(
        re.search(r"\+7[\s\-(]?\d", lowered)
        or re.search(r"[a-z0-9_.+-]+@[a-z0-9-]+\.[a-z]{2,}", lowered)
    )
    has_business_signal = any(word in lowered for word in _BIZ_SIGNAL_WORDS)
    unique_latin = {token for token in latin_tokens if len(token) >= 5}

    return len(unique_latin) >= 6 and not cyrillic_tokens and not has_contact and not has_business_signal


def _looks_like_article_or_directory(item: dict) -> bool:
    if item.get("source") in {"yandex_maps", "2gis", "maps_searxng"}:
        return False

    text = _normalize_match_text(
        " ".join(
            filter(
                None,
                [
                    item.get("company", ""),
                    item.get("snippet", ""),
                    item.get("source_url", ""),
                ],
            )
        )
    )
    source_url = item.get("source_url", "")
    source_domain = extract_domain(source_url)
    source_path = urlparse(source_url).path.lower()

    if source_domain in _EDITORIAL_OR_DIRECTORY_DOMAINS:
        return True
    if any(hint in text for hint in _ARTICLE_OR_DIRECTORY_HINTS):
        return True
    if any(hint in source_path for hint in _PATH_DIRECTORY_HINTS) and "официальный сайт" not in text:
        return True
    # Reject file download URLs (.xls/.pdf/.doc/etc)
    if any(source_path.endswith(ext) for ext in _REJECT_URL_EXTENSIONS):
        return True
    return False


def _candidate_relevance_score(
    item: dict,
    niche: str,
    geography: str = "",
    segments: list[str] | None = None,
) -> int:
    domain = (item.get("domain") or extract_domain(item.get("website", ""))).lower()
    source = item.get("source", "searxng")
    is_maps_source = source in {"yandex_maps", "2gis"}

    # For web sources (SearXNG, Bing) — domain is required (it's a web result after all)
    # For maps sources (2GIS, Yandex) — allow results WITHOUT domain if they have company + (address OR phone)
    # Real B2B customers (farms, small clinics) often don't have websites
    if not domain:
        if not is_maps_source:
            return -999
        # Maps result without website — require company name + (address or phone) as minimum viable lead
        if not item.get("company") or (not item.get("address") and not item.get("phone")):
            return -999
    elif not is_real_domain(domain) or is_aggregator_domain(domain):
        return -999
    elif not _is_candidate_domain_allowed(domain, geography, source):
        return -999

    company = _normalize_match_text(item.get("company", ""))
    snippet = _normalize_match_text(item.get("snippet", ""))
    address = _normalize_match_text(item.get("address", ""))
    categories = _normalize_match_text(" ".join(item.get("categories") or []))
    source_url = item.get("source_url", "")
    source_domain = extract_domain(source_url)
    combined = " ".join(filter(None, [company, snippet, address, categories, domain, source_domain]))

    score = _SOURCE_WEIGHTS.get(source, 10)
    if item.get("website"):
        score += 8
    else:
        score -= 8  # Soft penalty — many real B2B customers don't have websites

    if _looks_like_article_or_directory(item):
        score -= 120
    if any(word in combined for word in _REJECT_TITLE_WORDS):
        score -= 35
    if any(part in domain for part in _REJECT_DOMAIN_PARTS):
        score -= 25
    biz_hits = sum(1 for word in _BIZ_SIGNAL_WORDS if word in combined)
    if biz_hits:
        score += 10
    if _looks_synthetic_result(item, niche, geography, segments):
        score -= 160

    niche_phrase = _normalize_match_text(niche)
    niche_terms = _build_match_terms(niche, *(segments or []))
    title_hits = _keyword_hits(f"{company} {domain}", niche_terms)
    context_hits = _keyword_hits(f"{snippet} {address} {categories}", niche_terms)

    if niche_phrase and niche_phrase in combined:
        score += 28
    score += min(30, title_hits * 8 + context_hits * 3)
    if niche_terms and title_hits + context_hits == 0:
        score -= 24
    elif niche_terms and title_hits == 0:
        score -= 8

    # Segment matching — bonus for matching target customer type
    if segments:
        seg_terms = set()
        for seg in (segments or []):
            for word in seg.lower().replace("ё", "е").split():
                if len(word) >= 3:
                    seg_terms.add(word)
        seg_hits = sum(1 for term in seg_terms if term in combined)
        score += min(20, seg_hits * 6)

    # Competitor detection — penalty for seller signals
    competitor_hits = sum(1 for word in _COMPETITOR_SIGNALS if word in combined)
    if competitor_hits >= 2:
        score -= 30

    geo_terms = _build_match_terms(geography)
    city_text = _normalize_match_text(item.get("city", ""))
    geo_search_text = f"{company} {snippet} {address} {city_text}"
    geo_hits = _keyword_hits(geo_search_text, geo_terms)
    score += min(14, geo_hits * 5)
    if geography and geo_hits == 0:
        if source not in {"yandex_maps", "2gis"}:
            score -= 30
        else:
            score -= 3  # Maps are already geo-constrained by bbox/city_id

    if source in {"yandex_maps", "2gis"}:
        if address:
            score += 10
        if categories:
            score += 8

    contact_text = f"{snippet} {address}"
    if re.search(r"\+7[\s\-(]?\d", contact_text) or re.search(r"8\s?\(\d{3}\)", contact_text):
        score += 4
    if re.search(r"[a-z0-9_.+-]+@[a-z0-9-]+\.[a-z]{2,}", contact_text):
        score += 4

    credibility_markers = 0
    if title_hits:
        credibility_markers += 1
    if context_hits:
        credibility_markers += 1
    if geo_hits:
        credibility_markers += 1
    if address or categories:
        credibility_markers += 1
    if biz_hits:
        credibility_markers += 1
    if re.search(r"\+7[\s\-(]?\d", contact_text) or re.search(r"[a-z0-9_.+-]+@[a-z0-9-]+\.[a-z]{2,}", contact_text):
        credibility_markers += 1
    if source in {"searxng", "bing"} and credibility_markers < 2:
        score -= 24

    if len(company.split()) > 12:
        score -= 10

    return score


def _score_candidate(item: dict, niche: str, geography: str, segments: list[str] | None = None) -> dict:
    scored = dict(item)
    scored["relevance_score"] = _candidate_relevance_score(scored, niche, geography, segments)
    return scored


def _finalize_candidates(candidates: list[dict], limit: int) -> list[dict]:
    """Dedup by base_domain, merging structured fields from all sources."""
    by_domain: dict[str, dict] = {}

    for c in candidates:
        # Filter junk results (vacancies, liquidated companies, reviews, etc.)
        title = c.get("company", "") or c.get("title", "")
        snippet = c.get("snippet", "") or c.get("description", "")
        if is_junk_result(title, snippet):
            continue

        domain = c.get("domain") or extract_domain(c.get("website", ""))
        bd = get_base_domain(domain) if domain else ""
        if domain and (not bd or not is_real_domain(bd) or is_aggregator_domain(bd)):
            continue
        # For candidates without domain (e.g. from 2GIS), use company name as key
        if not bd:
            bd = title.lower().strip()
            if not bd:
                continue

        if bd not in by_domain:
            by_domain[bd] = dict(c)  # copy
        else:
            existing = by_domain[bd]
            incoming = c

            # Keep the higher relevance_score as the base record
            if incoming.get("relevance_score", -999) > existing.get("relevance_score", -999):
                # Swap: incoming becomes base, but merge fields from existing
                merged = dict(incoming)
                _merge_fields(merged, existing)
                by_domain[bd] = merged
            else:
                # Existing has higher score, merge incoming fields into it
                _merge_fields(existing, incoming)

    ranked = sorted(
        by_domain.values(),
        key=lambda row: (row.get("relevance_score", -999), _SOURCE_WEIGHTS.get(row.get("source", ""), 0)),
        reverse=True,
    )
    return ranked[:limit]


def _merge_fields(target: dict, source: dict) -> None:
    """Merge non-empty structured fields from *source* into *target* where target is empty."""
    merge_keys = ["address", "city", "phone", "email", "company", "category", "description"]
    for key in merge_keys:
        if not target.get(key) and source.get(key):
            target[key] = source[key]

    # Combine source provenance so we know which engines contributed
    target_sources = target.get("sources", [target.get("source", "")])
    source_sources = source.get("sources", [source.get("source", "")])
    if isinstance(target_sources, str):
        target_sources = [target_sources]
    if isinstance(source_sources, str):
        source_sources = [source_sources]
    target["sources"] = list(set(target_sources + source_sources))


def _is_relevant_business(item: dict, niche: str, geography: str = "", segments: list[str] | None = None) -> bool:
    return _candidate_relevance_score(item, niche, geography, segments) >= _MIN_RELEVANCE_SCORE


# DEPRECATED: _fake_results is no longer called. Kept for reference only.
def _fake_results(query: str, lead_limit: int) -> list[dict]:
    safe_query = "".join(ch for ch in query.lower() if ch.isalnum())[:18] or "company"
    rows = []
    for idx in range(1, min(lead_limit, 80) + 1):
        website = f"https://{safe_query}{idx}.io"
        rows.append(
            {
                "company": f"{query.title()} Company {idx}",
                "city": random.choice(["Berlin", "London", "Warsaw", "Madrid", "Tallinn"]),
                "website": website,
                "domain": extract_domain(website),
                "source_url": "fallback:demo",
                "snippet": "Demo fallback lead because search engine is unavailable",
                "demo": True,
                "source": "demo",
            }
        )
    return rows


def _parse_searxng_items(payload: dict) -> list[dict]:
    items = []
    for item in payload.get("results", []):
        target = normalize_url(item.get("url", ""))
        domain = extract_domain(target)
        if not target or not is_real_domain(domain) or is_aggregator_domain(domain):
            continue
        raw_title = (item.get("title") or "").strip()
        clean_title = re.sub(r"\s*[\|–\-]\s*.*$", "", raw_title).strip()
        clean_title = re.sub(r"^[\U0001F300-\U0001FFFE\s]+", "", clean_title).strip()
        company_name = clean_title[:180] if clean_title else domain.split(".")[0].capitalize()
        items.append(
            {
                "company": company_name,
                "city": "",
                "website": target,
                "domain": domain,
                "source_url": item.get("url", ""),
                "snippet": item.get("content", "")[:400],
                "demo": False,
                "source": "searxng",
            }
        )
    return items


def _build_discover_queries(niche: str, geo: str, segments: list[str], *, has_prompt: bool = False) -> list[str]:
    """Build search queries optimized for finding TARGET CUSTOMERS.

    When has_prompt=True, user described their business — segments are customer types.
    We search ONLY by segments, NOT by niche (niche would find competitors).
    """
    niche = niche.strip()
    geo = geo.strip()
    neg = _NEGATIVE_KEYWORDS

    queries = []

    # Search each segment as a standalone customer-type query
    if segments:
        for seg in segments[:8]:
            seg = seg.strip()
            if seg and len(seg) > 2:
                queries.extend([
                    f"{seg} {geo} контакты телефон {neg}",
                    f"{seg} {geo} официальный сайт {neg}",
                    f'"{seg}" "{geo}" ООО {neg}',
                ])

    # Also search by niche — but ONLY if no prompt (direct niche search)
    # When prompt exists, niche queries would find competitors, not customers
    if not has_prompt or not segments:
        queries.extend([
            f"{niche} {geo} контакты телефон {neg}",
            f"{niche} {geo} о компании {neg}",
            f"{niche} {geo} предприятие {neg}",
            f'"{niche}" "{geo}" ООО {neg}',
        ])

    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        cleaned = " ".join(query.split())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _searxng_fetch_page(
    client: httpx.Client,
    query: str,
    page: int,
    settings,
) -> list[dict]:
    url = f"{settings.searxng_url}/search?q={quote_plus(query)}&format=json&pageno={page}"
    for attempt in range(max(1, settings.searxng_retry_count)):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return _parse_searxng_items(resp.json())
        except Exception:
            if attempt == max(1, settings.searxng_retry_count) - 1:
                logger.warning("SearXNG retry exhausted: '%s' p%d", query, page)
                return []
            time.sleep(0.3 * (2 ** attempt))
    return []


def _search_bing(query: str, limit: int) -> list[dict]:
    settings = get_settings()
    if not settings.bing_api_key:
        return []
    endpoint = "https://api.bing.microsoft.com/v7.0/search"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            endpoint,
            params={"q": query, "count": limit},
            headers={"Ocp-Apim-Subscription-Key": settings.bing_api_key},
        )
        response.raise_for_status()
        payload = response.json()
    results = []
    for item in payload.get("webPages", {}).get("value", []):
        target = normalize_url(item.get("url", ""))
        domain = extract_domain(target)
        if not target or not is_real_domain(domain) or is_aggregator_domain(domain):
            continue
        results.append(
            {
                "company": item.get("name", "Unknown Company")[:180],
                "city": "",
                "website": target,
                "domain": domain,
                "source_url": item.get("url", ""),
                "snippet": item.get("snippet", "")[:400],
                "demo": False,
                "source": "bing",
            }
        )
    return results


def _extract_address_component(address_payload: dict, *kinds: str) -> str:
    for component in address_payload.get("Components", []):
        if component.get("kind") in kinds and component.get("name"):
            return component["name"]
    return ""


def _format_bbox(bounds: list[list[float]] | None) -> str | None:
    if not isinstance(bounds, list) or len(bounds) != 2:
        return None
    first, second = bounds
    if not isinstance(first, list) or not isinstance(second, list) or len(first) != 2 or len(second) != 2:
        return None
    return f"{first[0]},{first[1]}~{second[0]},{second[1]}"


def _build_yandex_map_queries(niche: str, geo: str, segments: list[str]) -> list[str]:
    base_queries = [
        f"{geo}, {niche}".strip(", "),
        f"{niche}, {geo}".strip(", "),
        f"{geo}, {niche} компания".strip(", "),
        f"{geo}, {niche} официальный сайт".strip(", "),
    ]
    for segment in segments[:8]:
        segment = segment.strip()
        if segment:
            base_queries.append(f"{geo}, {niche} {segment}".strip(", "))

    queries: list[str] = []
    for query in base_queries:
        cleaned = " ".join(query.split())
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
    return queries


def _resolve_yandex_geo_bbox(client: httpx.Client, geo: str, settings) -> str | None:
    if not geo.strip():
        return None
    response = client.get(
        _YANDEX_SEARCH_URL,
        params={
            "apikey": settings.yandex_maps_api_key,
            "text": geo,
            "type": "geo",
            "lang": settings.yandex_maps_lang,
            "results": 1,
        },
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if not features:
        return None
    bounds = features[0].get("properties", {}).get("boundedBy")
    return _format_bbox(bounds)


def _parse_yandex_business_feature(feature: dict, query: str) -> dict | None:
    properties = feature.get("properties") or {}
    meta = properties.get("CompanyMetaData") or {}
    company_name = (meta.get("name") or properties.get("name") or "").strip()
    if not company_name:
        return None

    website = normalize_url(meta.get("url", ""))
    domain = extract_domain(website)
    if not website or not domain or not is_real_domain(domain) or is_aggregator_domain(domain):
        return None

    address_payload = meta.get("Address") or {}
    categories = [item.get("name", "").strip() for item in meta.get("Categories", []) if item.get("name")]
    address = meta.get("address") or address_payload.get("formatted") or properties.get("description", "")
    city = _extract_address_component(address_payload, "locality", "province", "area", "district")
    hours_text = ((meta.get("Hours") or {}).get("text") or "").strip()
    snippet_parts = [part for part in [", ".join(categories), address, hours_text] if part]

    return {
        "company": company_name[:180],
        "city": city,
        "website": website,
        "domain": domain,
        "source_url": f"https://yandex.ru/maps/?text={quote_plus(f'{company_name} {address or query}'.strip())}",
        "snippet": " | ".join(snippet_parts)[:400],
        "address": address[:300] if address else "",
        "categories": categories,
        "demo": False,
        "source": "yandex_maps",
    }


def _search_yandex_maps(niche: str, geo: str, segments: list[str], limit: int) -> list[dict]:
    settings = get_settings()
    if not settings.yandex_maps_api_key:
        return []

    queries = _build_yandex_map_queries(niche, geo, segments)
    results: list[dict] = []
    seen_domains: set[str] = set()

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            bbox = _resolve_yandex_geo_bbox(client, geo, settings) if geo else None
            for query in queries:
                if len(results) >= limit:
                    break
                for skip in (0, 20, 40):
                    params = {
                        "apikey": settings.yandex_maps_api_key,
                        "text": query,
                        "type": "biz",
                        "lang": settings.yandex_maps_lang,
                        "results": min(20, max(limit, 10)),
                        "skip": skip,
                    }
                    if bbox:
                        params["bbox"] = bbox
                        params["rspn"] = 1

                    response = client.get(_YANDEX_SEARCH_URL, params=params)
                    response.raise_for_status()
                    features = response.json().get("features") or []
                    if not features:
                        break

                    for feature in features:
                        item = _parse_yandex_business_feature(feature, query)
                        if not item:
                            continue
                        base_domain = get_base_domain(item["domain"])
                        if base_domain in seen_domains:
                            continue
                        seen_domains.add(base_domain)
                        results.append(item)
                        if len(results) >= limit:
                            break
                    time.sleep(0.2)
    except Exception as exc:
        logger.warning("Yandex Maps search failed for '%s %s': %s", niche, geo, exc)

    return results[:limit]


_CITY_ALIASES = {
    "спб": "Санкт-Петербург",
    "питер": "Санкт-Петербург",
    "мск": "Москва",
    "екб": "Екатеринбург",
    "нск": "Новосибирск",
    "нн": "Нижний Новгород",
    "ростов": "Ростов-на-Дону",
    "волгоград": "Волгоград",
}


@functools.lru_cache(maxsize=512)
def _resolve_2gis_city_id(geo: str) -> str | None:
    """Resolve a city name to a 2GIS city ID.

    Checks Redis cache first (30-day TTL — cities don't change), then API.
    Each cache hit saves 1 API call.
    """
    settings = get_settings()
    api_key = settings.twogis_api_key
    if not api_key:
        return None

    city = geo.strip().lower().replace("ё", "е")
    city_query = _CITY_ALIASES.get(city, geo.strip())
    cache_k = _cache_key("city", city_query)

    # Try Redis cache
    r = _get_redis()
    if r:
        try:
            cached = r.get(cache_k)
            if cached is not None:
                return cached if cached != "__none__" else None
        except Exception:
            pass

    # API call
    city_id: str | None = None
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                "https://catalog.api.2gis.com/3.0/items",
                params={
                    "key": api_key,
                    "q": city_query,
                    "type": "adm_div.city",
                    "fields": "items.point",
                    "page_size": 1,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("result", {}).get("items", [])
                if items:
                    city_id = str(items[0]["id"])
    except Exception as e:
        logger.warning(f"2GIS city resolve failed for '{geo}': {e}")

    # Store in Redis (30 days — cities are immutable)
    if r:
        try:
            r.set(cache_k, city_id or "__none__", ex=30 * 24 * 60 * 60)
        except Exception:
            pass

    return city_id


def _search_2gis(niche: str, geo: str, limit: int) -> list[dict]:
    settings = get_settings()
    api_key = settings.twogis_api_key
    if not api_key:
        return []

    # ── Redis cache: same (niche, geo) → skip API call entirely ──
    cache_k = _cache_key("search", niche, geo, str(limit))
    r = _get_redis()
    if r:
        try:
            cached = r.get(cache_k)
            if cached is not None:
                logger.info("2GIS cache HIT for %r/%r (saved %d+ API calls)", niche, geo, 1)
                return _json.loads(cached)
        except Exception:
            pass

    city_id = _resolve_2gis_city_id(geo)
    # 2GIS API limits: page_size MUST be 1..10 (undocumented limit — API returns
    # empty items+error if page_size > 10)
    page_size = min(max(limit, 1), 10)
    # To fetch `limit` results, paginate up to enough pages (max 10 per page)
    max_pages = max(1, min(5, (limit + page_size - 1) // page_size))
    params: dict = {
        "q": niche,
        "type": "branch",
        "page_size": page_size,
        "key": api_key,
        "fields": "items.contact_groups,items.adm_div,items.external_content,items.org",
    }
    if city_id:
        params["city_id"] = city_id
    else:
        params["q"] = f"{niche} {geo}"

    results: list[dict] = []
    seen_domains: set[str] = set()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            for page_num in range(1, max_pages + 1):
                params["page"] = page_num
                resp = client.get("https://catalog.api.2gis.com/3.0/items", params=params)
                if resp.status_code != 200:
                    logger.warning("2GIS /items HTTP %s for q=%r", resp.status_code, niche)
                    break
                try:
                    data = resp.json()
                except Exception:
                    logger.warning("2GIS /items returned non-JSON body for q=%r", niche)
                    break
                # 2GIS returns HTTP 200 with an error envelope when the key is
                # blocked / quota exceeded / bad request. We must surface those
                # loudly — they were silently becoming "no leads found".
                meta = data.get("meta") or {}
                meta_code = meta.get("code")
                if meta_code and meta_code != 200:
                    err = (meta.get("error") or {})
                    logger.error(
                        "2GIS API error: code=%s type=%s message=%s (q=%r)",
                        meta_code,
                        err.get("type"),
                        err.get("message"),
                        niche,
                    )
                    # Key-blocked / quota / auth errors — stop pagination, no point retrying.
                    if meta_code in (401, 403, 429):
                        break
                    break
                items = data.get("result", {}).get("items", [])
                if not items:
                    break
                for item in items:
                    website = ""
                    phone = ""
                    email = ""
                    extra_phones: list[str] = []
                    # Try org.website first (more reliable)
                    org_info = item.get("org", {})
                    if org_info.get("website"):
                        website = org_info["website"]
                    # Walk contact_groups once and collect ALL channels — previously
                    # we dropped 2nd/3rd phones and emails silently.
                    for group in item.get("contact_groups", []):
                        for contact in group.get("contacts", []):
                            ctype = contact.get("type")
                            cval = (contact.get("text") or contact.get("value") or "").strip()
                            if not cval:
                                continue
                            if ctype == "website" and not website:
                                website = cval
                            elif ctype == "phone":
                                if not phone:
                                    phone = cval
                                elif cval not in extra_phones:
                                    extra_phones.append(cval)
                            elif ctype == "email" and not email:
                                email = cval

                    norm = normalize_url(website) if website else ""
                    domain = extract_domain(norm) if norm else ""

                    # Skip if website exists but is bad
                    if domain and (not is_real_domain(domain) or is_aggregator_domain(domain)):
                        continue

                    name = item.get("name", "")
                    if not name:
                        continue

                    # Dedup by domain (if has one) or by company name
                    dedup_key = get_base_domain(domain) if domain else name.lower().strip()
                    if dedup_key in seen_domains:
                        continue
                    seen_domains.add(dedup_key)

                    address_name = item.get("address_name", "")
                    city = ""
                    for adm in item.get("adm_div", []):
                        if adm.get("type") == "city":
                            city = adm.get("name", "")
                            break

                    firm_id = str(item.get("id") or "")
                    results.append(
                        {
                            "company": name[:180],
                            "city": city or geo,
                            "website": norm,
                            "domain": domain,
                            "phone": phone,
                            "extra_phones": extra_phones,
                            "email": email,
                            "source_url": f"https://2gis.ru/search/{quote_plus(niche)}",
                            "snippet": f"{address_name} {phone}".strip()[:400],
                            "address": address_name[:300],
                            "demo": False,
                            "source": "2gis",
                            "firm_id": firm_id,
                        }
                    )
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
                time.sleep(0.3)
    except Exception as exc:
        logger.warning("2GIS search failed for '%s %s': %s", niche, geo, exc, exc_info=True)

    final = results[:limit]

    # ── Store in Redis cache (7 days) — only if we got real results ──
    if final and r:
        try:
            r.set(cache_k, _json.dumps(final, ensure_ascii=False, default=str), ex=_CACHE_TTL_SECONDS)
        except Exception:
            pass

    return final


def _search_maps_via_searxng(niche: str, geo: str, limit: int) -> list[dict]:
    # Disabled: HTML scraping of SPA map pages (2GIS, Yandex Maps) produces
    # garbage data — the meaningful content is loaded via JS, not in the HTML.
    return []
    settings = get_settings()
    map_queries = [
        f"site:2gis.ru {niche} {geo}",
        f"site:yandex.ru/maps {niche} {geo}",
        f"site:yandex.ru/maps {niche} {geo} компания",
    ]

    raw_items: list[dict] = []
    try:
        with httpx.Client(timeout=settings.searxng_timeout_seconds, follow_redirects=True) as client:
            for query in map_queries:
                if len(raw_items) >= limit * 2:
                    break
                url = f"{settings.searxng_url}/search?q={quote_plus(query)}&format=json&pageno=1"
                for attempt in range(2):
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                        payload = resp.json()
                        for item in payload.get("results", []):
                            title = (item.get("title") or "").strip()
                            snippet = (item.get("content") or "").strip()
                            source_url = item.get("url", "")

                            clean_title = re.sub(
                                r"\s*[\|–\-—]\s*(2ГИС|2GIS|Яндекс|Yandex).*$",
                                "",
                                title,
                                flags=re.IGNORECASE,
                            ).strip()
                            clean_title = re.sub(r"^[\U0001F300-\U0001FFFE\s]+", "", clean_title).strip()
                            if not clean_title:
                                continue
                            raw_items.append(
                                {
                                    "company": clean_title[:180],
                                    "city": geo,
                                    "website": "",
                                    "domain": "",
                                    "source_url": source_url,
                                    "snippet": snippet[:400],
                                    "demo": False,
                                    "source": "maps_searxng",
                                }
                            )
                        break
                    except Exception:
                        if attempt == 0:
                            time.sleep(0.5)
                time.sleep(0.3)
    except Exception:
        logger.warning("Maps SearXNG search failed for '%s %s'", niche, geo)

    enriched: list[dict] = []
    seen_domains: set[str] = set()
    for item in raw_items:
        source_url = item["source_url"]
        if "2gis.ru" in source_url or "yandex.ru/maps" in source_url:
            if not _is_safe_url(source_url):
                continue
            try:
                with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                    resp = client.get(source_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                    if resp.status_code < 400:
                        html = resp.text[:80000]
                        websites = re.findall(r'href=["\']?(https?://[^"\'<>\s]+)', html)
                        for website in websites:
                            website_domain = extract_domain(website)
                            website_base = get_base_domain(website_domain)
                            if (
                                website_domain
                                and is_real_domain(website_domain)
                                and not is_aggregator_domain(website_domain)
                                and website_base not in seen_domains
                                and "2gis" not in website_domain
                                and "yandex" not in website_domain
                                and "google" not in website_domain
                            ):
                                seen_domains.add(website_base)
                                enriched.append(
                                    {
                                        **item,
                                        "website": normalize_url(website),
                                        "domain": website_domain,
                                    }
                                )
                                break
            except Exception:
                pass
            time.sleep(0.2)
        if len(enriched) >= limit:
            break
    return enriched[:limit]


def search_leads(query: str, limit: int, *, niche: str = "", geography: str = "", segments: list[str] | None = None, prompt: str = "", use_yandex: bool = True) -> list[dict]:
    effective_niche = (niche or query).strip()
    effective_geo = geography.strip()
    effective_segments = segments or []

    collected: list[dict] = []
    searxng_accessible = False
    skipped_irrelevant = 0
    oversample_limit = max(limit * 5, limit + 50)

    # Build list of specific search terms for maps (2GIS, Yandex)
    # When segments are specific business types (e.g. "птицефабрика", "ветклиника"),
    # search each one separately — much more effective than a combined query
    map_search_terms = []
    if effective_segments:
        for seg in effective_segments[:8]:
            seg = seg.strip()
            if seg and len(seg) > 2:
                map_search_terms.append(seg)
    if not map_search_terms:
        map_search_terms = [effective_niche]

    def collect_candidates(source_items: list[dict]) -> None:
        nonlocal skipped_irrelevant
        for item in source_items:
            scored = _score_candidate(item, effective_niche, effective_geo, effective_segments)
            if scored.get("relevance_score", -999) < _MIN_RELEVANCE_SCORE:
                skipped_irrelevant += 1
                continue
            collected.append(scored)
            if len(collected) >= oversample_limit:
                break

    # Search maps with each segment separately for better results
    per_term_limit = max(oversample_limit // max(len(map_search_terms), 1), 20)

    for term in map_search_terms:
        if use_yandex:
            try:
                if len(collected) < oversample_limit:
                    yandex_results = _search_yandex_maps(term, effective_geo, effective_segments, per_term_limit)
                    collect_candidates(yandex_results)
                    if yandex_results:
                        logger.info("Yandex Maps returned %d results for '%s %s'", len(yandex_results), term, effective_geo)
            except Exception:
                logger.warning("Yandex Maps search error for '%s'", term, exc_info=True)

        try:
            if len(collected) < oversample_limit:
                twogis_results = _search_2gis(term, effective_geo, per_term_limit)
                collect_candidates(twogis_results)
                if twogis_results:
                    logger.info("2GIS returned %d results for '%s %s'", len(twogis_results), term, effective_geo)
        except Exception:
            logger.warning("2GIS search error for '%s'", term, exc_info=True)

        time.sleep(0.2)

    try:
        queries = _build_discover_queries(effective_niche, effective_geo, effective_segments, has_prompt=bool(prompt))
        settings = get_settings()
        local_seen_domains: set[str] = set()

        with httpx.Client(timeout=settings.searxng_timeout_seconds, follow_redirects=True) as client:
            for search_query in queries:
                if len(collected) >= oversample_limit:
                    break
                for page_num in range(1, 4):
                    items = _searxng_fetch_page(client, search_query, page_num, settings)
                    if not items:
                        break

                    page_items: list[dict] = []
                    for item in items:
                        base_domain = get_base_domain(item["domain"])
                        if base_domain in local_seen_domains:
                            continue
                        local_seen_domains.add(base_domain)
                        page_items.append(item)

                    if not page_items:
                        break

                    collect_candidates(page_items)
                    time.sleep(0.3)
                    if len(collected) >= oversample_limit:
                        break
                time.sleep(0.15)
        searxng_accessible = True
    except Exception:
        logger.exception("SearXNG search failed")

    try:
        if len(collected) < oversample_limit:
            maps_results = _search_maps_via_searxng(effective_niche, effective_geo, oversample_limit - len(collected))
            collect_candidates(maps_results)
            if maps_results:
                logger.info(
                    "Maps via SearXNG returned %d results for '%s %s'",
                    len(maps_results),
                    effective_niche,
                    effective_geo,
                )
    except Exception:
        logger.warning("Maps SearXNG search error", exc_info=True)

    try:
        if len(collected) < oversample_limit:
            bing_query = f"{effective_niche} компания {effective_geo}".strip()
            bing_results = _search_bing(bing_query, oversample_limit - len(collected))
            collect_candidates(bing_results)
    except Exception:
        logger.warning("Bing search error", exc_info=True)

    if skipped_irrelevant:
        logger.info("Filtered out %d irrelevant results for niche='%s'", skipped_irrelevant, effective_niche)

    ranked = _finalize_candidates(collected, limit)
    if ranked:
        from app.services.llm_filter import filter_candidates_llm
        ranked = filter_candidates_llm(ranked, effective_niche, effective_geo, effective_segments, prompt=prompt)
        return ranked
    # Never generate fake/synthetic leads — return empty list so callers see
    # real zero-result state and can act accordingly.
    return []


def enrich_website_contacts(base_url: str) -> dict:
    parsed = urlparse(base_url if base_url.startswith(("http://", "https://")) else f"https://{base_url}")
    domain = extract_domain(base_url)
    if not domain or is_aggregator_domain(domain):
        return {"emails": [], "phones": [], "addresses": []}
    root_url = f"{parsed.scheme or 'https'}://{domain}"
    candidate_paths = ["/", "/contacts", "/contact", "/contact-us", "/about", "/about-us", "/kontakty", "/o-kompanii"]
    gathered_text = ""
    gathered_html = ""
    robots = RobotFileParser()
    robots.set_url(f"{root_url.rstrip('/')}/robots.txt")
    try:
        robots.read()
    except Exception:
        robots = None
    for path in candidate_paths:
        target = normalize_url(f"{root_url}{path}" if path != "/" else root_url)
        if not target:
            continue
        if not _is_safe_url(target):
            continue
        if robots and not robots.can_fetch(DEFAULT_USER_AGENT, target):
            continue
        try:
            with httpx.Client(timeout=6.0, follow_redirects=False) as client:
                for attempt in range(3):
                    response = client.get(target, headers={"User-Agent": DEFAULT_USER_AGENT})
                    if response.status_code in (429, 503):
                        time.sleep(0.2 * (2**attempt))
                        continue
                    if response.status_code < 400:
                        gathered_html += f"\n{response.text[:50000]}"
                        plain_text = TAG_RE.sub(" ", unescape(response.text))
                        gathered_text += f"\n{plain_text[:25000]}"
                    break
        except Exception:
            continue
        time.sleep(0.15)
    return extract_contacts(gathered_text, gathered_html)


# ─── 2GIS public-page enrichment ────────────────────────────────────────────
# The 2GIS Places API minimal tier does not return contact_groups, but the
# public 2gis.ru site renders phones/emails directly in server HTML for search
# results. We query the public search page and extract contacts via regex.

# Multiple realistic browser UAs to rotate across — captcha is rate/fingerprint-based,
# so diversifying the identity reduces trigger rate substantially.
_BROWSER_UAS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15",
)
# Keep the old name as the first UA so legacy callers still work.
_BROWSER_UA = _BROWSER_UAS[0]
# Russian phone numbers come in +7, bare-7, or 8-prefix forms; we accept all three.
# Separators ({0,3}) cover combinations like ` (`, `) `, etc. between digit groups.
_PHONE_RE = re.compile(r"(?:\+7|\b8)[\s\-()]{0,3}\d{3}[\s\-()]{0,3}\d{3}[\s\-()]{0,3}\d{2}[\s\-()]{0,3}\d{2}")
_TEL_LINK_RE = re.compile(r'tel:\+?(\d{10,15})', re.IGNORECASE)
# Stricter email regex — requires TLD of 2-10 chars and forbids the dot-ending seen in fragment matches.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._%+\-]{0,63}@[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}\.[a-zA-Z]{2,10}\b")

# Markers that tell us 2gis.ru served a captcha / blocked page instead of real data.
_CAPTCHA_MARKERS = (
    "captcha", "Captcha", "CAPTCHA",
    "проверка, что вы не робот", "Проверьте, что вы не робот",
    "smart-captcha", "checkbox-captcha", "yandex-captcha",
)


def _normalize_phone(raw: str) -> str:
    """Collapse formatting — '+7 (382) 220-11-36' → '+73822201136'."""
    digits = re.sub(r"\D+", "", raw or "")
    if not digits:
        return ""
    # Russian 8-prefix → 7 canonicalisation
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    return "+" + digits


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _looks_like_captcha(html: str) -> bool:
    """Detect if 2gis.ru served a captcha page instead of real content.

    Captcha pages return HTTP 200 with phone-like strings decorating the challenge,
    so we must sniff the body to avoid wasting the response as a "successful" miss.
    """
    if not html:
        return False
    # Bail fast if the page has a tel: link — real firm pages have those; captchas don't.
    if "tel:" in html:
        return False
    snippet = html[:8000]  # captcha markers always appear in the head/body top
    return any(marker in snippet for marker in _CAPTCHA_MARKERS)


def _fetch_2gis_html(url: str) -> str:
    """Fetch a 2gis.ru page with rotating UA + retries + captcha detection.

    Returns empty string on HTTP failure, network error, or captcha interception.
    Retries up to 4 times with exponential backoff on 429/503/captcha.
    """
    with httpx.Client(timeout=12.0, follow_redirects=True) as client:
        for attempt in range(4):
            ua = _BROWSER_UAS[attempt % len(_BROWSER_UAS)]
            headers = {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                # Only declare encodings httpx decodes by default (brotli requires extra pkg).
                "Accept-Encoding": "gzip, deflate",
            }
            try:
                response = client.get(url, headers=headers)
            except httpx.RequestError:
                if attempt == 3:
                    return ""
                time.sleep(0.5 * (2 ** attempt) + random.random() * 0.3)
                continue
            if response.status_code in (429, 503):
                time.sleep(0.7 * (2 ** attempt) + random.random() * 0.5)
                continue
            if response.status_code >= 400:
                return ""
            body = response.text or ""
            if _looks_like_captcha(body):
                # Back off harder — captcha trip means we were fingerprinted, so give
                # it time and rotate UA before the next attempt.
                if attempt == 3:
                    logger.info("2gis captcha persists after 4 attempts for %s", url)
                    return ""
                time.sleep(1.0 * (2 ** attempt) + random.random() * 0.5)
                continue
            return body
    return ""


def enrich_2gis_lead(company: str, city: str = "", firm_id: str = "") -> dict:
    """Fetch phones/emails for a 2GIS lead from the public 2gis.ru site.

    Strategy (best signal first):
      1. If firm_id provided — hit firm page directly (/firm/{id}).
      2. Otherwise — search page (/search/{company} {city}) + take results
         shown in the server-rendered HTML.

    Returns dict with keys emails/phones/addresses (same shape as
    enrich_website_contacts).
    """
    result: dict = {"emails": [], "phones": [], "addresses": []}
    company = (company or "").strip()
    if not company and not firm_id:
        return result

    def _extract_phones(html: str) -> list[str]:
        plus_phones = _PHONE_RE.findall(html)
        tel_phones = [("+" + d if not d.startswith("+") else d) for d in _TEL_LINK_RE.findall(html)]
        raw = plus_phones + tel_phones
        normed = _dedup_preserve_order([_normalize_phone(p) for p in raw])
        return [p for p in normed if p and 11 <= len(re.sub(r"\D", "", p)) <= 12]

    # Try URL paths in order; stop at the first one that yields any phone.
    # 2gis.ru returns 200 even for non-existent firm IDs ("ничего не найдено"),
    # so we must fall back on empty content, not just HTTP errors.
    urls: list[str] = []
    if firm_id:
        urls.append(f"https://2gis.ru/firm/{firm_id}")
    if company:
        query = company if not city else f"{company} {city}"
        urls.append(f"https://2gis.ru/search/{quote_plus(query)}")

    html = ""
    phones: list[str] = []
    for url in urls:
        page_html = _fetch_2gis_html(url)
        if not page_html:
            continue
        page_phones = _extract_phones(page_html)
        if page_phones:
            html = page_html
            phones = page_phones
            break
        # Keep the last non-empty HTML so we can still pull emails if phones missed
        html = page_html

    if not html:
        return result

    # Emails: regex across HTML with false-positive filtering
    emails_raw = _EMAIL_RE.findall(html)
    filtered_emails = []
    for e in emails_raw:
        e_low = e.lower()
        # Reject CDN/static resources and 2GIS internal addresses
        if any(bad in e_low for bad in (
            ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif",
            ".woff", ".ttf", ".css", ".js",
            "2gis.ru", "2gis.com", "example.com", "sentry",
        )):
            continue
        filtered_emails.append(e_low)
    emails = _dedup_preserve_order(filtered_emails)

    result["phones"] = phones[:5]
    result["emails"] = emails[:5]
    # Address is non-trivial to extract reliably from search HTML; leave empty
    # and rely on the 2GIS API address that was saved at collection time.
    return result

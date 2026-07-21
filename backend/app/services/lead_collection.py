import base64
import functools
import hashlib
import json as _json
import random
import time
from html import unescape
import logging
import re
from urllib.parse import quote_plus, urljoin, urlparse
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

# Module-level singleton Redis client. Re-using the client across requests
# lets us avoid reconnection overhead and prevents connection-pool leaks under
# concurrent load (each _get_redis() call used to create a new client).
_REDIS_SINGLETON: "redis.Redis | None" = None


def _get_redis() -> "redis.Redis | None":
    """Return a shared Redis client on DB 3 (cache). Thread-safe — redis.Redis
    manages its own internal connection pool.
    """
    global _REDIS_SINGLETON
    if _REDIS_SINGLETON is not None:
        return _REDIS_SINGLETON
    try:
        url = get_settings().redis_url  # e.g. redis://localhost:6379/0
        # Use DB 3 for 2GIS cache (0=app, 1=celery broker, 2=celery results)
        base = url.rsplit("/", 1)[0] if "/" in url else url
        _REDIS_SINGLETON = redis.Redis.from_url(
            f"{base}/3", decode_responses=True, socket_timeout=2, socket_connect_timeout=2,
        )
        return _REDIS_SINGLETON
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
    # Editorial / news (NEVER a real lead)
    "kp.ru", "pravda.ru", "dzen.ru", "vc.ru", "pikabu.ru",
    "forbes.ru", "rbc.ru", "ria.ru", "tass.ru", "kommersant.ru",
    "vedomosti.ru", "lenta.ru", "gazeta.ru", "interfax.ru",
    "habr.com", "3dnews.ru", "tadviser.ru", "tadviser.com",
    # Industry publications / marketing blogs
    "markakachestva.ru", "oknatrade.ru", "retail.ru", "retailer.ru",
    "agroinvestor.ru", "dairynews.ru", "mcx.ru",  # last one is gov portal
    # Wiki / directory / catalog aggregators
    "wikipedia.org", "ru.wikipedia.org", "wiki-prom.ru",
    "wikimapia.org", "esosedi.org", "images.esosedi.org",
    "tradus.com", "europages.ru", "flagma.ru",
    # Map / directory (their own listings, not individual businesses)
    "yell.ru", "zoon.ru", "flamp.ru", "2gis.ru", "yandex.ru",
    # Marketplaces
    "wildberries.ru", "ozon.ru", "avito.ru", "market.yandex.ru",
    # Registries (handled separately in rusprofile flow, but filter web surfacings)
    "rusprofile.ru", "list-org.com", "e-ecolog.ru", "sravni.ru",
}

_ARTICLE_OR_DIRECTORY_HINTS = [
    "рейтинг", "лучших", "лучшие", "лучший", "топ 10", "топ-10",
    # "обзор" and "подборка" removed — they legitimately appear in B2B case-study
    # titles like "подборка лучших поставщиков для HoReCa" which are useful leads.
    "список компаний", "каталог компаний", "каталог фирм",
    "справочник", "адреса и телефоны",
    "что такое", "как работает", "значение слова", "история развития",
    # How-to/advice patterns that over-matched earlier (e.g. "Электрификация
    # магазина" for niche "электрика"): these are articles, not leads.
    "как выбрать", "как сделать", "как провести", "советы по",
    "руководство по", "пошаговое", "своими руками",
    "основы", "с чего начать", "инструкция",
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

# Words that signal "this is a real company" WITHOUT implying they sell the product.
# Words like "купить", "прайс", "заказать", "магазин", "оптом", "поставщик" used to be
# here, but they're competitor signals (see _COMPETITOR_SIGNALS below) — having them
# in both lists let sellers score +10 biz bonus before the competitor penalty kicked in.
_BIZ_SIGNAL_WORDS = [
    "ооо", "оао", "зао", "ип ", "компания", "предприятие", "организация",
    "услуг", "сервис",
    "звоните", "наш адрес", "контакты", "телефон:",
    "+7", "8 (", "info@",
    "режим работы", "график работы",
    "официальный сайт",
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
    "rusprofile": 45,        # legal-entity registry — high credibility but no contacts
    "maps_searxng": 40,
    "yandex_search": 30,     # официальный Yandex Search API — надёжнее скрейпа
    "searxng": 26,
    "bing": 20,
}

# Split into CORE (always safe) and SELLER_EXTRA (only when prompt exists AND
# segments don't explicitly include online stores / distributors). Previously
# a single monolithic list dinged projects whose target customer is literally
# "интернет-магазины одежды" — the seller negatives killed the target audience.
#
# Fix [searx-query-len]: поисковые движки за SearXNG режут запрос на ~32 словах.
# Старые хвосты негативов раздували запрос до 45-65 слов — ВСЕ исключения
# молча отбрасывались движком и не работали. Новый бюджет: ≤10 токенов
# негативов на запрос, самые ценные — первыми. Доменные негативы (-2gis.ru,
# -avito.ru, …) убраны полностью: домены-агрегаторы и так режутся после
# выдачи через is_aggregator_domain()/_EDITORIAL_OR_DIRECTORY_DOMAINS.
# «-inn» удран отдельно (fix [inn-negative]): он выкидывал отели с «Inn»
# в названии; страницы реестров отфильтровываются доменными фильтрами.
_NEGATIVE_CORE = "-вакансии -работа -форум -отзывы -рейтинг -википедия"

# Seller-исключения идут ПЕРВЫМИ в комбинированной строке — если движок всё же
# обрежет хвост, переживут самые важные для buyer-hunt токены.
_NEGATIVE_SELLER_EXTRA = "-купить -интернет-магазин -оптом -поставщик"

# Kept for backward compat with callers that haven't migrated yet.
_NEGATIVE_KEYWORDS = f"{_NEGATIVE_SELLER_EXTRA} {_NEGATIVE_CORE}"


def _pick_negatives(*, has_prompt: bool, segments: list[str] | None) -> str:
    """Choose CORE only (safe) or SELLER_EXTRA+CORE (when we're hunting buyers).

    If segments mention shop / marketplace / distributor keywords,
    we stay with CORE only — the seller-negatives would kill the target.

    Fix [neg-per-segment]: решение принимается ПО СЕГМЕНТУ — вызывающий код
    передаёт [seg] внутри цикла. Раньше решение принималось один раз по блобу
    ВСЕХ сегментов, и один seller-сегмент отключал seller-негативы для всего
    проекта.
    """
    if not has_prompt:
        return _NEGATIVE_CORE  # Direct niche search: don't over-filter
    if not segments:
        return _NEGATIVE_CORE  # Unknown segments: play safe
    seg_blob = " ".join(segments).lower()
    # Fix [neg-per-segment]: голое «интернет» больше не триггер — сегмент типа
    # «интернет-провайдер» (легитимный покупатель) отключал seller-негативы.
    # «интернет-магазин» покрывается подстрокой «магазин».
    for word in ("магазин", "маркетплейс", "дистрибьютор", "поставщик", "оптов"):
        if word in seg_blob:
            return _NEGATIVE_CORE  # Target audience IS a seller category
    return f"{_NEGATIVE_SELLER_EXTRA} {_NEGATIVE_CORE}"

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
    # Russian "Trading House" abbreviations — near-synonyms of "магазин".
    # "тд " has trailing space to avoid matching "тдушка"/random letter blends.
    "тд ", "торговый дом", "т/д", "т.д.",
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
                # Also add the stem (first 4 chars of lemma) for partial
                # matching. Keeping [:4] preserves "корм" for "кормовой/
                # кормовые" family. For lemmas ≥ 8 chars we also emit a 5-char
                # stem so long niche words ("электрика") don't over-match
                # unrelated short ones ("элит") via loose prefix overlap —
                # the 5-char stem "элект" is specific enough to discriminate.
                if len(lemma) >= 5:
                    stem4 = lemma[:4]
                    if stem4 not in seen:
                        seen.add(stem4)
                        terms.append(stem4)
                if len(lemma) >= 8:
                    stem5 = lemma[:5]
                    if stem5 not in seen:
                        seen.add(stem5)
                        terms.append(stem5)
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

    # Check BOTH the source URL's domain AND the candidate's own website domain.
    # Previously we only checked source_domain, so a company whose "website"
    # was literally a media domain (tadviser.ru, forbes.ru) slipped through.
    candidate_domain = extract_domain(item.get("website", "") or item.get("domain", ""))
    if source_domain in _EDITORIAL_OR_DIRECTORY_DOMAINS:
        return True
    if candidate_domain and candidate_domain in _EDITORIAL_OR_DIRECTORY_DOMAINS:
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
    is_registry_source = source in {"rusprofile"}

    # For web sources (SearXNG, Bing) — domain is required (it's a web result after all)
    # For maps sources (2GIS, Yandex) — allow results WITHOUT domain if they have company + (address OR phone)
    # For registry sources (rusprofile) — allow on company name alone, since
    # phones/emails are JS-rendered and unreachable. They're real legal entities.
    if not domain:
        if not is_maps_source and not is_registry_source:
            return -999
        if is_maps_source:
            # Maps result without website — require company name + (address or phone)
            if not item.get("company") or (not item.get("address") and not item.get("phone")):
                return -999
        if is_registry_source:
            # Registry: just company name is enough
            if not item.get("company") or len(item.get("company", "")) < 4:
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

    # Pre-compute competitor score so we can suppress niche-bonuses for sellers.
    # A seller's name naturally contains the niche words (that's their product),
    # so the +28 phrase and up-to +30 term bonuses would wrongly reward them.
    _competitor_name_hits = sum(1 for word in _COMPETITOR_SIGNALS if word in company)
    _competitor_other_hits = sum(
        1 for word in _COMPETITOR_SIGNALS
        if word in combined and word not in company
    )
    _competitor_score_pre = _competitor_name_hits * 3 + _competitor_other_hits
    _is_likely_seller = _competitor_score_pre >= 3

    if niche_phrase and niche_phrase in combined:
        if _is_likely_seller:
            score += 6   # sharply reduced — seller's own product name
        else:
            score += 28
    niche_term_bonus = min(30, title_hits * 8 + context_hits * 3)
    if _is_likely_seller:
        niche_term_bonus = niche_term_bonus // 4   # sellers don't get full credit
    score += niche_term_bonus
    if niche_terms and title_hits + context_hits == 0:
        # Harder penalty for searxng/bing zero-hit results. Maps results are
        # not penalized the same way — they were fetched via a targeted
        # segment query so the item IS the target audience even without
        # niche words in the snippet. For web-search results, zero niche
        # match means the result is almost certainly off-topic (e.g. a
        # consulting firm surfacing for an "электрика" project).
        if source in {"searxng", "bing", "yandex_search"}:
            score -= 32
        else:
            score -= 24
    elif niche_terms and title_hits == 0:
        score -= 8

    # Segment matching — bonus for matching target customer type.
    # Use _build_match_terms so segment words are lemmatized + stem-matched
    # (avoids missing "молочные фермы" ↔ "молочного производства" due to case).
    if segments:
        seg_terms = _build_match_terms(*segments)
        seg_hits = sum(1 for term in seg_terms if term in combined)
        score += min(20, seg_hits * 6)

    # Competitor detection — tiered penalty for seller signals. Reuses the
    # pre-computed hit counts (above) so name-field weight stays in sync.
    competitor_score = _competitor_score_pre
    if competitor_score >= 5:
        score -= 55  # strong seller — ТД, магазин + опт + каталог
    elif competitor_score >= 3:
        score -= 30  # likely seller — 2+ snippet markers or name marker + 1 other
    elif competitor_score >= 1:
        score -= 12  # possible seller — 1 marker, leave room for false positives

    # Hard geo guard: when the project targets a SPECIFIC region and the
    # candidate's city resolves to a DIFFERENT federal subject, disqualify it.
    # This is what keeps a Москва / СПб / Благовещенск company out of a
    # 'Томская область' project even if it has a complete contact card. Only
    # fires on a confident city→region mismatch; blank/unknown cities fall
    # through to the soft scoring below (we don't drop what we can't classify).
    if geography and not _is_broad_geo(geography):
        requested_region = _region_of(geography)
        candidate_region = _region_of(item.get("city", ""))
        if requested_region and candidate_region and candidate_region != requested_region:
            return -999

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
        # 2GIS/Yandex results were fetched via a targeted segment query (e.g.
        # "бизнес-центр Екатеринбург"), so the items ARE the target audience
        # by definition. Give a strong baseline bonus to counteract penalties
        # for missing website/domain — these are real businesses on the map.
        score += 18

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
    if source in {"searxng", "bing", "yandex_search"} and credibility_markers < 2:
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
        # For candidates without domain (e.g. from 2GIS), use company name as key.
        # Fix #7 [dedup]: previously the key was just the lowercased company name,
        # so same-name companies in different cities (e.g. "Сибирь" in Tomsk AND
        # Novosibirsk) were collapsed into one record — silently dropping one city.
        # Include normalized city so the key is city-scoped for domain-less entries.
        if not bd:
            company_title = title.lower().strip()
            if not company_title:
                continue
            city_val = (c.get("city") or "").lower().strip()
            # Only append city when present — keeps backward-compat for records
            # with no city field (city-less entries still dedup by name alone).
            bd = f"{company_title}|{city_val}" if city_val else company_title

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
    """Merge non-empty structured fields from *source* into *target* where target is empty.

    website/domain included: a Yandex duplicate often carries the site (→ email
    enrichment path) that the 2GIS/registry base row lacks — dropping it threw
    away the contact trail.
    """
    # Ревью 21.07 (major): при swap'е базы (веб-кандидат победил 2GIS по
    # relevance) поля батча «поиск v2» — rating/review_count/vk/telegram — и
    # firm_id/extra_phones молча выбрасывались. `not target.get(key)` корректен
    # и для None/""/[]: пустое у цели → берём из источника.
    merge_keys = [
        "address", "city", "phone", "email", "company", "category",
        "description", "website", "domain",
        "vk", "telegram", "rating", "review_count", "firm_id", "extra_phones",
    ]
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

    queries = []

    # Search each segment as a standalone customer-type query.
    # Up to 24 segments — the LLM now generates 20-40 specific buyer types
    # (was 6-8 broad categories), and each becomes its own targeted SearXNG
    # query. More segments → wider net → 100+ candidate companies vs 12.
    if segments:
        for seg in segments[:24]:
            seg = seg.strip()
            if seg and len(seg) > 2:
                # Fix [neg-per-segment]: негативы выбираем для КАЖДОГО сегмента
                # отдельно — «магазин одежды» получает CORE, а «ресторан» в том
                # же проекте получает SELLER_EXTRA+CORE.
                neg = _pick_negatives(has_prompt=has_prompt, segments=[seg])
                queries.extend([
                    f"{seg} {geo} контакты телефон {neg}",
                    f"{seg} {geo} официальный сайт {neg}",
                    f'"{seg}" "{geo}" ООО {neg}',
                ])

    # Also search by niche — but ONLY if no prompt (direct niche search).
    # When prompt exists we normally NEVER search by niche — that floods
    # results with sellers of the niche (the user's competitors), not buyers.
    if not has_prompt:
        neg = _pick_negatives(has_prompt=False, segments=None)
        queries.extend([
            f"{niche} {geo} контакты телефон {neg}",
            f"{niche} {geo} о компании {neg}",
            f"{niche} {geo} предприятие {neg}",
            f'"{niche}" "{geo}" ООО {neg}',
        ])
    elif not queries and niche:
        # Fix [prompt-no-segments]: prompt есть, но энхансер не вернул ни одного
        # сегмента. Раньше — ноль веб-запросов навсегда (а веб-проход — это
        # единственный источник сайтов/email). Генерируем хотя бы минимальный
        # запрос из ниши: хуже таргетинг, но лучше, чем гарантированный ноль.
        neg = _pick_negatives(has_prompt=True, segments=None)
        queries.extend([
            f"{niche} {geo} контакты телефон {neg}",
            f"{niche} {geo} официальный сайт {neg}",
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


# ── Yandex Search API v2 (Yandex Cloud) ─────────────────────────────────────
# Официальная замена мёртвого SearXNG-скрейпинга: RU-выдача без капчи. Sync-
# эндпоинт /v2/web/search сразу отдаёт {rawData: base64-XML} классической схемы
# Яндекса. Форма запроса/ответа — по docs.yandex.cloud/search-api и рабочему
# клиенту openclaw-yandex-search. При любой ошибке — тихий фолбэк на SearXNG.
# NB: имя обязано отличаться от _YANDEX_SEARCH_URL выше (Geosearch/карты):
# 13.07 одноимённое переопределение затёрло константу КАРТ, все вызовы
# Яндекс.Карт били в cloud-URL и падали 404 — карты были мертвы у всех орг
# до фикса 16.07 (нашлось финальным смоуком перед стартом продаж).
_YANDEX_WEB_SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"
_HLWORD_RE = re.compile(r"</?hlword[^>]*>", re.IGNORECASE)
# Кап платных Yandex Search запросов на один tier-проход (ограничивает счёт на
# разреженных нишах, где резерв веб-прохода не набирается). Обычный сбор упрётся
# в web_reserve намного раньше — это страховка от worst-case fan-out.
_YANDEX_SEARCH_MAX_REQ_PER_TIER = 60


def _yandex_search_configured(settings) -> bool:
    return bool(
        getattr(settings, "yandex_search_api_key", "")
        and getattr(settings, "yandex_search_folder_id", "")
    )


def _clean_yandex_xml_text(node) -> str:
    """Текст XML-узла Яндекса с вычищенными <hlword>-подсветками и склейкой
    вложенных элементов (title/passage приходят с inline-разметкой)."""
    if node is None:
        return ""
    raw = "".join(node.itertext())
    return _HLWORD_RE.sub("", raw).strip()


class _SkipWebPass(Exception):
    """Сигнал «веб-проход не нужен» (website_preference=no_website)."""


class _YandexSearchError(Exception):
    """Ошибка внутри XML-ответа Яндекса (HTTP 200 + <error code=…>). Отдельный
    тип, чтобы диспетчер откатился на SearXNG, а не тихо получил 0 сайтов."""


def _parse_yandex_search_xml(xml_text: str) -> list[dict]:
    """Разобрать XML Яндекса (yandexsearch>response>results>grouping>group>doc)
    в кандидатов той же формы, что и _parse_searxng_items.

    Поднимает _YandexSearchError, если Яндекс вернул ошибку ВНУТРИ XML при
    HTTP 200 (мисконфиг folder/ключа/биллинга) — иначе веб-проход тихо
    остался бы без единственного источника сайтов/email (ревью 09.07)."""
    import xml.etree.ElementTree as ET

    items: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        logger.warning("Yandex Search: не удалось распарсить XML-ответ")
        return items
    err = root.find(".//error")
    if err is not None:
        raise _YandexSearchError(
            f"code={err.get('code', '?')}: {(err.text or '').strip()[:200]}"
        )
    for doc in root.iter("doc"):
        url_el = doc.find("url")
        target = normalize_url((url_el.text or "").strip() if url_el is not None else "")
        domain = extract_domain(target)
        if not target or not is_real_domain(domain) or is_aggregator_domain(domain):
            continue
        title = _clean_yandex_xml_text(doc.find("title"))
        clean_title = re.sub(r"\s*[\|–\-]\s*.*$", "", title).strip()
        company_name = clean_title[:180] if clean_title else domain.split(".")[0].capitalize()
        passages_el = doc.find("passages")
        snippet = _clean_yandex_xml_text(passages_el) if passages_el is not None else ""
        if not snippet:
            snippet = _clean_yandex_xml_text(doc.find("headline"))
        items.append(
            {
                "company": company_name,
                "city": "",
                "website": target,
                "domain": domain,
                "source_url": (url_el.text or "").strip() if url_el is not None else "",
                "snippet": snippet[:400],
                "demo": False,
                "source": "yandex_search",
            }
        )
    return items


def _yandex_search_fetch_page(
    client: httpx.Client,
    query: str,
    page: int,
    settings,
) -> list[dict]:
    """Одна страница выдачи Yandex Search API v2. page — 1-индексирован (как у
    SearXNG-вызова); Яндекс page 0-индексирован, конвертируем внутри."""
    body = {
        "query": {
            "searchType": "SEARCH_TYPE_RU",
            "queryText": query,
            "familyMode": "FAMILY_MODE_NONE",
            "page": max(0, page - 1),
        },
        "groupSpec": {
            "groupMode": "GROUP_MODE_DEEP",
            "groupsOnPage": 20,
            "docsInGroup": 1,
        },
        "maxPassages": 2,
        "l10n": "LOCALIZATION_RU",
        "folderId": settings.yandex_search_folder_id,
        "responseFormat": "FORMAT_XML",
    }
    region = (getattr(settings, "yandex_search_region", "") or "").strip()
    if region:
        body["region"] = region
    headers = {"Authorization": f"Api-Key {settings.yandex_search_api_key}"}
    resp = client.post(_YANDEX_WEB_SEARCH_URL, json=body, headers=headers,
                       timeout=settings.yandex_search_timeout_seconds)
    resp.raise_for_status()
    raw = (resp.json() or {}).get("rawData", "")
    if not raw:
        return []
    xml_text = base64.b64decode(raw).decode("utf-8", errors="replace")
    return _parse_yandex_search_xml(xml_text)


# Generic-токены названий: пересечение ТОЛЬКО по ним — не матч («Строительная
# компания Альфа» ≠ «Строительная компания Домострой»; ревью 14.07 поймало
# чужой сайт именно на этом).
_LOOKUP_STOPWORDS = frozenset({
    "компания", "фирма", "группа", "центр", "студия", "салон", "магазин",
    "сервис", "служба", "агентство", "бюро", "мастерская", "клиника",
    "организация", "предприятие", "завод", "фабрика", "холдинг",
    "ооо", "зао", "оао", "пао", "ао", "ип", "тд", "тк", "гк", "нпо", "пкф",
    "строительная", "торговая", "производственная", "транспортная",
    "юридическая", "медицинская", "туристическая", "рекламная", "оптовая",
})

_LOOKUP_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+")
_LOOKUP_CACHE_TTL = 14 * 86400  # платный запрос: вердикт «есть ли сайт» живёт 2 недели


def _lookup_tokens(text: str) -> set[str]:
    return {t for t in _LOOKUP_TOKEN_RE.findall((text or "").lower()) if len(t) >= 3}


def yandex_search_company_lookup(company: str, city: str = "") -> dict:
    """Один платный запрос Yandex Search v2 по названию компании: официальный
    сайт + телефон/email из сниппета СОВПАВШЕГО результата.

    Появился 14.07: живой инцидент — все карточные источники контактов легли
    разом (2GIS-тариф без contact_groups, Geosearch 403, скрейп под капчей),
    и у клиента 20/20 лидов без телефона. Это последний фолбэк обогащения и
    верификатор «сайта нет» для website_preference=no_website.

    Гарантии точности (ревью 14.07): матч названия — по значимым токенам
    (пунктуация срезана, generic-слова «компания/строительная/ООО…» не
    считаются), контакты берутся ТОЛЬКО из совпавшего item'а — телефон чужой
    компании из соседнего сниппета хуже пустого. Результат кэшируется в
    Redis на 14 дней (запрос платный; повторные сборы/обогащения того же
    склада не должны жечь деньги заново).

    Возвращает {"website": str, "phone": str, "email": str} (пустые строки,
    если не найдено); {} — если Yandex Search не настроен или упал.
    """
    settings = get_settings()
    if not _yandex_search_configured(settings) or not (company or "").strip():
        return {}

    # Суточный глобальный потолок платных lookup'ов — предохранитель от
    # неожиданного жжения (кроновые сборы × много проектов). Кэш-хиты ниже
    # бесплатны и в кап не попадают.
    r_cap = _get_redis()
    cache_key = "weblookup:" + hashlib.sha1(
        f"{_normalize_match_text(company)}|{_normalize_match_text(city)}".encode()
    ).hexdigest()
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(cache_key)
            if cached:
                return _json.loads(cached)
        except Exception:
            pass

    if r_cap is not None:
        try:
            day_key = f"weblookup_day:{int(time.time()) // 86400}"
            spent_today = r_cap.incr(day_key)
            r_cap.expire(day_key, 86400)
            if spent_today > int(getattr(settings, "web_lookup_daily_cap", 200)):
                logger.warning("web lookup daily cap hit (%s) — skipping", spent_today)
                return {}
        except Exception:
            pass
    query = f"{company.strip()} {city.strip()} контакты телефон".strip()
    try:
        with httpx.Client(timeout=settings.yandex_search_timeout_seconds, follow_redirects=True) as client:
            items = _yandex_search_fetch_page(client, query, page=1, settings=settings)
    except (_YandexSearchError, httpx.HTTPError) as exc:
        # Ошибку НЕ кэшируем (может быть временная) и не молчим: протухший
        # ключ Yandex Search молча отключил бы верификацию «сайта нет» —
        # повтор паттерна инцидента с Geosearch 403.
        logger.warning("yandex company lookup failed for %r: %s", company[:50], exc)
        try:
            from app.services.notifications import send_alert
            send_alert("error", "Yandex Search lookup падает",
                       f"company={company[:40]!r}: {exc}", key="weblookup-down",
                       throttle_seconds=3600)
        except Exception:
            pass
        return {}

    result = {"website": "", "phone": "", "email": ""}
    company_words = _lookup_tokens(company) - _LOOKUP_STOPWORDS
    matched_item = None
    for it in items[:5]:
        title_words = _lookup_tokens(it.get("company") or "")
        domain = (it.get("domain") or "").lower()
        translit_hit = any(
            w[:5] in domain for w in company_words if w.isalpha() and w.isascii() and len(w) >= 5
        )
        if (company_words and company_words & title_words) or translit_hit:
            matched_item = it
            result["website"] = normalize_url(
                it.get("website") or it.get("source_url") or f"https://{domain}"
            )
            break

    if matched_item is not None:
        # Контакты — только из СОВПАВШЕГО результата (contact_parser, а не
        # локальный _PHONE_RE: тот не ловит 4-значные коды городов вроде 3822).
        from app.utils.contact_parser import extract_contacts

        parsed = extract_contacts(
            f"{matched_item.get('company') or ''} {matched_item.get('snippet') or ''}"
        )
        result["phone"] = (parsed.get("phones") or [""])[0]
        result["email"] = (parsed.get("emails") or [""])[0]

    if r is not None:
        try:
            r.setex(cache_key, _LOOKUP_CACHE_TTL, _json.dumps(result, ensure_ascii=False))
        except Exception:
            pass
    return result


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
    """Pick an address component honoring the ARGUMENT priority order.

    Yandex lists Components hierarchically (country → province «ЦФО» →
    province «Рязанская область» → locality «Рязань»), so scanning components
    first returned the federal district for ("locality", "province", ...) —
    and the hard geo guard then disqualified every Yandex row (ЦФО != регион).
    Iterate kinds in caller's order instead, and within a kind take the LAST
    match (the most specific one: «Рязанская область» over «ЦФО»).
    """
    components = address_payload.get("Components", [])
    for kind in kinds:
        matches = [c.get("name") for c in components if c.get("kind") == kind and c.get("name")]
        if matches:
            return matches[-1]
    return ""


def _format_bbox(bounds: list[list[float]] | None) -> str | None:
    if not isinstance(bounds, list) or len(bounds) != 2:
        return None
    first, second = bounds
    if not isinstance(first, list) or not isinstance(second, list) or len(first) != 2 or len(second) != 2:
        return None
    return f"{first[0]},{first[1]}~{second[0]},{second[1]}"


def _build_yandex_map_query_groups(
    niche: str,
    geo: str,
    segments: list[str],
    *,
    has_prompt: bool = False,
) -> list[list[str]]:
    """Build Yandex Places search queries, grouped per segment.

    Fix [yandex-budget]: возвращает СПИСОК ГРУПП — по одной группе запросов на
    сегмент (в buyer-hunt режиме) либо группу нишевых запросов + группы
    «ниша+сегмент». Группировка нужна _search_yandex_maps, чтобы делить бюджет
    платных вызовов между сегментами, а не отдавать его весь первому.

    When `has_prompt=True`, user described their business — niche is THEIR
    product ("кормовые добавки"), segments are THEIR customers ("птицефабрика",
    "молочная ферма"). Including niche in the query brings sellers of the
    niche (competitors). In this mode we query ONLY by segments.

    When `has_prompt=False`, niche is the thing to search for directly.
    """
    raw_groups: list[list[str]] = []

    if has_prompt and segments:
        # Buyer-hunt mode: segment-only queries, one group per segment.
        for segment in segments[:24]:
            segment = segment.strip()
            if not segment:
                continue
            raw_groups.append([
                f"{geo}, {segment}".strip(", "),
                f"{segment}, {geo}".strip(", "),
            ])
    else:
        # Direct niche search.
        raw_groups.append([
            f"{geo}, {niche}".strip(", "),
            f"{niche}, {geo}".strip(", "),
            f"{geo}, {niche} компания".strip(", "),
            f"{geo}, {niche} официальный сайт".strip(", "),
        ])
        for segment in segments[:24]:
            segment = segment.strip()
            if segment:
                raw_groups.append([f"{geo}, {niche} {segment}".strip(", ")])

    # Глобальная дедупликация запросов + отбрасывание пустых групп.
    seen: set[str] = set()
    groups: list[list[str]] = []
    for raw_group in raw_groups:
        group: list[str] = []
        for query in raw_group:
            cleaned = " ".join(query.split())
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                group.append(cleaned)
        if group:
            groups.append(group)
    return groups


def _build_yandex_map_queries(
    niche: str,
    geo: str,
    segments: list[str],
    *,
    has_prompt: bool = False,
) -> list[str]:
    """Flat view of _build_yandex_map_query_groups (kept for compat/tests)."""
    return [
        query
        for group in _build_yandex_map_query_groups(niche, geo, segments, has_prompt=has_prompt)
        for query in group
    ]


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
    # Fix #6 [data-loss]: previously businesses with no website were silently
    # dropped here, while 2GIS keeps them if they have company + address/phone.
    # Mirror the 2GIS behaviour: if website is present but invalid/aggregator →
    # still drop it. If website is simply absent, keep the record as long as
    # it has at least an address or a phone so the lead is actionable.
    if website and domain:
        if not is_real_domain(domain) or is_aggregator_domain(domain):
            # Bad/aggregator website — clear it so the record is still kept
            # (the company+address signal is still valuable).
            website = ""
            domain = ""
    elif website and not domain:
        # normalize_url returned something but extract_domain found nothing
        website = ""
        domain = ""
    # At this point: either we have a clean (website, domain) pair, or both are "".

    address_payload = meta.get("Address") or {}
    categories = [item.get("name", "").strip() for item in meta.get("Categories", []) if item.get("name")]
    address = meta.get("address") or address_payload.get("formatted") or properties.get("description", "")
    city = _extract_address_component(address_payload, "locality", "province", "area", "district")
    # Extract phone if present (some Yandex API responses include it)
    phones_raw = meta.get("Phones") or []
    phone = ""
    if phones_raw and isinstance(phones_raw, list):
        phone = (phones_raw[0].get("formatted") or "").strip()
    hours_text = ((meta.get("Hours") or {}).get("text") or "").strip()
    snippet_parts = [part for part in [", ".join(categories), address, hours_text] if part]

    # Require at least website OR address OR phone — otherwise the lead has no
    # contact path and is noise.
    if not website and not address and not phone:
        return None

    return {
        "company": company_name[:180],
        "city": city,
        "website": website,
        "domain": domain,
        "phone": phone,
        "source_url": f"https://yandex.ru/maps/?text={quote_plus(f'{company_name} {address or query}'.strip())}",
        "snippet": " | ".join(snippet_parts)[:400],
        "address": address[:300] if address else "",
        "categories": categories,
        "demo": False,
        "source": "yandex_maps",
    }


# Circuit-breaker for Yandex Maps. After N consecutive 401/403/429 we stop
# calling the API for the rest of the worker process — saves seconds per project
# of wasted HTTP latency to a known-broken upstream.
_YANDEX_DEAD_KEY = False

# Same pattern for 2GIS API and rusprofile scrape. Both ALSO get hit on every
# segment iteration (24×) inside _search_leads_one_tier, so a dead source
# bleeds 24 × 15s = 6min off every search before we even begin filtering.
# Flipping the breaker on first auth-shaped error ends that bleed instantly.
_TWOGIS_DEAD_KEY = False
# 2GIS public scrape is independent of the API — blocked separately by their
# captcha/anti-bot. Counter keeps it at zero unless we see persistent block,
# then flip after 2nd failure to avoid wasting ~10s × 24 segments.
_TWOGIS_SCRAPE_BLOCKED = False
_TWOGIS_SCRAPE_CAPTCHA_FAILS = 0
# Fix #5 [robustness]: separate captcha-fail counter for the enrichment path.
# Previously _TWOGIS_SCRAPE_CAPTCHA_FAILS was shared between search scraping
# and enrichment scraping. Captchas during enrich_2gis_lead() would disable
# _search_2gis_scrape() for the entire worker process, causing silent data-loss
# on every subsequent project. The two code paths are called independently and
# should not share circuit-breaker state.
_TWOGIS_SCRAPE_CAPTCHA_FAILS_ENRICH = 0
_TWOGIS_SCRAPE_BLOCKED_ENRICH = False
_RUSPROFILE_BLOCKED = False


# Fix [yandex-budget]: bbox географии меняется разве что с релизом Яндекса —
# кэшируем на время жизни процесса. Раньше bbox геокодился заново при КАЖДОМ
# вызове (внутри цикла по term × городам): до 384 платных вызовов на
# общероссийский проект только на геокодинг.
_YANDEX_BBOX_CACHE: dict[str, str | None] = {}


def _charge_yandex_requests(organization_id: str | None, n: int) -> None:
    """Add `n` consumed PAID Yandex Geosearch requests to the org's monthly
    meter. Best-effort, self-contained session (mirrors llm_client._charge);
    a metering failure never blocks collection."""
    if not organization_id or n <= 0:
        return
    try:
        from sqlalchemy import update
        from app.db.session import SessionLocal
        from app.models import Organization
        db = SessionLocal()
        try:
            db.execute(
                update(Organization)
                .where(Organization.id == organization_id)
                .values(
                    yandex_requests_used_current_month=(
                        Organization.yandex_requests_used_current_month + n
                    )
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        logger.warning("Yandex request metering failed (org=%s, n=%d)", organization_id, n)


def _search_yandex_maps(
    niche: str,
    geo: str,
    segments: list[str],
    limit: int,
    *,
    has_prompt: bool = False,
    organization_id: str | None = None,
) -> list[dict]:
    """Search Yandex Places ONCE per geo with a budget shared across segments.

    Fix [yandex-budget]: вызывается один раз на гео со ВСЕМ списком сегментов
    и общим бюджетом `limit` (остаток oversample-окна). Бюджет делится между
    группами запросов (группа = сегмент): первый проход даёт каждой группе
    равную долю (limit // n_groups с минимальным полом), второй — раздаёт
    невыбранный остаток. Раньше функция вызывалась внутри цикла по term (до
    24× с ИДЕНТИЧНЫМ набором запросов), а внутренний ранний break отдавал весь
    бюджет запросам первого сегмента — остальные сегменты получали ноль
    покрытия, а триал-ключ выгорал в ~24 раза быстрее.
    """
    global _YANDEX_DEAD_KEY
    if _YANDEX_DEAD_KEY:
        return []
    settings = get_settings()
    if not settings.yandex_maps_api_key:
        return []

    query_groups = _build_yandex_map_query_groups(niche, geo, segments, has_prompt=has_prompt)
    if not query_groups or limit <= 0:
        return []

    results: list[dict] = []
    seen_domains: set[str] = set()
    # query → следующий offset пагинации (-1 = исчерпан). Нужен, чтобы второй
    # (leftover) проход не перезапрашивал уже оплаченные страницы.
    query_skip: dict[str, int] = {}
    # Billable org-search requests actually made (geocoder bbox lookup excluded);
    # charged to the org's monthly Yandex meter in the finally below.
    req_count = [0]

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            bbox: str | None = None
            geo_key = geo.strip().lower()
            if geo and geo_key in _YANDEX_BBOX_CACHE:
                bbox = _YANDEX_BBOX_CACHE[geo_key]
            elif geo:
                try:
                    bbox = _resolve_yandex_geo_bbox(client, geo, settings)
                    req_count[0] += 1  # billable geo lookup (same endpoint, type=geo)
                    _YANDEX_BBOX_CACHE[geo_key] = bbox
                except httpx.HTTPStatusError as exc:
                    # 401/403 = dead key, 429 = rate limited; both → skip future calls
                    if exc.response.status_code in (401, 403, 429):
                        _YANDEX_DEAD_KEY = True
                        logger.warning(
                            "Yandex Maps key DEAD (HTTP %s on bbox lookup) — disabling for process lifetime",
                            exc.response.status_code,
                        )
                        try:
                            from app.services.notifications import send_alert
                            send_alert(
                                "warning",
                                f"Yandex Maps API dead (HTTP {exc.response.status_code})",
                                "Disabling for this worker. Scrape sources still active.",
                                key=f"yandex_api_{exc.response.status_code}",
                                throttle_seconds=3600,
                            )
                        except Exception:
                            pass
                        return []
                    raise

            def _drain_query(query: str, target: int) -> bool:
                """Тянуть страницы `query`, пока results не достигнет target
                или запрос не исчерпается. False — ключ умер, всё остановить."""
                global _YANDEX_DEAD_KEY
                skip = query_skip.get(query, 0)
                while 0 <= skip <= 40 and len(results) < target:
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

                    try:
                        response = client.get(_YANDEX_SEARCH_URL, params=params)
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code in (401, 403, 429):
                            _YANDEX_DEAD_KEY = True
                            logger.warning("Yandex Maps key DEAD — disabling")
                            query_skip[query] = -1
                            return False
                        raise
                    req_count[0] += 1
                    features = response.json().get("features") or []
                    if not features:
                        skip = -1
                        break

                    # Страница уже оплачена — разбираем её целиком, даже если
                    # слегка перевалим за target (лучше overshoot, чем потеря).
                    for feature in features:
                        item = _parse_yandex_business_feature(feature, query)
                        if not item:
                            continue
                        if item["domain"]:
                            dedup_key = get_base_domain(item["domain"])
                        else:
                            # Записи без сайта дедупим по имя|город — иначе все
                            # они схлопывались по пустому base-домену в одну.
                            dedup_key = f"{item['company'].lower()}|{(item.get('city') or '').lower()}"
                        if dedup_key in seen_domains:
                            continue
                        seen_domains.add(dedup_key)
                        results.append(item)
                    skip += 20
                    time.sleep(0.2)
                query_skip[query] = skip if 0 <= skip <= 40 else -1
                return True

            # Проход 1: каждой группе (сегменту) — равная доля бюджета, чтобы
            # ранние сегменты не съели всё (см. fix [yandex-budget]).
            per_group = max(limit // len(query_groups), 5)
            for group in query_groups:
                if len(results) >= limit:
                    break
                target = min(limit, len(results) + per_group)
                for query in group:
                    if len(results) >= target:
                        break
                    if not _drain_query(query, target):
                        return results[:limit]
            # Проход 2: раздаём невыбранный остаток бюджета (плотные сегменты
            # добирают то, что не выбрали редкие).
            for group in query_groups:
                if len(results) >= limit:
                    break
                for query in group:
                    if len(results) >= limit:
                        break
                    if not _drain_query(query, limit):
                        return results[:limit]
    except Exception as exc:
        logger.warning("Yandex Maps search failed for '%s %s': %s", niche, geo, exc)
    finally:
        _charge_yandex_requests(organization_id, req_count[0])

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


def _parse_2gis_reviews(item: dict) -> tuple[float | None, int | None]:
    """Рейтинг и число отзывов из блока items.reviews ответа 2GIS.

    Терпит любой мусор: нет блока / нули / строки → (None, None) либо
    частичный результат. Нулевой рейтинг трактуем как «нет данных» (2GIS
    отдаёт 0 у карточек без оценок — это не «одна звезда»).
    """
    reviews = item.get("reviews") or {}
    if not isinstance(reviews, dict):
        return None, None
    rating: float | None = None
    review_count: int | None = None
    try:
        raw = reviews.get("general_rating") or reviews.get("rating")
        if raw is not None:
            rating = round(float(raw), 1)
            # NaN-безопасная форма (NaN проваливал `<=`-пару, ревью 21.07).
            if not (0 < rating <= 5):
                rating = None
    except (TypeError, ValueError):
        rating = None
    try:
        raw_n = reviews.get("general_review_count") or reviews.get("review_count")
        if raw_n is not None:
            review_count = max(0, int(raw_n))
    except (TypeError, ValueError):
        review_count = None
    if rating is None and not review_count:
        return None, None
    return rating, review_count


def _search_2gis(niche: str, geo: str, limit: int) -> list[dict]:
    global _TWOGIS_DEAD_KEY
    if _TWOGIS_DEAD_KEY:
        # Skip 24× wasted HTTP roundtrips per search if we know the key is dead.
        # Flag persists for the worker process — gets cleared on next deploy
        # when the operator rotates the key (env reload).
        return []
    settings = get_settings()
    api_key = settings.twogis_api_key
    if not api_key:
        return []

    # ── Redis cache: same (niche, geo) → skip API call entirely ──
    # v2 (21.07): формат кэшируемых кандидатов расширился (rating/vk/…) —
    # смена имени ключа инвалидирует записи старого формата, иначе активные
    # ниши до 7 дней отдавали бы кандидатов без рейтинга/соцсетей.
    cache_k = _cache_key("search_v2", niche, geo, str(limit))
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
    # To fetch `limit` results, paginate up to enough pages (10 per page).
    # Was capped at 5 pages (50 per term) — bumped to 10 (100 per term).
    # Combined with 24 segments → up to 2400 raw 2GIS candidates.
    max_pages = max(1, min(10, (limit + page_size - 1) // page_size))
    params: dict = {
        "q": niche,
        "type": "branch",
        "page_size": page_size,
        "key": api_key,
        # items.reviews — рейтинг/число отзывов (бесплатно в том же ответе);
        # на тарифах без reviews ключ просто отсутствует, парсер терпит.
        "fields": "items.contact_groups,items.adm_div,items.external_content,items.org,items.reviews",
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
                    # Auth/quota errors → fire ops alert (throttled to 1/hour)
                    # AND flip the process-wide circuit breaker so the next 23
                    # segment iterations don't each pay 15s of HTTP timeout.
                    if meta_code in (401, 403, 429):
                        _TWOGIS_DEAD_KEY = True
                        try:
                            from app.services.notifications import send_alert
                            send_alert(
                                "critical",
                                f"2GIS API blocked: {err.get('type', meta_code)}",
                                f"Code {meta_code}: {err.get('message', '')[:200]}\n"
                                f"Scrape continues to work; API fallback is dead.",
                                key=f"2gis_api_{meta_code}",
                                throttle_seconds=3600,
                            )
                        except Exception:
                            pass
                        break
                    break
                items = data.get("result", {}).get("items", [])
                if not items:
                    break
                for item in items:
                    website = ""
                    phone = ""
                    email = ""
                    vk = ""
                    telegram = ""
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
                            if ctype in ("vkontakte", "telegram"):
                                # Соцсети 2GIS кладёт в url; text/value там —
                                # подпись («Наша группа»). Санитайзер отсекает
                                # не-URL мусор (ревью 21.07).
                                soc = sanitize_social(
                                    "vk" if ctype == "vkontakte" else "telegram",
                                    contact.get("url") or contact.get("value") or "",
                                )
                                if soc:
                                    if ctype == "vkontakte" and not vk:
                                        vk = soc
                                    elif ctype == "telegram" and not telegram:
                                        telegram = soc
                                continue
                            # Для phone/email/website url НЕ фолбэк: там лежат
                            # tel:/mailto:/соц-ссылки — мусор в этих полях.
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
                    rating, review_count = _parse_2gis_reviews(item)
                    results.append(
                        {
                            "company": name[:180],
                            "city": city or geo,
                            "website": norm,
                            "domain": domain,
                            "phone": phone,
                            "extra_phones": extra_phones,
                            "email": email,
                            "vk": vk,
                            "telegram": telegram,
                            "rating": rating,
                            "review_count": review_count,
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


# ─── 2GIS scrape-based search (no API quota) ────────────────────────────────
# Parses the embedded initialState JSON from public 2gis.ru search pages.
# Used as primary search path; API fallback only when scraping fails.

_CITY_SLUG_MAP = {
    # Russian city name → 2gis.ru URL slug (Latin transliteration).
    # 2GIS uses unique slugs that DON'T follow standard transliteration rules.
    # Verified working slugs for 80+ Russian cities.
    "москва": "moscow", "санкт-петербург": "spb", "петербург": "spb",
    "новосибирск": "novosibirsk", "екатеринбург": "ekaterinburg",
    "казань": "kazan", "красноярск": "krasnoyarsk", "воронеж": "voronezh",
    "краснодар": "krasnodar", "ростов-на-дону": "rostov", "ростов": "rostov",
    "пермь": "perm", "томск": "tomsk", "барнаул": "barnaul", "омск": "omsk",
    "челябинск": "chelyabinsk", "самара": "samara", "уфа": "ufa",
    "волгоград": "volgograd", "нижний новгород": "n_novgorod",
    "тюмень": "tyumen", "иркутск": "irkutsk", "кемерово": "kemerovo",
    "тула": "tula", "ярославль": "yaroslavl", "хабаровск": "khabarovsk",
    "владивосток": "vladivostok", "саратов": "saratov", "тольятти": "tolyatti",
    "оренбург": "orenburg", "ижевск": "izhevsk", "рязань": "ryazan",
    "калининград": "kaliningrad", "пенза": "penza", "сочи": "sochi",
    "астрахань": "astrakhan", "липецк": "lipetsk", "курск": "kursk",
    "брянск": "bryansk", "белгород": "belgorod", "тверь": "tver",
    "сургут": "surgut", "набережные челны": "nabchelny", "архангельск": "arkhangelsk",
    "владимир": "vladimir", "смоленск": "smolensk", "калуга": "kaluga",
    "чита": "chita", "орел": "orel", "новокузнецк": "novokuznetsk",
    "мурманск": "murmansk", "вологда": "vologda", "якутск": "yakutsk",
    # ── Extended (verified working) ──
    "иваново": "ivanovo", "чебоксары": "cheboksary", "магнитогорск": "magnitogorsk",
    "сыктывкар": "syktyvkar", "пятигорск": "pyatigorsk",
    "нижневартовск": "nizhnevartovsk", "ноябрьск": "noyabrsk", "норильск": "norilsk",
    "стерлитамак": "sterlitamak", "волжский": "volzhsky", "кострома": "kostroma",
    "таганрог": "taganrog", "майкоп": "maikop", "череповец": "cherepovets",
    "саранск": "saransk", "энгельс": "engels", "кызыл": "kyzyl",
    "орск": "orsk", "нальчик": "nalchik", "шахты": "shakhty",
    "ангарск": "angarsk", "ковров": "kovrov", "новочеркасск": "novocherkassk",
    "псков": "pskov", "бийск": "biysk", "рыбинск": "rybinsk",
    "северодвинск": "severodvinsk", "дербент": "derbent", "салават": "salavat",
    "октябрьский": "oktyabrskij", "улан-удэ": "ulanude", "улан удэ": "ulanude",
    "грозный": "groznyj", "симферополь": "simferopol", "севастополь": "sevastopol",
    "ставрополь": "stavropol", "балашиха": "balashiha", "подольск": "podolsk",
    "химки": "khimki", "люберцы": "lyubercy", "королев": "korolev",
    "мытищи": "mytischi", "красногорск": "krasnogorsk", "одинцово": "odincovo",
    "электросталь": "elektrostal", "сергиев посад": "sergiev_posad",
    "пушкино": "pushkino", "раменское": "ramenskoe", "коломна": "kolomna",
    "серпухов": "serpukhov", "орехово-зуево": "orekhovo_zuevo",
    "обнинск": "obninsk", "тамбов": "tambov", "уссурийск": "ussuriysk",
    "новороссийск": "novorossiysk", "армавир": "armavir", "благовещенск": "blagoveshchensk",
    "петропавловск-камчатский": "petropavlovsk", "южно-сахалинск": "yujno_sakhalinsk",
    "комсомольск-на-амуре": "komsomolsk", "великий новгород": "vnovgorod",
}

# Runtime cache for auto-discovered slugs (populated by HTTP probes).
# Stored on the instance level so we don't keep probing 2gis for unknown cities.
_AUTO_SLUG_CACHE: dict[str, str | None] = {}


def _try_auto_discover_slug(city_lower: str) -> str | None:
    """Probe 2gis.ru with several transliteration candidates to find slug.

    Cheap heuristic — most Russian cities follow simple transliteration
    rules. We try a few candidates and HEAD-request each. First 200 wins.
    Returns None if nothing matches (caller should fall back).

    Two-tier cache:
      1. In-process dict (fastest)
      2. Redis (DB 3, 90-day TTL — slugs don't change)
    """
    if city_lower in _AUTO_SLUG_CACHE:
        return _AUTO_SLUG_CACHE[city_lower]

    # Check Redis
    r_redis = _get_redis()
    redis_k = f"{_CACHE_PREFIX}slug_probe:{hashlib.md5(city_lower.encode()).hexdigest()[:12]}"
    if r_redis:
        try:
            cached = r_redis.get(redis_k)
            if cached is not None:
                value = None if cached == "__none__" else cached
                _AUTO_SLUG_CACHE[city_lower] = value
                return value
        except Exception:
            pass

    # Build transliteration candidates
    translit_table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
        "х": "kh", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y",
        "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    base = "".join(translit_table.get(ch, ch) for ch in city_lower)
    base = base.replace(" ", "_").replace("-", "_")

    candidates = [
        base,
        base.replace("_", ""),     # 'novyy_urengoy' → 'novyyurengoy'
        base.replace("yj", "y"),   # 'oktyabrskij' alt 'oktyabrskiy'
        base.replace("kh", "h"),   # alt h-spelling
        base.replace("yy", "y"),
    ]
    candidates = list(dict.fromkeys(candidates))  # dedupe

    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            for i, cand in enumerate(candidates[:5]):  # cap probes
                try:
                    r = client.head(
                        f"https://2gis.ru/{cand}",
                        headers={"User-Agent": _BROWSER_UAS[i % len(_BROWSER_UAS)]},
                    )
                    if r.status_code == 200:
                        _AUTO_SLUG_CACHE[city_lower] = cand
                        if r_redis:
                            try:
                                r_redis.set(redis_k, cand, ex=90 * 24 * 60 * 60)
                            except Exception:
                                pass
                        logger.info("Auto-discovered 2GIS slug: %r → %r", city_lower, cand)
                        return cand
                except httpx.RequestError:
                    continue
    except Exception:
        pass

    _AUTO_SLUG_CACHE[city_lower] = None
    if r_redis:
        try:
            r_redis.set(redis_k, "__none__", ex=7 * 24 * 60 * 60)
        except Exception:
            pass
    return None


def _city_to_slug(geo: str) -> str | None:
    """Convert a Russian city name to a 2gis.ru URL slug.

    Strategy:
    1. Exact match in _CITY_SLUG_MAP (instant).
    2. Substring match (handles "Томск и область").
    3. Auto-discover via HTTP probe with transliteration candidates (cached).
    Returns None if nothing matches.
    """
    city = geo.strip().lower().replace("ё", "е")
    if city in _CITY_SLUG_MAP:
        return _CITY_SLUG_MAP[city]
    for known, slug in _CITY_SLUG_MAP.items():
        if known in city:
            return slug
    # Last resort: probe 2gis.ru with transliteration candidates.
    return _try_auto_discover_slug(city)


def _search_2gis_scrape(niche: str, geo: str, limit: int) -> list[dict]:
    """Search 2GIS by scraping the public 2gis.ru page (zero API calls).

    Parses the embedded initialState JSON from the server-rendered HTML.
    Returns the same dict format as _search_2gis (API version) so the caller
    can swap them transparently.
    """
    global _TWOGIS_SCRAPE_BLOCKED
    if _TWOGIS_SCRAPE_BLOCKED:
        # Captcha is persistent; subsequent calls would each spend ~10s
        # losing to the same bot-detection. Cleared on next worker restart.
        return []

    slug = _city_to_slug(geo)
    if not slug:
        logger.debug("2GIS scrape: no slug for geo=%r, skip", geo)
        return []

    # Redis cache (same key prefix as API, but with :scrape suffix)
    cache_k = _cache_key("scrape", niche, slug, str(limit))
    r = _get_redis()
    if r:
        try:
            cached = r.get(cache_k)
            if cached is not None:
                logger.info("2GIS scrape cache HIT for %r/%r", niche, slug)
                return _json.loads(cached)
        except Exception:
            pass

    base_url = f"https://2gis.ru/{slug}/search/{quote_plus(niche)}"
    # Fetch multiple pages (2gis.ru serves /page/N). Each page gives ~15-20 NEW
    # companies. Cap at 8 pages (~120-160 items) — was 4. We're a paid product
    # now; coverage matters more than the +30s latency from extra pages.
    max_pages = min(8, max(1, (limit + 14) // 15))
    merged_names: list[tuple[str, int]] = []
    merged_addrs: list[tuple[str, int]] = []
    merged_org_ids: list[tuple[str, int]] = []
    pos_offset = 0

    for page_num in range(1, max_pages + 1):
        page_url = base_url if page_num == 1 else f"{base_url}/page/{page_num}"
        html = _fetch_2gis_html(page_url)
        if not html or len(html) < 5000:
            break

        # Extract per-page matches; shift positions by cumulative offset so
        # the correlation logic below (proximity-based) still works across pages.
        page_primaries = [
            (m.group(1), m.start() + pos_offset)
            for m in re.finditer(r'"primary":"([^"]{2,80})"', html)
        ]
        merged_names.extend(page_primaries)
        merged_addrs.extend(
            (m.group(1), m.start() + pos_offset)
            for m in re.finditer(r'"address_name":"([^"]+)"', html)
        )
        merged_org_ids.extend(
            (m.group(1), m.start() + pos_offset)
            for m in re.finditer(r'"org":\{[^}]*"id":"(\d+)"', html)
        )
        pos_offset += len(html)

        # Short-circuit if we already have well more than requested
        if len({n for n, _ in merged_names}) >= limit + 5:
            break
        time.sleep(0.2 + random.random() * 0.2)

    if not merged_names:
        return []

    # 1) Dedupe names preserving order
    names: list[tuple[str, int]] = []
    seen_primary: set[str] = set()
    for n, p in merged_names:
        if n not in seen_primary:
            seen_primary.add(n)
            names.append((n, p))

    addrs = merged_addrs
    org_ids = merged_org_ids

    # 4) Build candidates by correlating positions
    results: list[dict] = []
    seen_names: set[str] = set()
    for name, npos in names[:limit * 2]:  # over-fetch to handle junk
        if name in seen_names:
            continue
        # Skip junk entries (generic names that aren't businesses)
        if len(name) < 3 or name.lower() in ("интернет-портал", "интернет"):
            continue

        # Find closest org ID after this name
        firm_id = ""
        for oid, opos in org_ids:
            if opos > npos and opos - npos < 800:
                firm_id = oid
                break

        # Find closest preceding address_name
        address = ""
        for aname, apos in reversed(addrs):
            if apos < npos:
                address = aname
                break

        seen_names.add(name)
        results.append({
            "company": name[:180],
            "city": geo.strip(),
            "website": "",
            "domain": "",
            "phone": "",
            "source_url": base_url,
            "snippet": address[:400],
            "address": address[:300],
            "demo": False,
            "source": "2gis",
            "firm_id": firm_id,
        })
        if len(results) >= limit:
            break

    # Cache results (7 days) — only if we actually found something
    if results and r:
        try:
            r.set(cache_k, _json.dumps(results, ensure_ascii=False, default=str), ex=_CACHE_TTL_SECONDS)
        except Exception:
            pass

    logger.info("2GIS scrape: %d results for %r in %s (0 API calls)", len(results), niche, slug)
    return results


# ─── Yandex Maps scrape (public site, no API key needed) ─────────────────────
# Yandex Maps renders 15 business-snippet tiles per page in server HTML —
# usable as a free parallel source to 2GIS for coverage.

_YANDEX_CITY_SLUG_MAP = {
    # City name → Yandex Maps URL slug (usually same as 2GIS but double-check
    # for multi-word cities)
    "москва": "moscow", "санкт-петербург": "saint-petersburg", "петербург": "saint-petersburg",
    "новосибирск": "novosibirsk", "екатеринбург": "yekaterinburg",
    "казань": "kazan", "красноярск": "krasnoyarsk", "воронеж": "voronezh",
    "краснодар": "krasnodar", "ростов-на-дону": "rostov-na-donu", "ростов": "rostov-na-donu",
    "пермь": "perm", "томск": "tomsk", "барнаул": "barnaul", "омск": "omsk",
    "челябинск": "chelyabinsk", "самара": "samara", "уфа": "ufa",
    "волгоград": "volgograd", "нижний новгород": "nizhny-novgorod",
    "тюмень": "tyumen", "иркутск": "irkutsk", "кемерово": "kemerovo",
    "тула": "tula", "ярославль": "yaroslavl", "хабаровск": "khabarovsk",
    "владивосток": "vladivostok", "саратов": "saratov", "тольятти": "tolyatti",
    "оренбург": "orenburg", "ижевск": "izhevsk", "рязань": "ryazan",
    "калининград": "kaliningrad", "пенза": "penza", "сочи": "sochi",
    "астрахань": "astrakhan", "липецк": "lipetsk", "курск": "kursk",
    "брянск": "bryansk", "белгород": "belgorod", "тверь": "tver",
    "сургут": "surgut", "владимир": "vladimir", "смоленск": "smolensk",
    "калуга": "kaluga", "чита": "chita", "вологда": "vologda",
}

# Fix #1 [geo]: Yandex Maps search URLs have the form
# https://yandex.ru/maps/{city_id}/{city_slug}/search/{query}
# The city_id segment is Yandex's internal geo-object ID — NOT a slug.
# Previously the code hardcoded 67 (Tomsk) for EVERY geography, so every
# non-Tomsk project silently returned Tomsk results.
# These IDs are stable Yandex geo IDs verified against the public Yandex API.
_YANDEX_CITY_ID_MAP: dict[str, int] = {
    "москва": 213, "санкт-петербург": 2, "петербург": 2,
    "новосибирск": 65, "екатеринбург": 54,
    "казань": 43, "красноярск": 62, "воронеж": 193,
    "краснодар": 35, "ростов-на-дону": 39, "ростов": 39,
    "пермь": 50, "томск": 67, "барнаул": 197, "омск": 66,
    "челябинск": 56, "самара": 51, "уфа": 172,
    "волгоград": 38, "нижний новгород": 47,
    "тюмень": 55, "иркутск": 63, "кемерово": 64,
    "тула": 15, "ярославль": 16, "хабаровск": 76,
    "владивосток": 75, "саратов": 194, "тольятти": 239,
    "оренбург": 195, "ижевск": 44, "рязань": 11,
    "калининград": 22, "пенза": 198, "сочи": 971,
    "астрахань": 37, "липецк": 9, "курск": 8,
    "брянск": 191, "белгород": 4, "тверь": 14,
    "сургут": 973, "владимир": 192, "смоленск": 12,
    "калуга": 7, "чита": 68, "вологда": 21,
}


def _yandex_city_slug(geo: str) -> str | None:
    city = (geo or "").strip().lower().replace("ё", "е")
    if city in _YANDEX_CITY_SLUG_MAP:
        return _YANDEX_CITY_SLUG_MAP[city]
    # Fallback to 2GIS slug as approximation
    return _city_to_slug(geo)


def _yandex_city_id(geo: str) -> int | None:
    """Return the Yandex geo-object ID for a city, or None if unknown.

    Fix #1 [geo]: used to build the correct Yandex Maps URL
    (/{city_id}/{slug}/search/…) instead of hardcoding 67 (Tomsk).
    """
    city = (geo or "").strip().lower().replace("ё", "е")
    return _YANDEX_CITY_ID_MAP.get(city)


def _search_yandex_maps_scrape(niche: str, geo: str, limit: int) -> list[dict]:
    """Scrape Yandex.Maps public search page for business listings.

    Same principle as _search_2gis_scrape — zero API quota consumed.
    Each result page has ~15 business-snippet tiles rendered server-side.
    """
    slug = _yandex_city_slug(geo)
    if not slug:
        return []
    # Fix #1 [geo]: resolve the real Yandex city ID for this geography.
    # Previously 67 (Tomsk) was hardcoded here — every non-Tomsk project
    # silently received Tomsk results. If the city ID is unknown, skip the
    # scrape rather than returning results for the wrong city.
    city_id = _yandex_city_id(geo)
    if city_id is None:
        logger.debug("Yandex scrape: no city_id for geo=%r, skipping", geo)
        return []

    cache_k = _cache_key("yandex_scrape", niche, slug, str(limit))
    r_redis = _get_redis()
    if r_redis:
        try:
            cached = r_redis.get(cache_k)
            if cached is not None:
                logger.info("Yandex scrape cache HIT for %r/%r", niche, slug)
                return _json.loads(cached)
        except Exception:
            pass

    # Fix #1 [geo]: use the resolved city_id instead of the hardcoded 67 (Tomsk).
    url = f"https://yandex.ru/maps/{city_id}/{slug}/search/{quote_plus(niche)}"
    headers = {
        # Mobile UA returns ~30 business-snippet tiles per page instead of 15
        # with desktop UA — Yandex serves a denser mobile layout in server HTML.
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
    except Exception:
        return []
    if resp.status_code != 200 or len(resp.text) < 10000:
        return []
    html = resp.text

    # Tiles are in business-snippet blocks — 3 fields each (name, category, address)
    snippet_texts = re.findall(
        r'class="[^"]*business-snippet[^"]*"[^>]*>([^<]+)<',
        html,
    )
    # Group by 3: [name, category, address]
    results: list[dict] = []
    for i in range(0, len(snippet_texts) - 2, 3):
        name = snippet_texts[i].strip()
        category = snippet_texts[i + 1].strip()
        address = snippet_texts[i + 2].strip()
        # Filter: address must contain street markers
        if not re.search(r"(ул\.|пр\.|просп\.|проспект|пер\.|переулок|пл\.|площадь|ш\.|шоссе|бульвар|набережная|наб\.|д\.|тракт)", address.lower()):
            continue
        # Filter junk names
        if len(name) < 3 or name.lower() in ("реклама", "подробнее"):
            continue
        results.append({
            "company": name[:180],
            "city": geo.strip(),
            "website": "",
            "domain": "",
            "phone": "",
            "source_url": url,
            "snippet": f"{category} {address}".strip()[:400],
            "address": address[:300],
            "categories": [category] if category else [],
            "demo": False,
            "source": "yandex_maps",
            "firm_id": "",
        })
        if len(results) >= limit:
            break

    if results and r_redis:
        try:
            r_redis.set(cache_k, _json.dumps(results, ensure_ascii=False, default=str), ex=_CACHE_TTL_SECONDS)
        except Exception:
            pass

    logger.info("Yandex scrape: %d results for %r in %s", len(results), niche, slug)
    return results


# ─── Rusprofile.ru — Russian legal-entity registry ──────────────────────────
# Returns ООО/ИП names with INN/OGRN. Phones/emails are JS-rendered (not in
# server HTML), so we use this only for additional company-name discovery.
# These names can then be searched in 2GIS for contacts.

_RUSPROFILE_ANCHOR_RE = re.compile(
    r'<a[^>]+href="/id/(\d+)"[^>]*class="[^"]*list-element__title[^"]*"[^>]*>(.*?)</a>',
    re.DOTALL,
)


def _search_rusprofile(niche: str, geo: str, limit: int) -> list[dict]:
    """Search rusprofile.ru for legal entities matching the niche+geo.

    Returns up to `limit` candidates with company name + city + INN-like ID.
    No phones/emails (JS-rendered) — those come from later 2GIS lookup.
    """
    global _RUSPROFILE_BLOCKED
    if _RUSPROFILE_BLOCKED:
        # Process-scoped breaker — once Cloudflare/captcha/IP-block kicks in,
        # 24× scrapes per search just multiply the wait. Cleared on next worker
        # restart (i.e. next deploy) — by then the IP reputation may have reset.
        return []

    cache_k = _cache_key("rusprofile", niche, geo, str(limit))
    r_redis = _get_redis()
    if r_redis:
        try:
            cached = r_redis.get(cache_k)
            if cached is not None:
                logger.info("Rusprofile cache HIT for %r/%r", niche, geo)
                return _json.loads(cached)
        except Exception:
            pass

    query = f"{niche} {geo}".strip() if geo else niche
    url = f"https://www.rusprofile.ru/search?query={quote_plus(query)}"
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url, headers={
                "User-Agent": _BROWSER_UAS[0],
                "Accept": "text/html,application/xhtml+xml;q=0.9",
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Accept-Encoding": "gzip, deflate",
            })
    except Exception as exc:
        logger.info("Rusprofile fetch failed for %r: %s", query, exc)
        return []
    if resp.status_code in (403, 429):
        # Server-side block — sticky, so flip the breaker and alert ops once.
        _RUSPROFILE_BLOCKED = True
        try:
            from app.services.notifications import send_alert
            send_alert(
                "warning",
                f"Rusprofile blocked (HTTP {resp.status_code})",
                "Server is rejecting our IP — captcha or rate-limit. "
                "Disabling rusprofile for this worker until restart.",
                key=f"rusprofile_blocked_{resp.status_code}",
                throttle_seconds=3600,
            )
        except Exception:
            pass
        return []
    if resp.status_code != 200 or len(resp.text) < 1000:
        return []

    results: list[dict] = []
    seen: set[str] = set()
    for m in _RUSPROFILE_ANCHOR_RE.finditer(resp.text):
        rusprofile_id = m.group(1)
        body = m.group(2)
        # Strip HTML tags from body (it has nested <span> for highlights)
        clean_name = re.sub(r"<[^>]+>", "", body)
        clean_name = re.sub(r"\s+", " ", clean_name).strip()
        # Strip leading "ООО" type prefix to make the name searchable in 2GIS
        # Keep the legal form for display though
        if not clean_name or len(clean_name) < 4:
            continue
        # Normalize: collapse repeated quotes
        clean_name = clean_name.replace('""', '"')
        # Dedup by lowercased name (rusprofile sometimes lists branches with same name)
        dedup_key = clean_name.lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        results.append({
            "company": clean_name[:180],
            "city": geo.strip(),
            "website": "",
            "domain": "",
            "phone": "",
            "source_url": url,
            "snippet": f"Юрлицо из rusprofile (id={rusprofile_id})",
            "address": "",
            "demo": False,
            "source": "rusprofile",
            "firm_id": "",  # rusprofile_id is not a 2GIS firm_id
            "rusprofile_id": rusprofile_id,
        })
        if len(results) >= limit:
            break

    if results and r_redis:
        try:
            r_redis.set(cache_k, _json.dumps(results, ensure_ascii=False, default=str), ex=_CACHE_TTL_SECONDS)
        except Exception:
            pass

    logger.info("Rusprofile: %d results for %r in %s", len(results), niche, geo)
    return results


_CITY_TO_REGION: dict[str, str] = {
    "москва": "Московская область",
    "санкт-петербург": "Ленинградская область",
    "спб": "Ленинградская область",
    "новосибирск": "Новосибирская область",
    "екатеринбург": "Свердловская область",
    "казань": "Республика Татарстан",
    "нижний новгород": "Нижегородская область",
    "челябинск": "Челябинская область",
    "красноярск": "Красноярский край",
    "самара": "Самарская область",
    "омск": "Омская область",
    "уфа": "Республика Башкортостан",
    "ростов-на-дону": "Ростовская область",
    "ростов": "Ростовская область",
    "пермь": "Пермский край",
    "волгоград": "Волгоградская область",
    "воронеж": "Воронежская область",
    "краснодар": "Краснодарский край",
    "саратов": "Саратовская область",
    "тюмень": "Тюменская область",
    "тольятти": "Самарская область",
    "ижевск": "Удмуртская Республика",
    "барнаул": "Алтайский край",
    "ульяновск": "Ульяновская область",
    "иркутск": "Иркутская область",
    "хабаровск": "Хабаровский край",
    "ярославль": "Ярославская область",
    "владивосток": "Приморский край",
    "махачкала": "Республика Дагестан",
    "томск": "Томская область",
    "оренбург": "Оренбургская область",
    "кемерово": "Кемеровская область",
    "новокузнецк": "Кемеровская область",
    "рязань": "Рязанская область",
    "астрахань": "Астраханская область",
    "пенза": "Пензенская область",
    "липецк": "Липецкая область",
    "тула": "Тульская область",
    "киров": "Кировская область",
    "чебоксары": "Чувашская Республика",
    "калининград": "Калининградская область",
    "брянск": "Брянская область",
    "курск": "Курская область",
    "иваново": "Ивановская область",
    "магнитогорск": "Челябинская область",
    "тверь": "Тверская область",
    "ставрополь": "Ставропольский край",
    "симферополь": "Республика Крым",
    "белгород": "Белгородская область",
    "архангельск": "Архангельская область",
    "владимир": "Владимирская область",
    "сочи": "Краснодарский край",
    "курган": "Курганская область",
    "смоленск": "Смоленская область",
    "калуга": "Калужская область",
    "чита": "Забайкальский край",
    "орел": "Орловская область",
    "вологда": "Вологодская область",
    "якутск": "Республика Саха",
    "сургут": "ХМАО",
    "владикавказ": "Республика Северная Осетия",
    "грозный": "Чеченская Республика",
}


def _region_of(place: str) -> str:
    """Normalize a city OR region string to its federal-subject name (lowercased).

    'Москва' → 'московская область'; 'г. Санкт-Петербург' → 'ленинградская
    область'; 'Томская область' → 'томская область'.

    Returns '' when it cannot classify the string (empty, or an unknown city).
    Callers MUST treat '' as "don't know" — never as a mismatch — so leads with
    a blank/unfamiliar city are kept, not dropped.
    """
    p = _normalize_match_text(place or "")
    if not p:
        return ""
    # Federal DISTRICTS (ЦФО, СЗФО, ...) span many subjects — that's "don't
    # know which subject", not a subject itself. Without this, a Yandex row
    # whose city parsed as «Центральный федеральный округ» hard-mismatched
    # every specific region and got disqualified.
    if "федеральн" in p and "округ" in p:
        return ""
    # Already a federal subject (область / край / республика / округ).
    if any(tok in p for tok in ("област", "край", "республик", "округ", "автономн")):
        return p
    # A known major city → its region. Whole-word match so 'москва' doesn't
    # fire inside 'московская' and 'ростов' doesn't swallow unrelated tokens.
    for city, region in _CITY_TO_REGION.items():
        if re.search(rf"\b{re.escape(city)}\b", p):
            return region.lower()
    return ""


def _geo_tiers(geo: str) -> list[str]:
    """Return geographic fallback tiers from narrow to broad.
    'Томск' → ['Томск', 'Томская область']   (city → its federal subject)
    'Томская область' → ['Томская область']  (already a region — no broader tier)
    'Россия' → ['Россия']
    Empty → ['']

    We deliberately DO NOT escalate a specific geography up to 'Россия'.
    That used to fan the map search out across Москва/СПб/16 major cities and
    merge those leads back WITHOUT any geo filter — so a project scoped to
    'Томская область' ended up with its top filled by Moscow/SPb meat-combines
    (high contact-completeness scores beat sparse on-region farms). Returning
    fewer, on-region leads is correct for a geo-targeted search. A user who
    truly wants the whole country sets geography='Россия' explicitly, which
    still fans out as before.
    """
    geo_clean = (geo or "").strip()
    if not geo_clean:
        return [""]
    if geo_clean.lower() == "россия":
        return ["Россия"]
    tiers = [geo_clean]
    region = _CITY_TO_REGION.get(geo_clean.lower())
    if region and region not in tiers:
        tiers.append(region)
    return tiers


# Largest RU cities by population / business density. When a project is set to
# "Россия" (nationwide) the geo-aware map sources (2GIS, Yandex Maps) CANNOT
# search a whole country in one call — they're city-scoped and return 404 for
# "Россия". So for nationwide searches we fan the map queries out across these
# cities and aggregate. Ordered by lead density so the oversample cap is hit
# from the richest markets first.
# Administrative centre of every Russian federal subject + the largest metros,
# roughly ordered by business density. When a project is "Россия" (nationwide)
# the geo-aware map sources (2GIS/Yandex) can't search a whole country in one
# call, so we fan out across ALL of these — giving genuine all-regions coverage
# (not just Москва/СПб). The fan-out caps per-city and rotates the start point
# across runs so successive doses sweep different regions.
_MAJOR_RU_CITIES = [
    # Metros (highest density) — always queried first.
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург",
    "Казань", "Нижний Новгород", "Челябинск", "Самара",
    "Краснодар", "Ростов-на-Дону", "Уфа", "Пермь",
    "Воронеж", "Волгоград", "Красноярск", "Тюмень",
    # All remaining regional centres (every federal subject).
    "Ижевск", "Саратов", "Барнаул", "Ульяновск", "Иркутск", "Хабаровск",
    "Владивосток", "Ярославль", "Махачкала", "Томск", "Оренбург", "Кемерово",
    "Рязань", "Астрахань", "Пенза", "Липецк", "Киров", "Чебоксары",
    "Калининград", "Тула", "Курск", "Ставрополь", "Улан-Удэ", "Тверь",
    "Брянск", "Иваново", "Белгород", "Владимир", "Архангельск", "Чита",
    "Калуга", "Смоленск", "Якутск", "Саранск", "Вологда", "Курган",
    "Орёл", "Грозный", "Мурманск", "Тамбов", "Петрозаводск", "Кострома",
    "Нальчик", "Йошкар-Ола", "Сыктывкар", "Псков", "Великий Новгород",
    "Благовещенск", "Майкоп", "Южно-Сахалинск", "Абакан", "Элиста",
    "Черкесск", "Кызыл", "Горно-Алтайск", "Биробиджан", "Салехард",
    "Ханты-Мансийск", "Магадан", "Нарьян-Мар", "Магас", "Симферополь",
    "Севастополь",
]

# Near-abroad / CIS capitals — covered by 2GIS/Yandex Maps in those countries.
# Used when the project geography is "СНГ" / "ближнее зарубежье".
_CIS_CAPITALS = [
    "Минск", "Алматы", "Астана", "Ташкент", "Баку",
    "Ереван", "Бишкек", "Тбилиси", "Кишинёв",
]

_NATIONWIDE_GEOS = {"", "россия", "рф", "ru", "russia", "вся россия", "по россии"}
_CIS_GEOS = {"снг", "ближнее зарубежье", "зарубежье", "страны снг",
             "россия и снг", "снг и россия", "россия + снг"}

# Rotates the region fan-out start across runs so successive nationwide doses
# sweep different regions (combined with warehouse no-repeat → full coverage
# over time). Process-lifetime counter; the first N metros stay fixed for density.
_FANOUT_METRO_HEAD = 8
_nationwide_rotation = 0


def _is_broad_geo(geo: str) -> bool:
    """True for country-wide / multi-region geographies (Россия, СНГ) where the
    per-region geo guard must NOT disqualify out-of-one-region candidates."""
    g = (geo or "").strip().lower()
    return g in _NATIONWIDE_GEOS or g in _CIS_GEOS


def _maps_geo_targets(geo: str) -> list[str]:
    """Cities to actually query the map sources with.

    A specific city → [that city] (unchanged behaviour).
    Nationwide ("Россия"/empty) → fan out across ALL regional centres.
    "СНГ"/"ближнее зарубежье" → all RU regional centres + CIS capitals.
    """
    g = (geo or "").strip().lower()
    if g in _NATIONWIDE_GEOS:
        return list(_MAJOR_RU_CITIES)
    if g in _CIS_GEOS:
        return list(_MAJOR_RU_CITIES) + list(_CIS_CAPITALS)
    return [geo]


def search_leads(
    query: str,
    limit: int,
    *,
    niche: str = "",
    geography: str = "",
    segments: list[str] | None = None,
    prompt: str = "",
    excluded_segments: list[str] | None = None,
    website_preference: str = "any",
    use_yandex: bool = True,
    organization_id: str | None = None,
    deep_pages: bool = False,
) -> list[dict]:
    """Public entry point. Runs the single-tier search, and if the result
    set is materially below target, also probes the broader geographic
    tiers (city → region → Россия) to fill the gap.

    A thin tier-cascade rather than a 'big-bang' one-pass: avoids needless
    cost when the city already has plenty, but rescues thin-niche searches
    (e.g. 'птицефабрика в Урюпинске' → fallback to oblast → to country).

    `organization_id` flows down to the LLM filter so AI calls inside the
    candidate-relevance pass are metered against this org's monthly cap.
    """
    initial = _search_leads_one_tier(
        query, limit,
        niche=niche, geography=geography, segments=segments,
        prompt=prompt, excluded_segments=excluded_segments,
        website_preference=website_preference, use_yandex=use_yandex,
        organization_id=organization_id, deep_pages=deep_pages,
    )
    # If we already have a healthy chunk OR geography is 'Россия' (no broader
    # tier to expand to), return as-is.
    target_floor = max(limit // 2, 30)
    if len(initial) >= target_floor or (geography or "").strip().lower() in ("россия", "", "ru"):
        return initial[:limit]

    tiers = _geo_tiers(geography)
    if len(tiers) <= 1:
        return initial[:limit]

    seen_domains: set[str] = {r.get("domain", "") for r in initial if r.get("domain")}
    seen_companies: set[str] = {
        _normalize_match_text(r.get("company", "")) for r in initial if r.get("company")
    }
    merged: list[dict] = list(initial)

    # Probe the next tier (region). If still thin, escalate to country.
    for tier_geo in tiers[1:]:
        if len(merged) >= limit:
            break
        remaining = limit - len(merged)
        extra = _search_leads_one_tier(
            query, remaining,
            niche=niche, geography=tier_geo, segments=segments,
            prompt=prompt, excluded_segments=excluded_segments,
            website_preference=website_preference, use_yandex=use_yandex,
            organization_id=organization_id, deep_pages=deep_pages,
        )
        if not extra:
            continue
        for r in extra:
            d = r.get("domain", "")
            c = _normalize_match_text(r.get("company", ""))
            if d and d in seen_domains:
                continue
            if c and c in seen_companies:
                continue
            if d:
                seen_domains.add(d)
            if c:
                seen_companies.add(c)
            merged.append(r)
            if len(merged) >= limit:
                break
        logger.info(
            "Geo-tier fallback: tier=%r added %d new (running total %d/%d)",
            tier_geo, len(extra), len(merged), limit,
        )
        if len(merged) >= target_floor:
            break  # good enough; don't escalate further

    return merged[:limit]


def _search_leads_one_tier(query: str, limit: int, *, niche: str = "", geography: str = "", segments: list[str] | None = None, prompt: str = "", excluded_segments: list[str] | None = None, website_preference: str = "any", use_yandex: bool = True, organization_id: str | None = None, deep_pages: bool = False) -> list[dict]:
    effective_niche = (niche or query).strip()
    effective_geo = geography.strip()
    effective_segments = segments or []

    collected: list[dict] = []
    searxng_accessible = False
    skipped_irrelevant = 0
    oversample_limit = max(limit * 5, limit + 50)

    # Fix [unique-cap]: oversample-кап считает только УНИКАЛЬНЫЕ ключи
    # (base-домен либо имя|город — та же схема, что в _finalize_candidates).
    # Дубли между источниками по-прежнему ДОБАВЛЯЮТСЯ в collected (они нужны
    # _finalize_candidates для слияния полей), но кап больше не съедают:
    # раньше maps+rusprofile, отработав ПЕРЕД SearXNG, забивали кап в т.ч.
    # дублями, и веб-проход — единственный источник сайтов/email — получал
    # ноль запросов («лиды без сайтов» в плотных нишах).
    unique_keys: set[str] = set()
    unique_count = 0
    # Fix [web-reserve]: веб-проходу (SearXNG/Bing) гарантирован собственный
    # бюджет — он добирает min(limit, 30) уникальных веб-кандидатов, даже
    # если кап уже заполнен картами.
    web_reserve = min(limit, 30)
    if website_preference == "no_website":
        # Веб-поиск по определению возвращает компании С сайтами — для
        # «клиентов без сайта» проход пропускается целиком (см. ниже), и
        # резерв ему не положен: карты/реестры получают весь кап.
        web_reserve = 0
    web_unique = 0

    # Build list of specific search terms for maps (2GIS, Yandex)
    # When segments are specific business types (e.g. "птицефабрика", "ветклиника"),
    # search each one separately — much more effective than a combined query.
    has_prompt = bool((prompt or "").strip())
    map_search_terms = []
    if effective_segments:
        # 24 segments per maps source. With 2GIS+Yandex_scrape+Yandex_API+rusprofile
        # firing per term, this is the wide net that gets us 100+ candidates.
        for seg in effective_segments[:24]:
            seg = seg.strip()
            if seg and len(seg) > 2:
                map_search_terms.append(seg)
    if not map_search_terms:
        # If user provided a prompt but the enhancer returned NO segments
        # (unknown niche, e.g. "Продаю мраморные подоконники"), we must NOT
        # fall back to the niche as a maps term — that floods results with
        # sellers. Better to return empty from maps and let SearXNG/registry
        # passes do what they can with the prompt text itself.
        if has_prompt:
            map_search_terms = []
        else:
            map_search_terms = [effective_niche]

    def _candidate_key(item: dict) -> str:
        """Дедуп-ключ кандидата — зеркало логики _finalize_candidates."""
        domain = item.get("domain") or extract_domain(item.get("website", ""))
        bd = get_base_domain(domain) if domain else ""
        if bd:
            return bd
        name = (item.get("company") or "").lower().strip()
        if not name:
            return ""
        city = (item.get("city") or "").lower().strip()
        return f"{name}|{city}" if city else name

    def _cap_full() -> bool:
        return unique_count >= oversample_limit

    def collect_candidates(source_items: list[dict], *, is_web: bool = False) -> None:
        nonlocal skipped_irrelevant, unique_count, web_unique
        for item in source_items:
            scored = _score_candidate(item, effective_niche, effective_geo, effective_segments)
            if scored.get("relevance_score", -999) < _MIN_RELEVANCE_SCORE:
                skipped_irrelevant += 1
                continue
            # Требование к сайту («без сайтов», инцидент 14.07) — жёсткий
            # фильтр, а не скоринговый нюанс: перекос "+8 за сайт" ниже по
            # конвейеру иначе систематически хоронит бездоменных.
            if website_preference == "no_website" and (scored.get("domain") or "").strip():
                skipped_irrelevant += 1
                continue
            if website_preference == "with_website" and not (scored.get("domain") or "").strip():
                skipped_irrelevant += 1
                continue
            key = _candidate_key(scored)
            is_dup = bool(key) and key in unique_keys
            if not is_dup and _cap_full():
                # Кап полон. Веб-источникам разрешаем добор в счёт резерва —
                # см. fix [web-reserve].
                if not (is_web and web_unique < web_reserve):
                    break
            collected.append(scored)
            if not is_dup:
                if key:
                    unique_keys.add(key)
                unique_count += 1
                if is_web:
                    web_unique += 1

    # Search maps with each segment separately for better results
    per_term_limit = max(oversample_limit // max(len(map_search_terms), 1), 20)

    # Does the org have a working 2GIS API key? We check once per search_leads
    # call so we don't rediscover missing-key state on every term.
    _twogis_api_settings = get_settings()
    _twogis_api_available = bool(_twogis_api_settings.twogis_api_key)

    # Geo fan-out: a specific city queries just that city; a nationwide
    # ("Россия") search fans out across major cities, because 2GIS / Yandex
    # Maps cannot resolve a country to a city_id (they 404 on "Россия").
    # The oversample cap below stops the fan-out early once we have enough,
    # so popular niches fill from Москва+СПб while thin niches work through
    # more cities to reach target.
    maps_geo_targets = _maps_geo_targets(effective_geo)
    # Nationwide / CIS: spread the budget across regions instead of draining it
    # on Москва+СПб. Rotate the non-metro tail per run, and cap each city's
    # contribution so a single dose touches many regions.
    nationwide_fanout = _is_broad_geo(effective_geo) and len(maps_geo_targets) > 1
    per_city_cap = oversample_limit
    if nationwide_fanout:
        if len(maps_geo_targets) > _FANOUT_METRO_HEAD:
            global _nationwide_rotation
            head = maps_geo_targets[:_FANOUT_METRO_HEAD]
            tail = maps_geo_targets[_FANOUT_METRO_HEAD:]
            off = _nationwide_rotation % len(tail)
            maps_geo_targets = head + tail[off:] + tail[:off]
            _nationwide_rotation += 1
        # ~15-20 regions per dose; ≥3 so small doses still spread.
        per_city_cap = max(3, oversample_limit // 15)
    for map_geo in maps_geo_targets:
        if _cap_full():
            break
        _city_start_count = unique_count
        for term in map_search_terms:
            if _cap_full():
                break
            if nationwide_fanout and (unique_count - _city_start_count) >= per_city_cap:
                break  # this region got its slice — move on to the next region
            # 2GIS: API first (licensed, stable, legally clean), public-scrape
            # only as a last-resort fallback if the API key is missing or returns
            # nothing. Previously scrape was primary — faster but violates 2GIS
            # ToS and risks captcha/IP bans and a civil claim under ст.1334 ГК РФ
            # (database rights).
            try:
                if not _cap_full():
                    twogis_results: list[dict] = []
                    used_source = ""
                    if _twogis_api_available:
                        twogis_results = _search_2gis(term, map_geo, per_term_limit)
                        used_source = "2gis_api"
                    if not twogis_results:
                        # No API key, or API returned empty (e.g. unknown city) —
                        # fall back to public-page scrape. This is the legacy path
                        # kept as a safety net; we log a warning so ops notices if
                        # the API key needs top-up.
                        if _twogis_api_available:
                            logger.warning(
                                "2GIS API returned 0 results for '%s %s' — falling back to scrape",
                                term, map_geo,
                            )
                        twogis_results = _search_2gis_scrape(term, map_geo, per_term_limit)
                        used_source = "2gis_scrape"
                    collect_candidates(twogis_results)
                    if twogis_results:
                        logger.info(
                            "2GIS returned %d results for '%s %s' via %s",
                            len(twogis_results), term, map_geo, used_source,
                        )
            except Exception:
                logger.warning("2GIS search error for '%s'", term, exc_info=True)

            # Yandex Maps scrape — parallel free source. Adds coverage for firms
            # that Yandex indexes better than 2GIS (especially newer/smaller businesses).
            try:
                if not _cap_full():
                    yandex_scrape_results = _search_yandex_maps_scrape(term, map_geo, per_term_limit)
                    collect_candidates(yandex_scrape_results)
                    if yandex_scrape_results:
                        logger.info("Yandex scrape returned %d results for '%s %s'",
                                    len(yandex_scrape_results), term, map_geo)
            except Exception:
                logger.warning("Yandex scrape error for '%s'", term, exc_info=True)

            # Rusprofile.ru — PRIMARY legal-entity source (not just supplementary).
            # Every term gets 20 entities. Real ФНС-registered ЮЛ/ИП → downstream
            # enrichment (website + 2GIS-card fallback) fills in contacts. This
            # turns a thin "12 leads" search into 100+ legitimate buyers.
            # Previously this was gated behind `collected < limit // 3`, which
            # essentially disabled it for any decent-sized search.
            try:
                if not _cap_full():
                    rp_results = _search_rusprofile(term, map_geo, 20)
                    collect_candidates(rp_results)
                    if rp_results:
                        logger.info(
                            "Rusprofile returned %d results for '%s %s'",
                            len(rp_results), term, map_geo,
                        )
            except Exception:
                logger.warning("Rusprofile error for '%s'", term, exc_info=True)

            time.sleep(0.2)

        # Yandex Maps API — fix [yandex-budget]: ОДИН вызов на гео со всем
        # списком сегментов и бюджетом из остатка oversample-окна. Раньше
        # вызов сидел внутри цикла по term — до 24 идентичных прогонов на
        # город (билдер запросов игнорирует term в buyer-hunt режиме), где
        # ранний break отдавал весь бюджет первому сегменту. Распределение
        # бюджета по сегментам — внутри _search_yandex_maps; ключ отключается
        # circuit-breaker'ом на 401/403/429 (см. _YANDEX_DEAD_KEY).
        # Без гейта _cap_full(): Яндекс — единственный API-источник телефонов
        # и сайтов (проверено живьём на тарифе), поэтому получает
        # гарантированный минимум бюджета даже при заполненном капе — иначе в
        # плотных нишах бесплатный 2ГИС (без контактов) вытесняет его всегда.
        if use_yandex and map_search_terms:
            try:
                # Nationwide: cap Yandex per region too (don't let Москва eat
                # the whole quota); otherwise grab the remaining headroom.
                yandex_budget = (
                    min(per_city_cap, max(oversample_limit - unique_count, 8))
                    if nationwide_fanout else max(oversample_limit - unique_count, 20)
                )
                yandex_results = _search_yandex_maps(
                    effective_niche, map_geo, effective_segments, yandex_budget,
                    has_prompt=has_prompt, organization_id=organization_id,
                )
                collect_candidates(yandex_results)
                if yandex_results:
                    logger.info(
                        "Yandex Maps API returned %d results for '%s' (%d segments, budget %d)",
                        len(yandex_results), map_geo, len(effective_segments), yandex_budget,
                    )
            except Exception:
                logger.warning("Yandex Maps API error for '%s'", map_geo, exc_info=True)

    try:
        if website_preference == "no_website":
            raise _SkipWebPass()  # веб-поиск находит только компании С сайтами
        queries = _build_discover_queries(effective_niche, effective_geo, effective_segments, has_prompt=bool(prompt))
        settings = get_settings()
        local_seen_domains: set[str] = set()

        # Fix [web-reserve]: веб-проход не останавливается по капу, пока не
        # доберёт свой резерв (min(limit, 30) уникальных веб-кандидатов) —
        # это единственный источник сайтов и, значит, email.
        def _web_pass_done() -> bool:
            return _cap_full() and web_unique >= web_reserve

        # Основной веб-источник — Yandex Search API v2 (если ключ настроен);
        # иначе SearXNG. На первой ошибке API разово откатываемся на SearXNG,
        # чтобы временный сбой Яндекса не оставил проход без веб-источника.
        use_yandex_search = _yandex_search_configured(settings)
        client_timeout = (
            settings.yandex_search_timeout_seconds if use_yandex_search
            else settings.searxng_timeout_seconds
        )
        yandex_used = use_yandex_search  # был ли Яндекс основным на старте прохода
        yx_requests = 0                  # платные запросы Yandex Search за проход
        # Глубина выдачи: базово web_search_pages (3); на повторных сборах
        # (deep_pages, у проекта уже много компаний) — web_search_pages_deep,
        # чтобы хвост выдачи тоже прочёсывался и ниша «истощалась» позже.
        # Кап платных запросов _YANDEX_SEARCH_MAX_REQ_PER_TIER остаётся жёстким.
        _pages_cap = max(1, int(getattr(
            settings, "web_search_pages_deep" if deep_pages else "web_search_pages", 3
        )))
        with httpx.Client(timeout=client_timeout, follow_redirects=True) as client:
            for search_query in queries:
                if _web_pass_done():
                    break
                for page_num in range(1, _pages_cap + 1):
                    if use_yandex_search:
                        # Кап на платные запросы: на разреженной нише резерв
                        # веб-прохода может не набраться, и без капа fan-out
                        # запросов (до 24 сегм.×3 стр.) сжёг бы деньги впустую.
                        if yx_requests >= _YANDEX_SEARCH_MAX_REQ_PER_TIER:
                            logger.info(
                                "Yandex Search: достигнут кап %d запросов на проход — стоп",
                                _YANDEX_SEARCH_MAX_REQ_PER_TIER,
                            )
                            break
                        yx_requests += 1
                        try:
                            items = _yandex_search_fetch_page(client, search_query, page_num, settings)
                        except Exception as exc:
                            logger.warning(
                                "Yandex Search API failed (%s) — откат на SearXNG на этот проход",
                                type(exc).__name__,
                            )
                            use_yandex_search = False
                            items = _searxng_fetch_page(client, search_query, page_num, settings)
                    else:
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

                    collect_candidates(page_items, is_web=True)
                    time.sleep(0.3)
                    if _web_pass_done():
                        break
                if use_yandex_search and yx_requests >= _YANDEX_SEARCH_MAX_REQ_PER_TIER:
                    break
                time.sleep(0.15)
        # Громкий сигнал мисконфига: Яндекс был основным, ни разу не откатились,
        # но веб-проход не дал НИ ОДНОГО сайта — почти наверняка ключ/folder/
        # биллинг (иначе тихо теряли бы единственный источник email).
        if yandex_used and use_yandex_search and web_unique == 0:
            logger.warning(
                "Yandex Search настроен, но веб-проход вернул 0 сайтов за %d запросов — "
                "проверьте ключ/folder/биллинг (docs/yandex-search-api-setup.md)",
                yx_requests,
            )
        searxng_accessible = True
    except _SkipWebPass:
        logger.info("web pass skipped: website_preference=no_website")
    except Exception:
        logger.exception("web search pass failed")

    try:
        # Fix [web-reserve]: тот же резерв действует и для Bing-гейта.
        # (no_website: Bing, как и весь веб-проход, находит только сайты.)
        if website_preference != "no_website" and (not _cap_full() or web_unique < web_reserve):
            # Bing backup — segment-aware when we have prompt-driven targets.
            # Previously we searched `{niche} компания {geo}` unconditionally,
            # which brings sellers of the niche for prompt-driven projects.
            if has_prompt and effective_segments:
                # Segment-driven: iterate first 3 segments.
                # Fix [neg-per-segment]: негативы — по каждому сегменту отдельно.
                bing_queries = [
                    f"{seg.strip()} {effective_geo} {_pick_negatives(has_prompt=True, segments=[seg])}".strip()
                    for seg in effective_segments[:3]
                    if seg and seg.strip()
                ]
            else:
                neg = _pick_negatives(has_prompt=has_prompt, segments=effective_segments)
                bing_queries = [f"{effective_niche} компания {effective_geo} {neg}".strip()]
            per_q_limit = max(5, (oversample_limit - unique_count) // max(1, len(bing_queries)))
            for bing_query in bing_queries:
                if _cap_full() and web_unique >= web_reserve:
                    break
                bing_results = _search_bing(bing_query, per_q_limit)
                collect_candidates(bing_results, is_web=True)
    except Exception:
        logger.warning("Bing search error", exc_info=True)

    if skipped_irrelevant:
        logger.info("Filtered out %d irrelevant results for niche='%s'", skipped_irrelevant, effective_niche)

    # Fix [llm-refill]: финализируем с буфером 2×limit — LLM-фильтр срезает
    # 30-40%, и раньше недобор никогда не пополнялся из отброшенного
    # оверсэмпла (truncate ДО фильтра). Оба фильтра (_ai_filter и
    # _rule_based_competitor_filter) сохраняют исходный порядок кандидатов
    # (проверено), поэтому срез [:limit] ПОСЛЕ фильтра отдаёт тот же топ.
    ranked = _finalize_candidates(collected, limit * 2)
    if ranked:
        from app.services.llm_filter import filter_candidates_llm
        ranked = filter_candidates_llm(
            ranked, effective_niche, effective_geo, effective_segments,
            prompt=prompt, excluded_segments=excluded_segments,
            website_preference=website_preference,
            organization_id=organization_id,
        )
        return ranked[:limit]
    # Never generate fake/synthetic leads — return empty list so callers see
    # real zero-result state and can act accordingly.
    return []


_ANCHOR_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_CONTACT_LINK_KW = ("контакт", "contact", "kontakt", "связ", "реквизит", "о компании", "o-kompanii", "about")

# ── Соцсети компании (VK / Telegram) ────────────────────────────────────────
# Для компаний «без сайта» и малого бизнеса группа VK — часто единственный
# digital-канал; для менеджера это дополнительный способ связаться с лидом.
# Сервисные пути VK (share/away/video/wall/…) и telegram-виджеты отсекаются.
_VK_LINK_RE = re.compile(
    # Лукахед заякорен (ревью 21.07): «share»/«video»/… режутся только как
    # ЦЕЛЫЙ сегмент (share.php, video-123), а легитимные ники с таким
    # префиксом (sharemarket, videostudio70) проходят.
    r"https?://(?:www\.|m\.)?vk\.com/"
    r"(?!(?:share|away|images|video|wall|feed|app\d|widget|dev|id0)(?![A-Za-z]))"
    r"[A-Za-z0-9_.\-]{3,64}",
    re.IGNORECASE,
)
_TG_LINK_RE = re.compile(
    # Инвайты t.me/joinchat/… и t.me/+… поддержаны явно (ревью 21.07: раньше
    # joinchat обрезался до нерабочей ссылки t.me/joinchat).
    r"https?://(?:www\.)?t\.me/"
    r"(?:joinchat/[A-Za-z0-9_\-]{10,}|\+[A-Za-z0-9_\-]{10,}"
    r"|(?!share\b|iv\b|joinchat\b)[A-Za-z0-9_]{4,64})",
    re.IGNORECASE,
)


def sanitize_social(kind: str, value: str) -> str:
    """Валидный https-URL соцсети или "". kind: "vk" | "telegram".

    Единая точка защиты (ревью 21.07): значения приходят из чужого HTML и
    2GIS-контактов (голые ники, подписи «Наша группа», произвольные схемы) —
    в лид/склад/href фронта уходит ТОЛЬКО то, что матчит наш регекс соцссылок.
    Бессхемные vk.com/… и t.me/… нормализуются в https://.
    """
    v = (value or "").strip()
    if not v:
        return ""
    low = v.lower()
    if not low.startswith(("http://", "https://")):
        if low.startswith(("vk.com/", "www.vk.com/", "m.vk.com/", "t.me/", "www.t.me/")):
            v = "https://" + v
        else:
            return ""
    rex = _VK_LINK_RE if kind == "vk" else _TG_LINK_RE
    m = rex.match(v)
    return m.group(0).rstrip(".,;)") if m else ""


def _extract_social_links(html: str) -> dict:
    """Первые VK/Telegram ссылки из HTML. {"vk": str, "telegram": str} —
    пустые строки, если не нашли."""
    if not html:
        return {"vk": "", "telegram": ""}
    vk_m = _VK_LINK_RE.search(html)
    tg_m = _TG_LINK_RE.search(html)
    return {
        "vk": (vk_m.group(0) if vk_m else "").rstrip(".,;)"),
        "telegram": (tg_m.group(0) if tg_m else "").rstrip(".,;)"),
    }


def _discover_contact_links(html: str, root_url: str, domain: str) -> list[str]:
    """Find same-domain links to contact/about pages by anchor href OR text.

    Handles non-standard slugs (/kontakty-i-rekvizity, /o-kompanii/kontakty, …)
    that the fixed candidate-path list misses — a major cause of "the site has
    contacts but enrichment returned nothing".
    """
    out: list[str] = []
    for m in _ANCHOR_RE.finditer(html or ""):
        href = m.group(1).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        text = TAG_RE.sub(" ", m.group(2) or "").lower()
        hay = f"{href.lower()} {text}"
        if not any(kw in hay for kw in _CONTACT_LINK_KW):
            continue
        absu = normalize_url(urljoin(root_url.rstrip("/") + "/", href))
        if absu and extract_domain(absu) == domain and absu not in out:
            out.append(absu)
        if len(out) >= 6:
            break
    return out


_META_DESC_RE = re.compile(
    r"<meta[^>]+(?:name=[\"\']description[\"\']|property=[\"\']og:description[\"\'])[^>]*?content=[\"\']([^\"\']{20,})[\"\']",
    re.IGNORECASE | re.DOTALL,
)
_META_DESC_RE_REV = re.compile(
    r"<meta[^>]+content=[\"\']([^\"\']{20,})[\"\'][^>]*?(?:name=[\"\']description[\"\']|property=[\"\']og:description[\"\'])",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]{10,200})</title>", re.IGNORECASE | re.DOTALL)


def _extract_site_description(html: str) -> str:
    """«Чем занимается компания» из HTML главной: meta description /
    og:description (оба порядка атрибутов), фолбэк — <title>. Пустая строка,
    если сайт ничего осмысленного о себе не говорит."""
    if not html:
        return ""
    m = _META_DESC_RE.search(html) or _META_DESC_RE_REV.search(html)
    text = m.group(1) if m else ""
    if not text:
        t = _TITLE_RE.search(html)
        text = t.group(1) if t else ""
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    # Мусорные заглушки не считаем описанием.
    if len(text) < 20 or text.lower() in {"главная", "home", "index"}:
        return ""
    return text[:2000]


def enrich_website_contacts(base_url: str) -> dict:
    parsed = urlparse(base_url if base_url.startswith(("http://", "https://")) else f"https://{base_url}")
    domain = extract_domain(base_url)
    if not domain or is_aggregator_domain(domain):
        return {"emails": [], "phones": [], "addresses": []}
    root_url = f"{parsed.scheme or 'https'}://{domain}"
    # Russian + EN common contact/about pages. Order matters — most likely first.
    # Dropped `/footer` and `/header` — these are CSS/JS fragments, not real URLs.
    candidate_paths = [
        "/",  # home page — often has footer with emails/phones/address
        "/contacts", "/contacts/", "/contact", "/contact/", "/contact-us",
        "/kontakty", "/kontakty/", "/kontakti", "/kontakti/",
        "/about", "/about/", "/about-us", "/o-kompanii", "/o-kompanii/",
        "/o-nas", "/o-nas/",
        "/info", "/info/",
        # Phone often on checkout/order pages for e-commerce-ish B2B
        "/order", "/contacts.html", "/kontakty.html",
    ]
    gathered_text = ""
    gathered_html = ""
    home_html = ""
    pages_fetched = 0
    last_error: str | None = None
    # Fix #2 [robustness]: RobotFileParser.read() uses urllib internally with NO
    # timeout — it can hang a Celery worker forever on a slow/unresponsive host.
    # Fetch robots.txt manually via httpx with an explicit 8 s timeout, then
    # feed the content to parse(). On any failure treat as "all allowed".
    robots: RobotFileParser | None = None
    robots_url = f"{root_url.rstrip('/')}/robots.txt"
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as _rb_client:
            _rb_resp = _rb_client.get(robots_url, headers={"User-Agent": DEFAULT_USER_AGENT})
        if _rb_resp.status_code == 200:
            robots = RobotFileParser()
            robots.set_url(robots_url)
            robots.parse(_rb_resp.text.splitlines())
    except Exception:
        # Any network/timeout error → proceed without robots.txt restriction
        robots = None

    # Fix #3 [security]: SSRF via redirect — _is_safe_url is checked on the
    # initial URL but httpx's automatic redirect-following never re-validates
    # redirect destinations. An attacker-controlled site could 301→ an internal
    # IP (e.g. 169.254.169.254) and exfiltrate cloud metadata.
    # Fix: attach a request event hook that calls _is_safe_url on EVERY request
    # httpx fires (including redirect hops) and raises ValueError to abort the
    # request chain when the destination is unsafe. The hook fires before the
    # TCP connection, so no data is sent to private addresses.
    def _ssrf_guard(request: httpx.Request) -> None:
        if not _is_safe_url(str(request.url)):
            raise ValueError(f"SSRF: unsafe redirect destination blocked: {request.url}")

    # IMPORTANT: follow_redirects=True. Previously False → we dropped pages
    # after a single 301 (http→https, www/non-www, trailing-slash) and got
    # empty HTML. That was the #1 reason enrichment was returning nothing.
    # Bumped timeout 6s → 12s (RU shared-hosting is slow, and this is a
    # Celery worker — latency cost is acceptable for higher coverage).
    try:
        with httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            # Fix #3: hook fires on every request, including redirect hops
            event_hooks={"request": [_ssrf_guard]},
        ) as client:
            # Absolute-URL queue: homepage first, then the known contact paths.
            # While fetching the homepage we DISCOVER real contact-page links
            # (arbitrary slugs) and splice them in next — so we reach the actual
            # «Контакты» page even when it isn't at a standard URL.
            queue: list[str] = [root_url] + [
                normalize_url(f"{root_url}{p}") for p in candidate_paths if p != "/"
            ]
            visited: set[str] = set()
            qi = 0
            MAX_PAGES = 10
            while qi < len(queue) and pages_fetched < MAX_PAGES:
                target = queue[qi]
                qi += 1
                if not target or target in visited:
                    continue
                visited.add(target)
                if not _is_safe_url(target):
                    continue
                if robots and not robots.can_fetch(DEFAULT_USER_AGENT, target):
                    continue
                is_home = target.rstrip("/") == root_url.rstrip("/")
                try:
                    response = None
                    for attempt in range(3):
                        response = client.get(target)
                        if response.status_code in (429, 503):
                            time.sleep(0.3 * (2**attempt))
                            continue
                        break
                    if response is None or response.status_code >= 400:
                        continue
                    # Larger caps: real footers / «Контакты» blocks often sit
                    # AFTER 50k of HTML — truncating there was a top cause of
                    # "site has contacts but enrichment returned nothing".
                    gathered_html += f"\n{response.text[:300000]}"
                    plain_text = TAG_RE.sub(" ", unescape(response.text))
                    gathered_text += f"\n{plain_text[:150000]}"
                    pages_fetched += 1
                    if is_home and not home_html:
                        home_html = response.text[:300000]
                    if is_home:
                        for absu in _discover_contact_links(response.text, root_url, domain):
                            if absu not in visited and absu not in queue:
                                queue.insert(qi, absu)  # prioritise right after home
                except httpx.TimeoutException:
                    last_error = f"timeout on {target}"
                    continue
                except Exception as exc:
                    last_error = f"{type(exc).__name__} on {target}"
                    continue
                time.sleep(0.15)
                # Early exit once both email AND phone are found (saves worker time).
                _has_email = bool(re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", gathered_text))
                _has_phone = bool(re.search(r"\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", gathered_text))
                if _has_email and _has_phone:
                    break
    except Exception as exc:
        logger.warning(
            "enrich_website_contacts: client error for %s — %s",
            base_url, type(exc).__name__,
        )

    result = extract_contacts(gathered_text, gathered_html)
    # «О компании»: meta-description главной — обычно лучший короткий ответ на
    # вопрос «чем занимается компания». Возвращаем отдельным ключом; вызывающие
    # без него живут как раньше (dict.get).
    result["site_description"] = _extract_site_description(home_html)
    # Соцсети компании (VK/Telegram) — дополнительные каналы связи; ключи
    # опциональные, старые вызывающие живут как раньше.
    social = _extract_social_links(gathered_html)
    if social.get("vk"):
        result["vk"] = social["vk"]
    if social.get("telegram"):
        result["telegram"] = social["telegram"]
    logger.info(
        "enrich_website_contacts: %s — %d pages, %d emails, %d phones, %d addresses%s",
        base_url,
        pages_fetched,
        len(result.get("emails", [])),
        len(result.get("phones", [])),
        len(result.get("addresses", [])),
        f" (last_err: {last_error})" if pages_fetched == 0 and last_error else "",
    )
    return result


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
# Russian phone numbers: +7 or 8-prefix. The first 3-digit group MUST be a real
# Russian area code (mobile 9xx, fixed-line 3xx/4xx/8xx) — this filters out
# phantom matches from coordinate floats (84.85134...) and hash strings in URLs
# (868398585595b6b62608.js) that happen to start with 8 or 7.
# The `(?<![\w.\d])` lookbehind blocks matches inside decimals/identifiers.
_PHONE_RE = re.compile(
    r"(?<![\w.\d])"                             # not after digit/dot/word char
    r"(?:\+7|8)"                                 # +7 or 8 prefix
    r"[\s\-()]{0,3}"
    r"(?:[349]\d{2}|800)"                        # valid Russian area code: 3xx/4xx/8xx/9xx (non-capturing)
    r"[\s\-()]{0,3}\d{3}[\s\-()]{0,3}\d{2}[\s\-()]{0,3}\d{2}"
    r"(?![\d.])"                                 # not before digit/dot (avoids coordinate floats)
)
# Fix [phones]: tel:-ссылки часто содержат ФОРМАТИРОВАННЫЙ номер
# («tel:+7 (495) 123-45-67»), а не только слитные цифры — старый паттерн
# `tel:\+?(\d{10,15})` такие пропускал. Захватываем форматированную строку
# целиком и нормализуем ниже.
_TEL_LINK_RE = re.compile(r'tel:([+\d][\d\s\-().]{6,24})', re.IGNORECASE)
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
    # Fix [phones]: местный формат без префикса («(3822) 20-11-36») — 10
    # значащих цифр; код страны 7 подставляем сами (RU по умолчанию). Коды
    # городов/мобильных РФ начинаются с 3/4/8/9 — остальное не трогаем.
    elif len(digits) == 10 and digits[0] in "3489":
        digits = "7" + digits
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


def _fetch_2gis_html(url: str, *, _is_enrich: bool = False) -> str:
    """Fetch a 2gis.ru page with rotating UA + retries + captcha detection.

    Returns empty string on HTTP failure, network error, or captcha interception.
    Retries up to 4 times with exponential backoff on 429/503/captcha.

    Fix #5 [robustness]: _is_enrich=True routes captcha failures to the
    enrichment-specific circuit-breaker (_TWOGIS_SCRAPE_CAPTCHA_FAILS_ENRICH /
    _TWOGIS_SCRAPE_BLOCKED_ENRICH) instead of the search breaker.  Previously
    enrichment captchas shared the search counter and could permanently disable
    _search_2gis_scrape() for the whole worker process.
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
                    # Fix #5: bump the correct counter based on which call path we're in.
                    if _is_enrich:
                        global _TWOGIS_SCRAPE_CAPTCHA_FAILS_ENRICH, _TWOGIS_SCRAPE_BLOCKED_ENRICH
                        _TWOGIS_SCRAPE_CAPTCHA_FAILS_ENRICH += 1
                        if _TWOGIS_SCRAPE_CAPTCHA_FAILS_ENRICH >= 2 and not _TWOGIS_SCRAPE_BLOCKED_ENRICH:
                            _TWOGIS_SCRAPE_BLOCKED_ENRICH = True
                            logger.warning(
                                "2GIS enrich scrape: %d captcha failures, disabling enrich for this worker",
                                _TWOGIS_SCRAPE_CAPTCHA_FAILS_ENRICH,
                            )
                    else:
                        global _TWOGIS_SCRAPE_CAPTCHA_FAILS, _TWOGIS_SCRAPE_BLOCKED
                        _TWOGIS_SCRAPE_CAPTCHA_FAILS += 1
                        if _TWOGIS_SCRAPE_CAPTCHA_FAILS >= 2 and not _TWOGIS_SCRAPE_BLOCKED:
                            _TWOGIS_SCRAPE_BLOCKED = True
                            logger.warning(
                                "2GIS scrape: %d captcha failures, disabling for this worker process",
                                _TWOGIS_SCRAPE_CAPTCHA_FAILS,
                            )
                    # If captcha is hitting us this often, ops should know — but
                    # throttle to 1/15min so a captcha storm doesn't spam Telegram.
                    try:
                        from app.services.notifications import send_alert
                        send_alert(
                            "warning",
                            "2GIS captcha not bypassed",
                            f"4 retries with UA rotation didn't beat captcha. URL: {url[:200]}",
                            key="2gis_captcha_persistent",
                            throttle_seconds=900,
                        )
                    except Exception:
                        pass
                    return ""
                time.sleep(1.0 * (2 ** attempt) + random.random() * 0.5)
                continue
            return body
    return ""


# Company-name stop-words ignored when matching an API search result to a lead.
_NAME_STOP = {
    "ооо", "оао", "зао", "ип", "пао", "нпо", "ао", "тд", "торговый", "дом",
    "компания", "фирма", "группа", "group", "ltd", "llc", "inc",
}


def _name_tokens(s: str) -> set[str]:
    """Meaningful lowercased tokens of a company name (for fuzzy matching)."""
    toks = re.findall(r"[a-zа-яё0-9]+", (s or "").lower())
    return {t for t in toks if len(t) >= 3 and t not in _NAME_STOP}


def _name_match_positions(html: str, company: str) -> list[int]:
    """Позиции вхождений токенов названия компании в html (без учёта регистра).

    Fix [scrape-guard]: основа защиты от «чужого телефона» — страница поиска
    2gis.ru содержит МНОГО компаний, и контакты можно брать только из
    окрестности совпадения имени (тот же _name_tokens-матч, что у API-пути).
    """
    tokens = _name_tokens(company)
    if not tokens:
        return []
    lowered = html.lower()
    positions: list[int] = []
    for token in tokens:
        for m in re.finditer(re.escape(token), lowered):
            positions.append(m.start())
    positions.sort()
    return positions


def _find_firm_id_in_search_html(html: str, company: str) -> str:
    """Из HTML страницы поиска 2gis.ru вернуть /firm/{id} той карточки, чей
    текст проходит _name_tokens-матч с названием компании, либо ''.

    Берём ссылку на фирму, БЛИЖАЙШУЮ к вхождению токена имени (карточка в
    вёрстке/initialState занимает до ~1000 символов вокруг названия).
    """
    positions = _name_match_positions(html, company)
    if not positions:
        return ""
    best_id, best_dist = "", 10**9
    for m in re.finditer(r"/firm/(\d{6,})", html):
        fpos = m.start()
        dist = min(abs(fpos - p) for p in positions)
        if dist < best_dist and dist <= 1000:
            best_id, best_dist = m.group(1), dist
    return best_id


def _name_window_html(html: str, company: str, radius: int = 500) -> str:
    """Конкатенация фрагментов html в радиусе ±radius символов от вхождений
    токенов названия компании. '' — имя на странице не встречается.

    Fix [scrape-guard]: минимальная защита, когда ссылку /firm/{id} найти не
    удалось — телефон/email засчитываются только в пределах ~500 символов от
    совпадения имени, а не со всей многокомпанийной страницы.
    """
    positions = _name_match_positions(html, company)
    if not positions:
        return ""
    spans: list[list[int]] = []
    for p in positions:
        start, end = max(0, p - radius), min(len(html), p + radius)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    return "\n".join(html[s:e] for s, e in spans)


def _fetch_2gis_contacts_api(company: str, city: str = "", firm_id: str = "") -> dict:
    """Fetch contacts for ONE company from the official 2GIS Catalog (Places) API.

    This is the paid, structured, captcha-free path — preferred over scraping
    2gis.ru. Returns {"emails","phones","addresses"[,"website"]} with normalized
    phones, or an empty result if the API has no key, is rejected, or finds no
    confident match for this company.
    """
    global _TWOGIS_DEAD_KEY
    empty = {"emails": [], "phones": [], "addresses": []}
    settings = get_settings()
    api_key = settings.twogis_api_key
    if not api_key or _TWOGIS_DEAD_KEY:
        return empty
    company = (company or "").strip()
    firm_id = (firm_id or "").strip()
    if not company and not firm_id:
        return empty

    params: dict = {
        "key": api_key,
        "fields": "items.contact_groups,items.address_name,items.full_name,items.org",
        "page_size": 5,
    }
    if firm_id:
        params["id"] = firm_id
    else:
        params["q"] = company
        city_id = _resolve_2gis_city_id(city) if city else None
        if city_id:
            params["city_id"] = city_id
        elif city:
            params["q"] = f"{company} {city}"

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get("https://catalog.api.2gis.com/3.0/items", params=params)
    except Exception:
        logger.debug("2GIS contacts API request failed for %r", company, exc_info=True)
        return empty
    if resp.status_code != 200:
        return empty
    try:
        data = resp.json()
    except Exception:
        return empty

    meta = data.get("meta") or {}
    code = meta.get("code")
    if code and code != 200:
        err = meta.get("error") or {}
        # Auth/quota failure → flip the shared breaker + alert ops (same handling
        # as _search_2gis) so we stop hammering a dead key and the operator sees
        # it. The enrich task surfaces this to the user as a "ключ 2GIS" issue.
        if code in (401, 403, 429):
            _TWOGIS_DEAD_KEY = True
            logger.error("2GIS contacts API blocked: code=%s msg=%s", code, err.get("message"))
            try:
                from app.services.notifications import send_alert
                send_alert(
                    "critical",
                    f"2GIS API blocked: {err.get('type', code)}",
                    f"Code {code}: {err.get('message', '')[:200]}",
                    key=f"2gis_api_{code}",
                    throttle_seconds=3600,
                )
            except Exception:
                pass
        return empty

    items = data.get("result", {}).get("items", []) or []
    if not items:
        return empty

    # With a firm_id the result is exact. With a name search, pick the item whose
    # name shares the MOST tokens with the lead — so we never paste a different
    # company's phone onto this lead.
    if firm_id:
        chosen = items[0]
    else:
        q_tokens = _name_tokens(company)
        chosen, best = None, 0
        for it in items:
            score = len(q_tokens & _name_tokens(it.get("name") or it.get("full_name") or ""))
            if score > best:
                chosen, best = it, score
        if best < 1:
            return empty

    phones: list[str] = []
    emails: list[str] = []
    website = ""
    org_info = chosen.get("org") or {}
    if org_info.get("website"):
        website = org_info["website"]
    for group in chosen.get("contact_groups", []) or []:
        for contact in group.get("contacts", []) or []:
            ctype = contact.get("type")
            cval = (contact.get("text") or contact.get("value") or "").strip()
            if not cval:
                continue
            if ctype == "phone":
                np = _normalize_phone(cval)
                if np and np not in phones:
                    phones.append(np)
            elif ctype == "email":
                low = cval.lower()
                if low not in emails:
                    emails.append(low)
            elif ctype == "website" and not website:
                website = cval

    # Return whatever we got — including a website-only result (no direct
    # phone/email). The caller uses that website to scrape the company's own
    # site for contacts when the API tier doesn't expose phones.
    address = (chosen.get("address_name") or chosen.get("full_name") or "").strip()
    res: dict = {"emails": emails[:5], "phones": phones[:5], "addresses": [address] if address else []}
    if website:
        res["website"] = website
    return res


def enrich_2gis_lead(company: str, city: str = "", firm_id: str = "") -> dict:
    """Fetch phones/emails/address for a 2GIS lead.

    Strategy (best signal first):
      1. Official 2GIS Catalog (Places) API — paid, structured, no captcha.
         Used whenever a key is configured and the company is found there.
      2. Fallback: scrape the public 2gis.ru site (firm page by id, else search
         by name+city) — captcha-prone, used only if the API yields nothing.

    Returns dict with keys emails/phones/addresses (same shape as
    enrich_website_contacts).
    """
    company = (company or "").strip()
    if not company and not firm_id:
        return {"emails": [], "phones": [], "addresses": []}

    # 1) Official API first — paid, structured, no captcha.
    api_contacts = _fetch_2gis_contacts_api(company, city, firm_id)
    if api_contacts.get("phones") or api_contacts.get("emails"):
        return api_contacts

    # 1b) The API often returns the company's own website but no direct contacts
    # (e.g. when the API tier excludes phones). Scrape THAT site for phone/email
    # — fully legit: it's the company's own public contacts, no captcha.
    api_site = api_contacts.get("website")
    if api_site:
        try:
            site = enrich_website_contacts(api_site)
        except Exception:
            site = {}
        if site.get("phones") or site.get("emails"):
            if not site.get("addresses") and api_contacts.get("addresses"):
                site["addresses"] = api_contacts["addresses"]
            return site

    # 2) Fallback: scrape 2gis.ru. Honour the enrichment scrape breaker (captcha)
    # — if it's tripped, return whatever (possibly empty) the API gave.
    global _TWOGIS_SCRAPE_BLOCKED_ENRICH
    if _TWOGIS_SCRAPE_BLOCKED_ENRICH:
        return api_contacts or {"emails": [], "phones": [], "addresses": []}

    result: dict = {"emails": [], "phones": [], "addresses": []}

    def _extract_phones(html: str) -> list[str]:
        plus_phones = _PHONE_RE.findall(html)
        # Fix [phones]: «+» к цифрам больше не дорисовываем — tel:8(800)…
        # превращался в невалидный +8800…; нормализация сама приводит
        # 8-префиксные и местные номера к +7.
        tel_phones = _TEL_LINK_RE.findall(html)
        raw = plus_phones + tel_phones
        normed = _dedup_preserve_order([_normalize_phone(p) for p in raw])
        return [p for p in normed if p and 11 <= len(re.sub(r"\D", "", p)) <= 12]

    # Try URL paths in order; stop at the first one that yields any phone.
    # 2gis.ru returns 200 even for non-existent firm IDs ("ничего не найдено"),
    # so we must fall back on empty content, not just HTTP errors.
    #
    # IMPORTANT: bare /firm/{id} 301-redirects to /moscow/firm/{id} which 404s
    # for non-Moscow firms. We MUST prefix with the actual city slug (e.g.
    # /tomsk/firm/{id}). Without that the firm-page enrichment is dead code.
    urls: list[tuple[str, bool]] = []  # (url, is_search_page)
    slug = _city_to_slug(city) if city else None
    if firm_id and slug:
        urls.append((f"https://2gis.ru/{slug}/firm/{firm_id}", False))
    if firm_id and not slug:
        # No slug — try bare URL anyway as last resort (works for Moscow only)
        urls.append((f"https://2gis.ru/firm/{firm_id}", False))
    if company:
        query = company if not city else f"{company} {city}"
        if slug:
            urls.append((f"https://2gis.ru/{slug}/search/{quote_plus(query)}", True))
        urls.append((f"https://2gis.ru/search/{quote_plus(query)}", True))

    html = ""
    phones: list[str] = []
    for url, is_search in urls:
        # Fix #5: pass _is_enrich=True so captcha failures hit the enrichment
        # counter, not the search counter.
        page_html = _fetch_2gis_html(url, _is_enrich=True)
        if not page_html:
            continue
        if not is_search:
            # Страница конкретной фирмы — контакты принадлежат ей.
            page_phones = _extract_phones(page_html)
            if page_phones:
                html = page_html
                phones = page_phones
                break
            # Keep the last non-empty HTML so we can still pull emails if phones missed
            html = page_html
            continue

        # Fix [scrape-guard]: страница ПОИСКА содержит много компаний — гонять
        # регэкспы по всему HTML нельзя (phones[0] мог принадлежать чужой
        # фирме или рекламному блоку). Сначала ищем карточку, чей текст
        # проходит тот же _name_tokens-матч, что и API-путь, берём её
        # /firm/{id} и тянем контакты со страницы самой фирмы (captcha-риск
        # ограничен breaker'ом _TWOGIS_SCRAPE_BLOCKED_ENRICH). Этот же гард
        # действует и для fallback-на-поиск ветки firm_id-пути.
        matched_id = _find_firm_id_in_search_html(page_html, company)
        if matched_id:
            firm_url = (
                f"https://2gis.ru/{slug}/firm/{matched_id}" if slug
                else f"https://2gis.ru/firm/{matched_id}"
            )
            firm_html = _fetch_2gis_html(firm_url, _is_enrich=True)
            if firm_html:
                page_phones = _extract_phones(firm_html)
                if page_phones:
                    html = firm_html
                    phones = page_phones
                    break
                if not html:
                    html = firm_html

        # Минимальный гард: ссылки на фирму нет — контакты засчитываем только
        # в ±500 символах от совпадения имени. Имя не нашлось → страница не
        # даёт НИЧЕГО (любые контакты почти наверняка чужие).
        window_html = _name_window_html(page_html, company)
        if window_html:
            page_phones = _extract_phones(window_html)
            if page_phones:
                html = window_html
                phones = page_phones
                break
            if not html:
                html = window_html

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

    # If no emails on the firm page, try to extract the company's own website
    # from the firm-page HTML and scrape that for emails. ~15-20% of firms
    # link their own site, which usually has a /contacts page with email.
    if not emails:
        external_url = _extract_org_website_from_2gis_html(html)
        if external_url:
            try:
                website_contacts = enrich_website_contacts(external_url)
                website_emails = website_contacts.get("emails") or []
                if website_emails:
                    emails = _dedup_preserve_order(website_emails)
                # Also pick up any extra phones the website has
                website_phones = website_contacts.get("phones") or []
                for wp in website_phones:
                    np = _normalize_phone(wp) if not wp.startswith("+") else wp
                    if np and np not in phones and 11 <= len(re.sub(r"\D", "", np)) <= 12:
                        phones.append(np)
            except Exception:
                logger.debug("website enrichment via 2gis-link failed", exc_info=True)

    result["phones"] = phones[:5]
    result["emails"] = emails[:5]
    # Address is non-trivial to extract reliably from search HTML; leave empty
    # and rely on the 2GIS API address that was saved at collection time.
    return result


# Domains that are infrastructure/tracking/social — NOT a real company website
_NON_COMPANY_DOMAIN_PARTS = (
    "2gis", "yandex", "google", "vk.com", "vk.ru", "facebook", "instagram",
    "ok.ru", "twitter", "t.me", "telegram", "mail.ru", "rambler",
    "metrika", "gstatic", "googletagmanager", "googleapis",
    "sberbank", "sber.ru", "id.sber", "russpass", "w3.org",
    "top-fwz", "serving-sys", "doubleclick", "adservices",
    "cloudflare", "cdnjs", "jsdelivr", "fontawesome",
    "youtube.com", "youtu.be", "tiktok",
)


def _extract_org_website_from_2gis_html(html: str) -> str | None:
    """Find the company's own website URL inside a 2gis.ru firm-page HTML.

    Returns the first plausible external URL (excluding social/tracking/CDN).
    """
    if not html:
        return None
    candidates: list[str] = []
    # Look for url-like strings first; cap iteration
    for m in re.finditer(r'https?://([a-zA-Z0-9.\-]+)/?[a-zA-Z0-9._\-/]*', html):
        url = m.group(0).rstrip('",\'')
        host = m.group(1).lower()
        if any(bad in host for bad in _NON_COMPANY_DOMAIN_PARTS):
            continue
        # Must look like a real domain (TLD 2-6 chars)
        if not re.match(r'^[a-z0-9.\-]+\.[a-z]{2,6}$', host):
            continue
        # Skip very long URLs (probably tracking pixels)
        if len(url) > 150:
            continue
        candidates.append(url)
        if len(candidates) >= 5:
            break
    if not candidates:
        return None
    # Prefer the shortest URL (usually the homepage, not a tracking pixel)
    return sorted(candidates, key=len)[0]

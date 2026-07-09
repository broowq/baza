"""Lead quality filter: AI-powered (YandexGPT/GigaChat/Anthropic) with rule-based fallback.

Uses unified llm_client which tries the primary provider (YandexGPT by default),
then cascades through the others on failure. Falls back to rule-based competitor
detection if all LLMs are unavailable.
"""
import hashlib
import json
import logging
import re

import redis as _redis

from app.core.config import get_settings
from app.services import llm_client

logger = logging.getLogger(__name__)

# ── Per-candidate LLM-verdict cache (Redis) ──────────────────────────────────
# The AI filter used to re-classify every candidate on every collection run. We
# cache each LLM keep/drop verdict keyed on (project-config hash, candidate
# identity) for ~7 days, so repeat candidates for the same niche skip the LLM —
# saving the org's monthly AI budget + latency. Only REAL LLM verdicts are
# cached, never the rule-based fallback. A change to niche/geo/segments/prompt
# changes the hash and naturally invalidates.
_CACHE_TTL_SECONDS = 7 * 24 * 3600
_redis_singleton: "_redis.Redis | None" = None


def _get_filter_redis() -> "_redis.Redis | None":
    global _redis_singleton
    if _redis_singleton is None:
        try:
            _redis_singleton = _redis.Redis.from_url(
                get_settings().redis_url, decode_responses=True, socket_timeout=2
            )
        except Exception:
            return None
    return _redis_singleton


def _filter_config_hash(
    niche: str, geography: str, segments: list[str], prompt: str,
    excluded_segments: list[str] | None = None,
) -> str:
    parts = [
        (niche or "").strip().lower(),
        (geography or "").strip().lower(),
        ",".join(sorted((s or "").strip().lower() for s in (segments or []))),
        (prompt or "").strip().lower(),
    ]
    # Исключения меняют вердикты → обязаны менять ключ кэша (иначе старые
    # «keep» без исключений протекут в проект с ограничениями). Но 5-й элемент
    # добавляем ТОЛЬКО при непустых исключениях: для остальных проектов и
    # промпт фильтра, и вердикты не меняются — их 7-дневный кэш валиден, и
    # деплой не должен устраивать разовую полную инвалидацию (LLM-респенд).
    excl = ",".join(sorted((e or "").strip().lower() for e in (excluded_segments or []) if e))
    if excl:
        parts.append(excl)
    canon = "|".join(parts)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


def _candidate_cache_key(c: dict) -> str:
    dom = (c.get("domain") or "").strip().lower()
    if dom and "." in dom:
        return dom
    name = (c.get("company") or "").strip().lower()
    city = (c.get("city") or "").strip().lower()
    return f"{name}|{city}" if name else ""


def filter_candidates_llm(
    candidates: list[dict],
    niche: str,
    geography: str,
    segments: list[str],
    *,
    prompt: str = "",
    excluded_segments: list[str] | None = None,
    organization_id: str | None = None,
) -> list[dict]:
    """Filter candidates for relevance. Uses AI if available, rule-based otherwise.

    `organization_id` is forwarded to llm_client so each batch call is
    metered against the org's monthly AI-cost cap. Hitting the cap returns
    None from chat() — caller transparently falls back to rule-based.
    """
    if not candidates:
        return candidates

    # Try AI filter first
    if llm_client.is_configured():
        try:
            result = _ai_filter(candidates, niche, geography, segments, prompt,
                                excluded_segments=excluded_segments,
                                organization_id=organization_id)
            if result is not None:
                return result
        except Exception as e:
            logger.warning(f"AI filter failed, falling back to rules: {e}")

    # Rule-based fallback — applied whenever we have ANY usable context.
    # Previously: if prompt was empty AND LLM failed, every candidate passed
    # through unfiltered. A transient GigaChat outage was a silent
    # data-quality incident. Now: if there's no prompt but we have niche +
    # segments, synthesize a minimal prompt so the strict rule-based filter
    # always has signal to bite on.
    effective_prompt = prompt
    synthesized = False
    if not effective_prompt and (niche or segments):
        parts = []
        if niche:
            parts.append(niche)
        if segments:
            parts.append("для " + ", ".join(segments[:3]))
        effective_prompt = " ".join(parts).strip()
        if effective_prompt:
            # FIX (аудит, P0 #3): синтезированный промпт «{ниша} для {сегменты}» —
            # это ЧИСТО аудиторный текст, в нём нет слов продукта. Помечаем его,
            # чтобы rule-based фильтр пропустил Step 1 (поиск конкурентов по
            # имени) — иначе он отбраковывал ровно запрошенные сегменты.
            synthesized = True
            logger.info(
                "LLM filter fell back and synthesized prompt=%r from niche/segments "
                "so the rule-based filter still runs",
                effective_prompt,
            )

    if effective_prompt:
        result = _rule_based_competitor_filter(
            candidates, effective_prompt, niche, segments,
            synthesized_prompt=synthesized,
            excluded_segments=excluded_segments,
        )
        logger.info(
            f"Rule-based filter: {len(candidates)} candidates -> {len(result)} kept "
            f"({len(candidates) - len(result)} rejected as competitors/irrelevant)"
        )
        return result

    # No context at all (no prompt, no niche, no segments) — pass through.
    # This is mainly a test/internal-tooling escape hatch; real projects
    # always have at least niche.
    logger.warning(
        "LLM filter: LLM unavailable AND no niche/segments/prompt context — "
        "passing %d candidates through UNFILTERED. This should not happen "
        "in production.",
        len(candidates),
    )
    return candidates


def _ai_filter(
    candidates: list[dict],
    niche: str,
    geography: str,
    segments: list[str],
    prompt: str,
    *,
    excluded_segments: list[str] | None = None,
    organization_id: str | None = None,
) -> list[dict] | None:
    """AI-based filtering. Returns None on complete failure (all batches failed
    before producing any results, or cost-cap hit on the very first batch).

    FIX (Bug #5): Previously a single batch failure caused the entire result set
    to be discarded (return None), throwing away all candidates approved by
    earlier batches.  Now: on a batch failure we keep whatever was approved so
    far and fall back to rule-based filtering only for the failed batch.
    We still return None (signal full failure) if the *first* batch fails and no
    results have been accumulated yet, preserving the cost-cap short-circuit
    behaviour — the caller's rule-based path then handles all candidates.
    """
    cfg = _filter_config_hash(niche, geography, segments, prompt, excluded_segments)
    r = _get_filter_redis()

    # 1. Look up cached verdicts (config + candidate identity).
    # Префикс llmf2: (был llmf:) — конфиг-хэш не включает шаблон промпта,
    # поэтому после починки парсера ответов (JSON вместо «все цифры подряд»)
    # старые, потенциально отравленные вердикты llmf: нельзя переиспользовать —
    # они тихо доживут свой TTL и исчезнут.
    rkey_for: dict[int, str] = {}
    for c in candidates:
        ck = _candidate_cache_key(c)
        rkey_for[id(c)] = f"llmf2:{cfg}:{ck}" if ck else ""
    cached: dict[int, "bool | None"] = {id(c): None for c in candidates}
    if r:
        uniq = [k for k in {rkey_for[id(c)] for c in candidates} if k]
        if uniq:
            try:
                got = dict(zip(uniq, r.mget(uniq)))
                for c in candidates:
                    v = got.get(rkey_for[id(c)])
                    if v in ("0", "1"):
                        cached[id(c)] = (v == "1")
            except Exception:
                pass

    kept_ids: set[int] = {id(c) for c in candidates if cached[id(c)] is True}
    to_classify = [c for c in candidates if cached[id(c)] is None]
    cache_hits = len(candidates) - len(to_classify)

    if not to_classify:
        result = [c for c in candidates if id(c) in kept_ids]
        logger.info("AI filter: %d candidates, all cached → %d kept", len(candidates), len(result))
        return result

    # 2. Classify only the uncached remainder; cache fresh LLM verdicts.
    BATCH_SIZE = 30
    to_cache: dict[str, str] = {}
    llm_ok = False
    for batch_start in range(0, len(to_classify), BATCH_SIZE):
        batch = to_classify[batch_start:batch_start + BATCH_SIZE]
        verdict = _ai_filter_batch(batch, niche, geography, segments, prompt,
                                   excluded_segments=excluded_segments,
                                   organization_id=organization_id)
        if verdict is None:
            if batch_start == 0 and not llm_ok and not kept_ids:
                # Total failure (e.g. cost-cap) with nothing accumulated → signal
                # full failure so the caller runs rule-based over all candidates.
                return None
            logger.warning(
                "AI filter batch at %d failed; rule-based fallback for this batch "
                "(%d candidates)", batch_start, len(batch),
            )
            for c in _rule_based_competitor_filter(
                batch, prompt, niche, segments, excluded_segments=excluded_segments,
            ):
                kept_ids.add(id(c))
            continue  # never cache rule-based verdicts
        kept, verdict_complete = verdict
        llm_ok = True
        batch_kept_ids = {id(c) for c in kept}
        for c in batch:
            keep = id(c) in batch_kept_ids
            if keep:
                kept_ids.add(id(c))
            rk = rkey_for[id(c)]
            if not rk:
                continue
            # FIX (аудит, P0 #2): правило кэширования вердиктов.
            # «1» (keep) кэшируем всегда — индекс перечислен LLM явно.
            # «0» (drop) кэшируем ТОЛЬКО когда verdict_complete=True, т.е. ответ —
            # корректный JSON {"keep": [...]} со всеми индексами в диапазоне:
            # лишь тогда отсутствие кандидата в списке = явный отказ. Если ответ
            # мог быть обрезан (текстовый fallback, кривой JSON) — для
            # пропущенных НИЧЕГО не кэшируем, пусть переклассифицируются в
            # следующем прогоне. Иначе хвост батча на 7 дней застревал как drop.
            if keep:
                to_cache[rk] = "1"
            elif verdict_complete:
                to_cache[rk] = "0"

    if r and to_cache:
        try:
            pipe = r.pipeline()
            for k, v in to_cache.items():
                pipe.set(k, v, ex=_CACHE_TTL_SECONDS)
            pipe.execute()
        except Exception:
            pass

    # Preserve original candidate order in the kept result.
    result = [c for c in candidates if id(c) in kept_ids]
    logger.info(
        "AI filter: %d candidates (%d cached, %d classified) → %d kept",
        len(candidates), cache_hits, len(to_classify), len(result),
    )
    return result


def _ai_filter_batch(
    batch, niche, geography, segments, prompt, *,
    excluded_segments: list[str] | None = None,
    organization_id: str | None = None,
) -> "tuple[list[dict], bool] | None":
    """Filter a single batch using AI.

    Returns (kept_candidates, verdict_complete) or None on failure.
    verdict_complete=True означает: ответ — корректный JSON и отсутствие
    кандидата в keep-списке можно трактовать как явный отказ (кэшируемый «0»).
    """
    lines = []
    for i, c in enumerate(batch):
        company = c.get("company", "—")
        domain = c.get("domain", "—")
        city = c.get("city", "—")
        desc = (c.get("description") or c.get("snippet") or "")[:250]
        # FIX (аудит, P2 #5): кандидаты несут `categories` (список), ключа
        # `category` не существует — категория всегда была пустой строкой.
        category = ", ".join(c.get("categories") or [])

        parts = [f"{i+1}. {company}"]
        if domain and domain != "—":
            parts.append(f"сайт: {domain}")
        if city and city != "—":
            parts.append(f"город: {city}")
        if category:
            parts.append(f"категория: {category}")
        if desc:
            parts.append(f"описание: {desc}")
        lines.append(" | ".join(parts))

    candidates_text = "\n".join(lines)
    segments_str = ", ".join(segments) if segments else "не указаны"
    excluded_str = ", ".join(e for e in (excluded_segments or []) if e)

    if prompt and excluded_str:
        # Жёсткие исключения пользователя главнее списка сегментов: сегменты —
        # лишь подсказка-расширение, а «кому НЕЛЬЗЯ продать» — прямое
        # ограничение из промпта («только b2b» и т.п.). Без этого блока фильтр
        # легализовал розницу инструкцией «KEEP: компании из целевых сегментов».
        # ВАЖНО: этот усиленный текст применяется ТОЛЬКО к проектам с
        # исключениями — глобальное ужесточение сдвинуло бы вердикты (и кэш)
        # у всех существующих клиентов (major адверсариал-ревью).
        filter_prompt = f"""Ты — строгий фильтр B2B лидов. Пользователь описал свой бизнес: "{prompt}"
Мы ищем ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ — компании, которым можно ПРОДАТЬ товар/услугу.

ЦЕЛЕВАЯ НИША КЛИЕНТОВ: {niche}
ГЕОГРАФИЯ: {geography}
ЦЕЛЕВЫЕ СЕГМЕНТЫ (подсказка, НЕ гарантия): {segments_str}

ЖЁСТКИЕ ИСКЛЮЧЕНИЯ ПОЛЬЗОВАТЕЛЯ: {excluded_str}.
ОТКЛОНЯЙ кандидата, который подпадает под исключение, ДАЖЕ если его тип есть в целевых сегментах.

ГЛАВНЫЙ КРИТЕРИЙ: описание бизнеса пользователя. Если кандидату НЕЛЬЗЯ продать
описанный продукт/услугу — REJECT, даже если тип кандидата есть в целевых сегментах.
ОТКЛОНЯЙ (REJECT) также: конкуренты (продают то же), агрегаторы, каталоги, закрытые компании, блоги.
СОХРАНЯЙ (KEEP): реальные потенциальные покупатели продукта пользователя.

ФОРМАТ ОТВЕТА: строго JSON-объект с номерами подходящих кандидатов, без другого текста.
Пример: {{"keep": [1, 3]}}. Если ни один не подходит: {{"keep": []}}.

КАНДИДАТЫ:
{candidates_text}

JSON-ОТВЕТ:"""
    elif prompt:
        # Без исключений — прежний текст байт-в-байт (стабильность вердиктов
        # и кэша для всех существующих проектов).
        filter_prompt = f"""Ты — строгий фильтр B2B лидов. Пользователь описал свой бизнес: "{prompt}"
Мы ищем ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ — компании, которым можно ПРОДАТЬ товар/услугу.

ЦЕЛЕВАЯ НИША КЛИЕНТОВ: {niche}
ГЕОГРАФИЯ: {geography}
ЦЕЛЕВЫЕ СЕГМЕНТЫ: {segments_str}

ОТКЛОНЯЙ (REJECT): конкуренты (продают то же), агрегаторы, каталоги, закрытые компании, блоги.
СОХРАНЯЙ (KEEP): потенциальные покупатели, компании из целевых сегментов.

ФОРМАТ ОТВЕТА: строго JSON-объект с номерами подходящих кандидатов, без другого текста.
Пример: {{"keep": [1, 3]}}. Если ни один не подходит: {{"keep": []}}.

КАНДИДАТЫ:
{candidates_text}

JSON-ОТВЕТ:"""
    else:
        excluded_line = (
            f"\nЖЁСТКИЕ ИСКЛЮЧЕНИЯ: {excluded_str} — отклоняй подпадающих под них."
            if excluded_str else ""
        )
        filter_prompt = f"""Фильтр B2B лидов. Ниша: {niche}. География: {geography}. Сегменты: {segments_str}.{excluded_line}
Отклоняй: не из ниши, агрегаторы, закрытые, госучреждения. Сохраняй: реальный бизнес из ниши.
Ответ — строго JSON-объект {{"keep": [номера подходящих]}}, например {{"keep": [1, 3]}};
если ни один не подходит — {{"keep": []}}. Без другого текста.

КАНДИДАТЫ:
{candidates_text}

JSON-ОТВЕТ:"""

    try:
        # FIX (аудит, P0 #2): max_tokens 200 → 500. При BATCH_SIZE=30 ответ
        # вида {"keep": [1, 2, ..., 30]} в 200 токенов мог не влезть — обрезка
        # незаметна ниже по течению, и хвост батча кэшировался как drop.
        answer = llm_client.chat(
            filter_prompt,
            max_tokens=500,
            temperature=0.1,
            organization_id=organization_id,
        )
        if answer is None:
            return None

        parsed = _parse_keep_answer(answer.strip(), len(batch))
        if parsed is None:
            # Раньше нераспознанный ответ либо пропускал весь батч («keep all»),
            # либо парсер хватал все цифры подряд и выносил неверные вердикты.
            # Теперь: невнятный ответ → None → строгий rule-based fallback,
            # и НИЧЕГО из этого батча не кэшируется.
            logger.warning(f"AI filter: could not parse response {answer!r}, falling back to rules")
            return None

        kept_indices, verdict_complete = parsed
        return [c for i, c in enumerate(batch) if i in kept_indices], verdict_complete

    except Exception as e:
        logger.warning(f"AI filter batch failed: {e}")
        return None  # Signal failure


# FIX (аудит, P0 #1): раньше парсер брал ВСЕ цифры из ответа (re.findall(r"\d+")):
# «Подходят 1, 3. Кандидаты 2 и 4 — конкуренты» оставлял ещё и 2, 4;
# «Подходящих: 0 из 30» ломал эвристику «все отклонены» и оставлял №30;
# «1-5» терял кандидатов 2-4. Неверные вердикты кэшировались на 7 дней.
# Теперь промпт требует JSON {"keep": [...]}, текст разбирается лишь осторожным
# fallback-ом ниже.
_REFUSAL_TOKENS = ("конкурент", "не подход", "0 из")
_NEGATIVE_WORDS = ("нет", "none", "отсутству", "не подход")


def _extract_json_block(text: str) -> "str | None":
    """Первый сбалансированный {...} блок из текста (или None, если блока нет
    либо скобки не закрылись — т.е. JSON, скорее всего, обрезан)."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_keep_answer(answer: str, batch_size: int) -> "tuple[set[int], bool] | None":
    """Разбирает ответ LLM → (set 0-based KEEP-индексов, verdict_complete).

    verdict_complete=True ТОЛЬКО для корректного JSON {"keep": [...]} со всеми
    индексами в диапазоне 1..batch_size — лишь тогда отсутствие индекса можно
    кэшировать как явный drop. Явный {"keep": []} — валидный вердикт «все
    отклонены». None = неразборчиво/двусмысленно → rule-based fallback батча.
    """
    # 1) JSON-путь.
    block = _extract_json_block(answer)
    if block is not None:
        try:
            data = json.loads(block)
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("keep"), list):
            try:
                nums = {int(x) for x in data["keep"]}
            except (TypeError, ValueError):
                nums = None
            if nums is not None:
                if not nums:
                    return set(), True  # явный {"keep": []} = все отклонены
                in_range = {n - 1 for n in nums if 1 <= n <= batch_size}
                if not in_range:
                    return None  # все индексы вне диапазона — мусор
                # complete только если ВСЕ перечисленные индексы в диапазоне
                return in_range, len(in_range) == len(nums)

    # 2) Текстовый fallback — verdict_complete всегда False (обрезку текста
    #    отличить от полного ответа нельзя, дропы не кэшируем).
    lower = answer.lower()
    digits = re.findall(r"\d+", answer)
    if digits and any(tok in lower for tok in _REFUSAL_TOKENS):
        # Цифры вперемешку с отказными формулировками («конкурент», «не
        # подходит», «0 из») — двусмысленно: цифры могут быть номерами
        # ОТКЛОНЁННЫХ. Фейлим батч.
        return None
    if not digits:
        if any(tok in lower for tok in _NEGATIVE_WORDS):
            return set(), False  # «нет подходящих» текстом — дропы не кэшируем
        return None
    if digits == ["0"]:
        return set(), False  # одинокий ноль = все отклонены

    # Цифры берём только из текста после ПОСЛЕДНЕГО маркера «ПОДХОДЯЩИЕ» /
    # «подходят», а без маркера — из последней непустой строки.
    pos = lower.rfind("подходя")
    if pos != -1:
        segment = answer[pos:]
    else:
        seg_lines = [ln for ln in answer.splitlines() if ln.strip()]
        segment = seg_lines[-1] if seg_lines else answer

    kept: set[int] = set()
    for m in re.finditer(r"(\d+)\s*[-–—]\s*(\d+)|(\d+)", segment):
        if m.group(3) is not None:
            n = int(m.group(3))
            if 1 <= n <= batch_size:
                kept.add(n - 1)
        else:
            a, b = int(m.group(1)), int(m.group(2))
            if not (1 <= a <= b <= batch_size):
                return None  # диапазон вне батча — фейлим, не угадываем
            kept.update(range(a - 1, b))  # «1-5» → 1,2,3,4,5
    if not kept:
        return None
    return kept, False


# ── Rule-based competitor filtering ──

# Keywords that indicate a company SELLS the product (= competitor)
_SELLER_SIGNALS = [
    "продажа", "продаж", "продаём", "продаем", "купить", "заказать",
    "магазин", "интернет-магазин", "оптом", "розница", "прайс",
    "каталог товаров", "доставка по", "склад", "поставщик",
    "производител", "изготовлен", "дистрибьют",
]

# Типовые русские окончания для грубой лемматизации (без словаря): срезаем
# одно окончание, оставляя основу не короче 4 букв. «ресторанов»/«рестораны»/
# «ресторане» → «ресторан»; «овощи»/«овощей» → «овощ». Длинные суффиксы первыми.
_RU_SUFFIXES = (
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
    "ов", "ев", "ей", "ий", "ый", "ой", "ая", "яя", "ое", "ее", "ие", "ые",
    "ам", "ям", "ом", "ем", "ах", "ях", "ую", "юю", "ью",
    "а", "я", "о", "е", "ы", "и", "ь", "у", "ю", "й",
)


def _ru_stem(word: str) -> str:
    for suf in _RU_SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: len(word) - len(suf)]
    return word


def _segment_niche_stems(segments: "list[str] | None", niche: str) -> set[str]:
    """Лемматизированный словарь сегментов + ниши.

    FIX (аудит, P0 #3a/3d): сегменты и ниша описывают ПОКУПАТЕЛЕЙ («для
    ресторанов»), а не продукт. Их лексику нужно вычитать из продуктовых
    терминов, иначе rule-based фильтр отбраковывает ровно запрошенные сегменты
    («Ресторан Пушкин» как «конкурента» продавца овощей).
    """
    stems: set[str] = set()
    for src in list(segments or []) + [niche or ""]:
        for word in (src or "").lower().replace("ё", "е").replace("-", " ").split():
            w = word.strip(",.()[]:;\"'!?")
            if len(w) >= 4:
                stems.add(_ru_stem(w)[:6])
    return stems


# Частотные служебные слова, которые встречаются почти в каждом сниппете и
# поэтому не несут продуктового сигнала. FIX (аудит, P1 #4): «для» попадало в
# product_keywords и матчилось в КАЖДОМ сниппете — порог «2 продуктовых слова +
# маркер продавца» фактически превращался в 1.
_FUNCTION_WORDS = {
    "для", "или", "как", "что", "это", "этот", "эта", "так", "там", "тут",
    "при", "под", "над", "без", "про", "все", "всех", "если", "чтобы",
    "наша", "наше", "наши", "ваша", "ваше", "ваши", "свой", "своя", "свои",
    "есть", "будет", "может", "можно", "очень", "еще", "тоже", "также",
}


# Keywords extracted from prompt that indicate what user sells
def _extract_product_keywords(prompt: str, segments: "list[str] | None" = None,
                              niche: str = "") -> list[str]:
    """Extract product/service keywords from user's business description.

    FIX (аудит, P1 #4): фильтруем стоп-/служебные слова, требуем длину >=4,
    возвращаем УНИКАЛЬНЫЕ слова. FIX (P0 #3b/3d): часть промпта после первого
    «для» — это аудитория, а не продукт; лексику сегментов/ниши вычитаем.
    """
    text = (prompt or "").lower().replace("ё", "е")
    # Часть после первого «для» описывает покупателей — отрезаем.
    text = re.split(r"\bдля\b", text, maxsplit=1)[0]
    # Remove common action words to isolate product
    for word in ["продаю", "продаём", "продаем", "предлагаю", "оказываю",
                 "делаю", "произвожу", "поставляю", "занимаюсь", "работаю"]:
        text = text.replace(word, "")

    # Remove geography
    text = re.sub(r'\bв\s+\w+[еу]?\b', '', text)

    vocab = _segment_niche_stems(segments, niche)
    banned = _STOPWORDS | _FUNCTION_WORDS
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.split():
        w = raw.strip(",.()[]:;\"'!?")
        if len(w) < 4 or w in banned:
            continue
        if _ru_stem(w)[:6] in vocab:
            continue  # слово сегмента/ниши = покупатель, не продукт
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:10]


# Generic words that appear in many 2GIS company names but carry no targeting
# signal by themselves. Without stripping these, "управляющая компания" matches
# "Уралнефтегазкомплект, компания" (every LLC has "компания" in its name).
_STOPWORDS = {
    "компания", "компании", "фирма", "фирмы", "организация", "организации",
    "предприятие", "предприятия", "бизнес", "офис", "офисы", "офиса",
    "центр", "центра", "центры",  # only matches with modifier (бизнес-центр, торговый центр)
    "услуги", "сервис", "group", "групп", "ооо", "ип", "зао", "оао", "пао",
    "россия", "российский", "регион", "и", "в", "на", "для", "по",
    "небольшой", "малый", "средний", "крупный", "новый",
}


def _build_multiword_phrases(segments: list[str]) -> list[str]:
    """Extract multi-word / hyphenated phrases from segments that must match as whole.

    Both "бизнес-центр" (hyphenated) and "торговый центр" (spaced) are multi-token
    phrases — matching them whole avoids false positives from generic halves like "бизнес".
    """
    phrases: list[str] = []
    for seg in segments or []:
        s = seg.lower().replace("ё", "е").strip()
        if len(s) < 5:
            continue
        # Both space- and hyphen-separated forms are multi-word phrases.
        if " " in s or "-" in s:
            phrases.append(s)
            # Also include a normalized spaced variant so "бизнес-центр" matches
            # company names containing either "бизнес-центр" or "бизнес центр".
            spaced = s.replace("-", " ")
            if spaced != s and spaced not in phrases:
                phrases.append(spaced)
    return phrases


def _extract_product_core_terms(prompt: str, segments: "list[str] | None" = None,
                                niche: str = "") -> list[str]:
    """Extract CORE product/service terms from prompt (strong competitor signals).

    Example: "Оказываем бухгалтерские услуги" → ['бухгал']
    These roots in a company name indicate a direct competitor.

    FIX (аудит, P0 #3): раньше сюда попадали слова ПОКУПАТЕЛЕЙ — из «Продаю
    овощи для ресторанов» извлекался корень «рестор», и Step 1 отбраковывал
    «Ресторан Пушкин» как конкурента. Теперь: (b) промпт режем по первому
    «для» — дальше идёт аудитория; (a) лексику сегментов+ниши (лемматизированно)
    вычитаем из корней.
    """
    text = (prompt or "").lower().replace("ё", "е")
    # (3b) Часть после первого «для» — аудитория, не продукт.
    text = re.split(r"\bдля\b", text, maxsplit=1)[0]

    # Remove action words
    for word in ("продаю", "продаём", "продаем", "предлагаю", "оказываем", "оказываю",
                 "делаю", "делаем", "производим", "произвожу", "поставляю", "поставляем",
                 "занимаюсь", "занимаемся", "работаю", "работаем", "ищем"):
        text = text.replace(word, " ")
    # Remove geography prepositions
    text = re.sub(r'\bв\s+\w+[еу]?\b', '', text)
    # Remove stopwords
    for sw in ("для", "и", "по", "с", "на", "из", "а", "но", "или", "также",
               "наш", "наши", "свой", "свои"):
        text = re.sub(rf'\b{sw}\b', ' ', text)

    # (3a) Словарь сегментов/ниши — это покупатели, вычитаем их корни.
    vocab = _segment_niche_stems(segments, niche)

    # Extract product root words (5+ chars, лемматизация срезанием окончания)
    roots = []
    for word in text.split():
        w = word.strip(",.()[]:;\"'!?").lower()
        if len(w) >= 5 and w not in _STOPWORDS:
            stem = _ru_stem(w)[:6]
            if stem in vocab:
                continue
            roots.append(stem)
    # Dedupe preserving order
    seen = set()
    out = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out[:8]


def _rule_based_competitor_filter(
    candidates: list[dict],
    prompt: str,
    niche: str,
    segments: list[str],
    *,
    synthesized_prompt: bool = False,
    excluded_segments: list[str] | None = None,
) -> list[dict]:
    """Rule-based filter — STRICT mode when LLM unavailable.

    Strategy (in order):
    0. Candidate matches a user hard-exclusion term → REJECT (исключения
       главнее сегментов: «КФХ, магазин» не пройдёт в проект «только b2b»,
       даже если «КФХ» есть в segments)
    1. Company name contains 2+ product core terms → COMPETITOR → REJECT
    2. Explicit seller signals + product match → COMPETITOR → REJECT
    3. Multi-word segment phrase match → KEEP (strongest segment signal)
    4. Single-word segment match (stopword-filtered) → KEEP
    5. Nothing matches → REJECT (strict)

    FIX (аудит, P0 #3c): synthesized_prompt=True означает, что промпт собран
    из «{ниша} для {сегменты}» — в нём НЕТ слов продукта, только аудитория.
    Step 1 (конкурент по имени) в этом случае пропускаем целиком, иначе он
    отбраковывал ровно запрошенные сегменты.
    """
    product_keywords = _extract_product_keywords(prompt, segments, niche)
    core_terms = [] if synthesized_prompt else _extract_product_core_terms(prompt, segments, niche)

    # Build multi-word phrases from segments (strongest signal)
    phrases = _build_multiword_phrases(segments)

    # Single-word terms from segments, filtered by stopwords
    segment_terms: set[str] = set()
    for seg in segments or []:
        for word in seg.lower().replace("ё", "е").replace("-", " ").split():
            w = word.strip(",.()[]:;")
            if len(w) >= 4 and w not in _STOPWORDS:
                segment_terms.add(w)

    # Add niche words (also filtered)
    for word in (niche or "").lower().replace("ё", "е").replace("-", " ").split():
        w = word.strip(",.()[]:;")
        if len(w) >= 4 and w not in _STOPWORDS:
            segment_terms.add(w)

    # Step 0 prep: жёсткие исключения. Многословные («услуги для физлиц»,
    # «розничный магазин») матчим ТОЛЬКО целой фразой — разложение на слова
    # давало термы «для»/«услуги» и убивало почти всех легитимных кандидатов
    # (blocker адверсариал-ревью). Однословные (≥4 символов не из стоп-слов,
    # либо 3-буквенные аббревиатуры «КФХ»/«НКО») матчим ТОЛЬКО по границе
    # слова — голый substring ловил «нко» в «стаНКОстроительный».
    excluded_phrases: list[str] = []
    excluded_word_res: list["re.Pattern[str]"] = []
    _excluded_words: set[str] = set()
    for excl in excluded_segments or []:
        e = (excl or "").lower().replace("ё", "е").strip().strip(",.()[]:;")
        if not e:
            continue
        if " " in e:
            excluded_phrases.append(e)
            continue
        if (len(e) >= 4 and e not in _STOPWORDS) or (len(e) == 3 and e.isalpha()):
            _excluded_words.add(e)
            excluded_word_res.append(
                re.compile(rf"(?<![а-яеa-z0-9]){re.escape(e)}(?![а-яеa-z0-9])")
            )
    # Слова исключений убираем из positive segment_terms — иначе Step 4
    # сохранил бы то, что Step 0 должен отбросить.
    segment_terms -= _excluded_words

    kept = []
    rejected_competitors = 0
    rejected_irrelevant = 0
    rejected_excluded = 0

    for c in candidates:
        company = (c.get("company") or "").lower().replace("ё", "е")
        snippet = (c.get("snippet") or "").lower().replace("ё", "е")
        domain = (c.get("domain") or "").lower()
        categories = " ".join(c.get("categories") or []).lower()
        combined = f"{company} {snippet} {domain} {categories}"

        # Step 0: жёсткие исключения пользователя — главнее всего остального.
        if excluded_phrases or excluded_word_res:
            if any(ph in combined for ph in excluded_phrases) or any(
                rx.search(combined) for rx in excluded_word_res
            ):
                rejected_excluded += 1
                continue

        # Step 1: Direct competitor — company NAME contains product core terms.
        #
        # FIX (Bug #1): A single product-root match is not enough to call a company
        # a competitor in LLM-unavailable mode — e.g. an accounting *firm looking
        # to buy* accounting software legitimately has "бухгалтер" in its own name.
        # We now require EITHER:
        #   (a) 2+ core-term matches in the name (strong indicator of a direct peer), OR
        #   (b) 1 core-term match AND at least one explicit seller marker (ТД, магазин,
        #       опт, etc.) in the combined text — those signal the company actually SELLS.
        # This preserves false-positive rejection of obvious competitors while stopping
        # legitimate buyers from being silently dropped.
        name_core_matches = sum(1 for t in core_terms if t and t in company)
        has_seller_marker_in_combined = any(sig in combined for sig in _SELLER_SIGNALS)
        if len(core_terms) > 0 and (
            name_core_matches >= 2
            or (name_core_matches >= 1 and has_seller_marker_in_combined)
        ):
            rejected_competitors += 1
            continue

        # Step 2: Explicit seller signals + product match
        product_match = sum(1 for kw in product_keywords if kw in combined)
        seller_match = sum(1 for sig in _SELLER_SIGNALS if sig in combined)
        if product_match >= 2 and seller_match >= 1:
            rejected_competitors += 1
            continue

        # Step 3: Multi-word phrase match (strongest segment signal)
        phrase_match = any(p in combined for p in phrases)
        if phrase_match:
            kept.append(c)
            continue

        # Step 4: Single-word segment match (excluding stopwords)
        segment_match = any(term in combined for term in segment_terms)
        if segment_match:
            kept.append(c)
            continue

        # Step 5: Maps-sourced leads (2GIS, Yandex) — KEEP if any contactable
        # info is present. These came from a targeted segment query so they ARE
        # the target audience by definition, even if their company name doesn't
        # happen to contain the Russian segment word (e.g. "DDX Fitness"
        # searched via "фитнес-клуб"). Accept address OR phone OR firm_id as
        # proof of real business.
        # Trusted-source pass-through: maps and legal-entity registry results
        # came from a targeted query, so even without segment match they're
        # likely valid. Maps need address/phone/firm_id. Registry needs just name.
        is_maps = c.get("source") in {"2gis", "yandex_maps"}
        is_registry = c.get("source") in {"rusprofile"}
        if is_registry and c.get("company"):
            kept.append(c)
            continue
        if is_maps and (c.get("address") or c.get("phone") or c.get("firm_id")):
            kept.append(c)
            continue

        # Step 6: No match — REJECT (strict)
        rejected_irrelevant += 1

    logger.info(
        f"Rule-based filter (strict v3): {len(candidates)} -> {len(kept)} kept | "
        f"competitors={rejected_competitors}, irrelevant={rejected_irrelevant}, "
        f"excluded={rejected_excluded}"
    )
    return kept

"""Lead quality filter: AI-powered (GigaChat/Anthropic) with rule-based fallback.

Uses unified llm_client which tries GigaChat first, then Anthropic.
Falls back to rule-based competitor detection if both LLMs unavailable.
"""
import logging
import re

from app.services import llm_client

logger = logging.getLogger(__name__)


def filter_candidates_llm(
    candidates: list[dict],
    niche: str,
    geography: str,
    segments: list[str],
    *,
    prompt: str = "",
) -> list[dict]:
    """Filter candidates for relevance. Uses AI if available, rule-based otherwise."""
    if not candidates:
        return candidates

    # Try AI filter first
    if llm_client.is_configured():
        try:
            result = _ai_filter(candidates, niche, geography, segments, prompt)
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
    if not effective_prompt and (niche or segments):
        parts = []
        if niche:
            parts.append(niche)
        if segments:
            parts.append("для " + ", ".join(segments[:3]))
        effective_prompt = " ".join(parts).strip()
        if effective_prompt:
            logger.info(
                "LLM filter fell back and synthesized prompt=%r from niche/segments "
                "so the rule-based filter still runs",
                effective_prompt,
            )

    if effective_prompt:
        result = _rule_based_competitor_filter(candidates, effective_prompt, niche, segments)
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
) -> list[dict] | None:
    """AI-based filtering. Returns None on failure."""
    BATCH_SIZE = 30
    all_kept = []

    for batch_start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_start:batch_start + BATCH_SIZE]
        kept = _ai_filter_batch(batch, niche, geography, segments, prompt)
        if kept is None:
            return None  # Signal failure to caller
        all_kept.extend(kept)

    logger.info(
        f"AI filter: {len(candidates)} candidates -> {len(all_kept)} kept "
        f"({len(candidates) - len(all_kept)} rejected)"
    )
    return all_kept


def _ai_filter_batch(batch, niche, geography, segments, prompt) -> list[dict] | None:
    """Filter a single batch using AI. Returns None on failure."""
    lines = []
    for i, c in enumerate(batch):
        company = c.get("company", "—")
        domain = c.get("domain", "—")
        city = c.get("city", "—")
        desc = (c.get("description") or c.get("snippet") or "")[:150]
        category = c.get("category", "")

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

    if prompt:
        filter_prompt = f"""Ты — строгий фильтр B2B лидов. Пользователь описал свой бизнес: "{prompt}"
Мы ищем ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ — компании, которым можно ПРОДАТЬ товар/услугу.

ЦЕЛЕВАЯ НИША КЛИЕНТОВ: {niche}
ГЕОГРАФИЯ: {geography}
ЦЕЛЕВЫЕ СЕГМЕНТЫ: {segments_str}

ОТКЛОНЯЙ (REJECT): конкуренты (продают то же), агрегаторы, каталоги, закрытые компании, блоги.
СОХРАНЯЙ (KEEP): потенциальные покупатели, компании из целевых сегментов.

ФОРМАТ: Номера подходящих через запятую. Если ни один — "0".

КАНДИДАТЫ:
{candidates_text}

ПОДХОДЯЩИЕ:"""
    else:
        filter_prompt = f"""Фильтр B2B лидов. Ниша: {niche}. География: {geography}. Сегменты: {segments_str}.
Отклоняй: не из ниши, агрегаторы, закрытые, госучреждения. Сохраняй: реальный бизнес из ниши.
Номера подходящих через запятую (или "0").

КАНДИДАТЫ:
{candidates_text}

ПОДХОДЯЩИЕ:"""

    try:
        answer = llm_client.chat(
            filter_prompt,
            max_tokens=200,
            temperature=0.1,
        )
        if answer is None:
            return None
        answer = answer.strip()

        if answer == "0":
            return []

        kept_indices: set[int] = set()
        for part in re.findall(r"\d+", answer):
            idx = int(part) - 1
            if 0 <= idx < len(batch):
                kept_indices.add(idx)

        if not kept_indices:
            # Previously we returned the full batch here ("keep all"), which let
            # junk candidates leak through whenever the LLM returned gibberish.
            # Signal failure instead so the caller can fall back to the strict
            # rule-based filter.
            logger.warning(f"AI filter: could not parse response {answer!r}, falling back to rules")
            return None

        return [c for i, c in enumerate(batch) if i in kept_indices]

    except Exception as e:
        logger.warning(f"AI filter batch failed: {e}")
        return None  # Signal failure


# ── Rule-based competitor filtering ──

# Keywords that indicate a company SELLS the product (= competitor)
_SELLER_SIGNALS = [
    "продажа", "продаж", "продаём", "продаем", "купить", "заказать",
    "магазин", "интернет-магазин", "оптом", "розница", "прайс",
    "каталог товаров", "доставка по", "склад", "поставщик",
    "производител", "изготовлен", "дистрибьют",
]

# Keywords extracted from prompt that indicate what user sells
def _extract_product_keywords(prompt: str) -> list[str]:
    """Extract product/service keywords from user's business description."""
    prompt_lower = prompt.lower()
    # Remove common action words to isolate product
    for word in ["продаю", "продаём", "продаем", "предлагаю", "оказываю",
                 "делаю", "произвожу", "поставляю", "занимаюсь", "работаю"]:
        prompt_lower = prompt_lower.replace(word, "")

    # Remove geography
    import re as _re
    prompt_lower = _re.sub(r'\bв\s+\w+[еу]?\b', '', prompt_lower)

    # Extract meaningful words (3+ chars)
    words = [w.strip() for w in prompt_lower.split() if len(w.strip()) >= 3]
    return words[:10]


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


def _extract_product_core_terms(prompt: str) -> list[str]:
    """Extract CORE product/service terms from prompt (strong competitor signals).

    Example: "Оказываем бухгалтерские услуги" → ['бухгалтерск', 'налогов']
    These roots in a company name indicate a direct competitor.
    """
    import re as _re
    text = (prompt or "").lower().replace("ё", "е")

    # Remove action words
    for word in ("продаю", "продаём", "продаем", "предлагаю", "оказываем", "оказываю",
                 "делаю", "делаем", "производим", "произвожу", "поставляю", "поставляем",
                 "занимаюсь", "занимаемся", "работаю", "работаем", "ищем"):
        text = text.replace(word, " ")
    # Remove geography prepositions
    text = _re.sub(r'\bв\s+\w+[еу]?\b', '', text)
    # Remove stopwords
    for sw in ("для", "и", "по", "с", "на", "из", "а", "но", "или", "также",
               "наш", "наши", "свой", "свои"):
        text = _re.sub(rf'\b{sw}\b', ' ', text)

    # Extract product root words (5+ chars for higher specificity)
    roots = []
    for word in text.split():
        w = word.strip(",.()[]:;\"'!?").lower()
        if len(w) >= 6 and w not in _STOPWORDS:
            # Take 5-char stem for lemmatization-less matching
            roots.append(w[:6])
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
) -> list[dict]:
    """Rule-based filter — STRICT mode when LLM unavailable.

    Strategy (in order):
    1. Company name contains 2+ product core terms → COMPETITOR → REJECT
    2. Explicit seller signals + product match → COMPETITOR → REJECT
    3. Multi-word segment phrase match → KEEP (strongest segment signal)
    4. Single-word segment match (stopword-filtered) → KEEP
    5. Nothing matches → REJECT (strict)
    """
    product_keywords = _extract_product_keywords(prompt)
    core_terms = _extract_product_core_terms(prompt)

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

    kept = []
    rejected_competitors = 0
    rejected_irrelevant = 0

    for c in candidates:
        company = (c.get("company") or "").lower().replace("ё", "е")
        snippet = (c.get("snippet") or "").lower().replace("ё", "е")
        domain = (c.get("domain") or "").lower()
        categories = " ".join(c.get("categories") or []).lower()
        combined = f"{company} {snippet} {domain} {categories}"

        # Step 1: Direct competitor — company NAME contains product core terms
        #   "Куб2б, компания бухгалтерских услуг" → contains "бухгал" → competitor
        name_core_matches = sum(1 for t in core_terms if t and t in company)
        if name_core_matches >= 1 and len(core_terms) > 0:
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
        f"competitors={rejected_competitors}, irrelevant={rejected_irrelevant}"
    )
    return kept

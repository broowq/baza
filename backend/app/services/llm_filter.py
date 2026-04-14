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

    # Rule-based fallback: filter competitors when prompt context is available
    if prompt:
        result = _rule_based_competitor_filter(candidates, prompt, niche, segments)
        logger.info(
            f"Rule-based filter: {len(candidates)} candidates -> {len(result)} kept "
            f"({len(candidates) - len(result)} rejected as competitors/irrelevant)"
        )
        return result

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
            logger.warning(f"AI filter: could not parse response '{answer}', keeping all")
            return batch

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


def _rule_based_competitor_filter(
    candidates: list[dict],
    prompt: str,
    niche: str,
    segments: list[str],
) -> list[dict]:
    """Rule-based filter — STRICT mode when LLM unavailable.

    Strategy (in order):
    1. Explicit competitor match (product + seller signals) → REJECT
    2. Target segment match → KEEP
    3. Maps result (2GIS/yandex_maps) without strong signals → KEEP (trust maps)
    4. Web result without segment match → REJECT (too risky without LLM)
    """
    product_keywords = _extract_product_keywords(prompt)

    # Build set of segment terms (these are TARGET customer types)
    segment_terms: set[str] = set()
    for seg in segments or []:
        for word in seg.lower().replace("ё", "е").split():
            if len(word) >= 3:
                segment_terms.add(word)

    # Also use niche words as segment hints (for targeting)
    for word in (niche or "").lower().replace("ё", "е").split():
        if len(word) >= 3:
            segment_terms.add(word.strip(",."))

    kept = []
    rejected_competitors = 0
    rejected_irrelevant = 0

    for c in candidates:
        company = (c.get("company") or "").lower().replace("ё", "е")
        snippet = (c.get("snippet") or "").lower().replace("ё", "е")
        domain = (c.get("domain") or "").lower()
        categories = " ".join(c.get("categories") or []).lower()
        combined = f"{company} {snippet} {domain} {categories}"
        source = c.get("source", "")
        is_maps = source in {"2gis", "yandex_maps"}

        # Step 1: Explicit competitor match — REJECT
        product_match = sum(1 for kw in product_keywords if kw in combined)
        seller_match = sum(1 for sig in _SELLER_SIGNALS if sig in combined)
        if product_match >= 2 and seller_match >= 1:
            rejected_competitors += 1
            continue

        # Step 2: Target segment match — KEEP (highest priority)
        segment_match = any(term and term in combined for term in segment_terms)
        if segment_match:
            kept.append(c)
            continue

        # Step 3: Maps source with address — KEEP (trust 2GIS/Yandex geo-filter)
        #   Maps already filtered by geography + category, even without segment word
        #   the result is likely a real B2B lead near the target city
        if is_maps and c.get("address"):
            kept.append(c)
            continue

        # Step 4: Web result without segment match — REJECT
        #   Without LLM to judge, we can't trust a random web page matching the niche
        rejected_irrelevant += 1

    logger.info(
        f"Rule-based filter (strict): {len(candidates)} -> {len(kept)} kept | "
        f"rejected: competitors={rejected_competitors}, irrelevant={rejected_irrelevant}"
    )
    return kept

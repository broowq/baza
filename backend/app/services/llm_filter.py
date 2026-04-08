"""Lead quality filter: AI-powered with rule-based fallback.

When Anthropic API is available, uses Claude for smart filtering.
When unavailable (geo-blocked, no key), uses rule-based competitor detection.
"""
import logging
import re
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        settings = get_settings()
        api_key = settings.anthropic_api_key
        if not api_key:
            return None
        try:
            import anthropic
            kwargs = {"api_key": api_key}
            if settings.anthropic_base_url:
                kwargs["base_url"] = settings.anthropic_base_url
            _client = anthropic.Anthropic(**kwargs)
        except Exception:
            logger.warning("Failed to initialize Anthropic client")
            return None
    return _client


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
    client = _get_client()
    if client:
        try:
            result = _ai_filter(client, candidates, niche, geography, segments, prompt)
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
    client,
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
        kept = _ai_filter_batch(client, batch, niche, geography, segments, prompt)
        if kept is None:
            return None  # Signal failure to caller
        all_kept.extend(kept)

    logger.info(
        f"AI filter: {len(candidates)} candidates -> {len(all_kept)} kept "
        f"({len(candidates) - len(all_kept)} rejected)"
    )
    return all_kept


def _ai_filter_batch(client, batch, niche, geography, segments, prompt) -> list[dict] | None:
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
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": filter_prompt}],
        )
        answer = response.content[0].text.strip()

        if answer.strip() == "0":
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
    """Filter out competitors using rule-based heuristics.

    Logic: if a company name/description contains the PRODUCT keywords from the
    user's prompt AND contains seller signals, it's likely a competitor.
    """
    product_keywords = _extract_product_keywords(prompt)
    if not product_keywords:
        return candidates

    # Build set of segment terms (these are TARGET customer types)
    segment_terms = set()
    for seg in segments:
        for word in seg.lower().split():
            if len(word) >= 3:
                segment_terms.add(word)

    kept = []
    for c in candidates:
        company = (c.get("company") or "").lower()
        snippet = (c.get("snippet") or "").lower()
        domain = (c.get("domain") or "").lower()
        categories = " ".join(c.get("categories") or []).lower()
        combined = f"{company} {snippet} {domain} {categories}"

        # Check if company matches a target segment (always keep)
        segment_match = any(term in combined for term in segment_terms if term)
        if segment_match:
            kept.append(c)
            continue

        # Check if company looks like a competitor (sells the same product)
        product_match = sum(1 for kw in product_keywords if kw in combined)
        seller_match = sum(1 for sig in _SELLER_SIGNALS if sig in combined)

        # Strong competitor signal: mentions the product AND selling activity
        if product_match >= 2 and seller_match >= 1:
            logger.debug(f"Filtered competitor: {c.get('company')} (product={product_match}, seller={seller_match})")
            continue

        # Keep everything else — maps results, generic businesses, etc.
        kept.append(c)

    return kept

"""AI-powered lead quality filter using Claude API."""
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
            _client = anthropic.Anthropic(api_key=api_key)
        except Exception:
            logger.warning("Failed to initialize Anthropic client")
            return None
    return _client


def filter_candidates_llm(
    candidates: list[dict],
    niche: str,
    geography: str,
    segments: list[str],
) -> list[dict]:
    """Filter ALL candidates using LLM for relevance and quality.

    Sends batches of up to 30 candidates to Claude Haiku for evaluation.
    Each candidate gets a relevance verdict: KEEP or REJECT.

    If no API key configured, returns candidates unchanged (graceful degradation).
    """
    client = _get_client()
    if not client:
        return candidates

    if not candidates:
        return candidates

    # Process in batches of 30
    BATCH_SIZE = 30
    all_kept = []

    for batch_start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_start:batch_start + BATCH_SIZE]
        kept = _filter_batch(client, batch, niche, geography, segments)
        all_kept.extend(kept)

    logger.info(
        f"LLM filter: {len(candidates)} candidates -> {len(all_kept)} kept "
        f"({len(candidates) - len(all_kept)} rejected)"
    )
    return all_kept


def _filter_batch(
    client,
    batch: list[dict],
    niche: str,
    geography: str,
    segments: list[str],
) -> list[dict]:
    """Filter a single batch of candidates."""
    lines = []
    for i, c in enumerate(batch):
        company = c.get("company", "—")
        domain = c.get("domain", "—")
        city = c.get("city", "—")
        desc = (c.get("description") or c.get("snippet") or "")[:150]
        category = c.get("category", "")
        address = c.get("address", "")

        parts = [f"{i+1}. {company}"]
        if domain and domain != "—":
            parts.append(f"сайт: {domain}")
        if city and city != "—":
            parts.append(f"город: {city}")
        if category:
            parts.append(f"категория: {category}")
        if address:
            parts.append(f"адрес: {address}")
        if desc:
            parts.append(f"описание: {desc}")

        lines.append(" | ".join(parts))

    candidates_text = "\n".join(lines)
    segments_str = ", ".join(segments) if segments else "не указаны"

    prompt = f"""Ты — строгий фильтр качества B2B лидов для платформы лидогенерации.

ЗАДАЧА: Оцени каждого кандидата и реши — подходит ли он как потенциальный клиент/партнёр.

НИША ПОИСКА: {niche}
ГЕОГРАФИЯ: {geography}
СЕГМЕНТЫ: {segments_str}

КРИТЕРИИ ОТКЛОНЕНИЯ (REJECT):
- Компания НЕ относится к указанной нише (например, ищем деревообработку, а нашли автосервис)
- Это агрегатор, каталог, справочник, а не реальная компания
- Это ликвидированная/закрытая компания (если видно из описания)
- Это государственное учреждение, не являющееся потенциальным клиентом
- Домен явно не принадлежит компании (общий хостинг, социальная сеть)
- Компания из другого региона (если указана конкретная география)

КРИТЕРИИ СОХРАНЕНИЯ (KEEP):
- Компания работает в указанной нише или смежной области
- Компания из указанного региона (или региональный фильтр не критичен)
- Это реальный действующий бизнес
- Даже если информации мало — если ниша совпадает, сохраняем

ФОРМАТ ОТВЕТА: Только номера ПОДХОДЯЩИХ кандидатов через запятую. Если ни один не подходит — напиши "0".

КАНДИДАТЫ:
{candidates_text}

ПОДХОДЯЩИЕ:"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        answer = response.content[0].text.strip()

        if answer.strip() == "0":
            return []

        kept_indices: set[int] = set()
        # Parse comma-separated numbers, handling various formats
        for part in re.findall(r"\d+", answer):
            try:
                idx = int(part) - 1  # 1-indexed to 0-indexed
                if 0 <= idx < len(batch):
                    kept_indices.add(idx)
            except ValueError:
                continue

        if not kept_indices:
            # If parsing failed, keep all (don't lose data)
            logger.warning(f"LLM filter: could not parse response '{answer}', keeping all")
            return batch

        return [c for i, c in enumerate(batch) if i in kept_indices]

    except Exception as e:
        logger.warning(f"LLM filter batch failed: {e}. Keeping all candidates.")
        return batch

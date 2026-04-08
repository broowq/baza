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
    """Filter ALL candidates using LLM for relevance and quality.

    When a prompt is provided, the filter understands that niche/segments
    represent TARGET CUSTOMERS, not the user's own business.
    """
    client = _get_client()
    if not client:
        return candidates

    if not candidates:
        return candidates

    BATCH_SIZE = 30
    all_kept = []

    for batch_start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_start:batch_start + BATCH_SIZE]
        kept = _filter_batch(client, batch, niche, geography, segments, prompt=prompt)
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
    *,
    prompt: str = "",
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

    if prompt:
        # Customer-focused filter: the user described their business,
        # niche/segments are target CUSTOMER types
        filter_prompt = f"""Ты — строгий фильтр качества B2B лидов для платформы лидогенерации.

КОНТЕКСТ: Пользователь описал свой бизнес так: "{prompt}"
Мы ищем ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ для этого бизнеса — компании, которым можно ПРОДАТЬ товар/услугу пользователя.

ЦЕЛЕВАЯ НИША КЛИЕНТОВ: {niche}
ГЕОГРАФИЯ: {geography}
ЦЕЛЕВЫЕ СЕГМЕНТЫ: {segments_str}

КРИТЕРИИ ОТКЛОНЕНИЯ (REJECT):
- Компания является КОНКУРЕНТОМ (продаёт то же самое, что и пользователь)
- Это агрегатор, каталог, справочник, маркетплейс — не реальная компания
- Это ликвидированная/закрытая компания
- Компания НЕ может быть потенциальным покупателем/клиентом
- Это информационный сайт, блог, новостной портал
- Компания из другого региона (если указана конкретная география)

КРИТЕРИИ СОХРАНЕНИЯ (KEEP):
- Компания может быть ПОКУПАТЕЛЕМ товара/услуги пользователя
- Компания работает в сфере, где нужен товар/услуга пользователя
- Это реальный действующий бизнес из указанного региона
- Даже если мало информации — если тип бизнеса подходит как клиент, сохраняем

ФОРМАТ ОТВЕТА: Только номера ПОДХОДЯЩИХ кандидатов через запятую. Если ни один не подходит — напиши "0".

КАНДИДАТЫ:
{candidates_text}

ПОДХОДЯЩИЕ:"""
    else:
        # Legacy filter: direct niche matching
        filter_prompt = f"""Ты — строгий фильтр качества B2B лидов для платформы лидогенерации.

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
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": filter_prompt}],
        )

        answer = response.content[0].text.strip()

        if answer.strip() == "0":
            return []

        kept_indices: set[int] = set()
        for part in re.findall(r"\d+", answer):
            try:
                idx = int(part) - 1
                if 0 <= idx < len(batch):
                    kept_indices.add(idx)
            except ValueError:
                continue

        if not kept_indices:
            logger.warning(f"LLM filter: could not parse response '{answer}', keeping all")
            return batch

        return [c for i, c in enumerate(batch) if i in kept_indices]

    except Exception as e:
        logger.warning(f"LLM filter batch failed: {e}. Keeping all candidates.")
        return batch

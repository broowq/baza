"""AI-powered prompt enhancement for B2B lead search.

Takes a raw user description of their business and product/service,
and generates an optimized search strategy to find POTENTIAL CUSTOMERS,
not competitors.
"""
import json
import logging

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
            logger.warning("Failed to initialize Anthropic client for prompt enhancer")
            return None
    return _client


def enhance_prompt(raw_prompt: str) -> dict:
    """Take a user's raw business description and generate a search strategy.

    Returns dict with:
        - enhanced_prompt: improved version of the user's description
        - project_name: suggested short project name
        - niche: extracted target customer niche (who to search for)
        - geography: extracted geography
        - segments: list of target customer segments
        - search_queries: list of optimized search queries for finding CUSTOMERS
        - explanation: brief explanation of the strategy
    """
    client = _get_client()
    if not client:
        return _fallback_parse(raw_prompt)

    system_prompt = """Ты — AI-ассистент B2B платформы лидогенерации БАЗА. Твоя задача — проанализировать описание бизнеса пользователя и создать стратегию поиска ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ.

ВАЖНО: Пользователь описывает СВОЙ бизнес и что он продаёт/предлагает. Тебе нужно определить, КТО будет ПОКУПАТЕЛЕМ его товара/услуги, и настроить поиск именно этих компаний.

Пример:
- Пользователь: "Продаю кормовые добавки для животных в Томске"
- НЕПРАВИЛЬНО: искать компании, которые продают кормовые добавки (это конкуренты!)
- ПРАВИЛЬНО: искать животноводческие фермы, птицефабрики, свинокомплексы, зоомагазины, ветклиники, агрохолдинги — тех, кому НУЖНЫ кормовые добавки

Ещё пример:
- Пользователь: "Делаем сайты и мобильные приложения"
- НЕПРАВИЛЬНО: искать веб-студии (конкуренты!)
- ПРАВИЛЬНО: искать компании без сайта или с плохим сайтом, стартапы, малый бизнес, рестораны, магазины — тех, кому НУЖЕН сайт

Ответь СТРОГО в JSON формате:
{
  "enhanced_prompt": "Улучшенная версия описания бизнеса пользователя (1-2 предложения)",
  "project_name": "Короткое название проекта (2-4 слова)",
  "niche": "Целевая ниша КЛИЕНТОВ (не продавца!), например: животноводство, птицеводство",
  "geography": "Извлечённый регион/город или 'Россия' если не указан",
  "segments": ["сегмент1", "сегмент2", "сегмент3"],
  "target_customer_types": ["тип клиента 1", "тип клиента 2", "тип клиента 3"],
  "search_queries_niche": "Ключевые слова для поиска КЛИЕНТОВ на картах (Яндекс/2ГИС)",
  "explanation": "Краткое объяснение стратегии поиска (1-2 предложения)"
}

Поля segments и target_customer_types — это типы компаний, которые могут быть ПОКУПАТЕЛЯМИ.
search_queries_niche — это то, что будет искаться на картах и в поисковиках (ниша клиента, не продавца)."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": raw_prompt}],
        )
        answer = response.content[0].text.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0].strip()
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0].strip()

        result = json.loads(answer)

        # Validate required fields
        required = ["niche", "geography", "segments", "project_name"]
        for field in required:
            if field not in result:
                logger.warning(f"Missing field '{field}' in LLM response, falling back")
                return _fallback_parse(raw_prompt)

        # Ensure segments is a list
        if isinstance(result.get("segments"), str):
            result["segments"] = [s.strip() for s in result["segments"].split(",")]

        result["raw_prompt"] = raw_prompt
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse LLM response as JSON: {e}")
        return _fallback_parse(raw_prompt)
    except Exception as e:
        logger.warning(f"Prompt enhancement failed: {e}")
        return _fallback_parse(raw_prompt)


def _fallback_parse(raw_prompt: str) -> dict:
    """Simple rule-based fallback when LLM is not available."""
    words = raw_prompt.strip().split()

    # Try to extract geography (common Russian cities)
    cities = [
        "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
        "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
        "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград", "Краснодар",
        "Саратов", "Тюмень", "Тольятти", "Ижевск", "Барнаул", "Ульяновск",
        "Иркутск", "Хабаровск", "Ярославль", "Владивосток", "Махачкала",
        "Томск", "Оренбург", "Кемерово", "Новокузнецк", "Рязань",
    ]

    geography = "Россия"
    prompt_lower = raw_prompt.lower()
    for city in cities:
        if city.lower() in prompt_lower:
            geography = city
            break

    return {
        "enhanced_prompt": raw_prompt,
        "project_name": " ".join(words[:4]) if len(words) > 4 else raw_prompt[:50],
        "niche": raw_prompt[:120],
        "geography": geography,
        "segments": [],
        "target_customer_types": [],
        "search_queries_niche": raw_prompt[:120],
        "explanation": "Автоматический анализ без AI. Рекомендуем добавить ключ Anthropic API для лучших результатов.",
        "raw_prompt": raw_prompt,
    }

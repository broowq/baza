"""AI-powered prompt enhancement for B2B lead search.

Takes a raw user description of their business and product/service,
and generates an optimized search strategy to find POTENTIAL CUSTOMERS,
not competitors.
"""
import json
import logging
import re

from app.services import llm_client

logger = logging.getLogger(__name__)


# ── Smart rule-based customer mapping ──
# Maps what someone SELLS to who would BUY it.
# IMPORTANT: More specific multi-word phrases are prioritized (higher score per match).
# Order in list matters — specific industries are checked first.
_PRODUCT_TO_CUSTOMERS = [
    # ── Very specific B2B contexts (go FIRST) ──
    # Office / hospitality furniture for B2B — users SELLING to businesses
    {
        "keywords": ["офисная мебель", "гостиничная мебель", "мебель для офиса",
                      "мебель для отелей", "мебель для ресторанов", "мебель на заказ",
                      "корпоративная мебель", "мебель для бизнеса", "b2b мебель",
                      "мебель для гостиниц", "мебель для кафе"],
        "niche": "офисы, отели, рестораны, бизнес-центры",
        "segments": ["бизнес-центр", "офисный центр", "отель", "гостиница",
                     "ресторан", "кафе", "коворкинг", "деловой центр"],
        "target_types": ["Бизнес-центры", "Отели", "Гостиницы", "Рестораны", "Коворкинги"],
        "search_niche": "бизнес-центр отель гостиница ресторан коворкинг",
    },
    # HoReCa equipment — kitchen / bar / hotel equipment
    # Matches both "оборудование для ресторанов" and "оборудования для кафе"
    # by using root stems. Requires at least 2 keywords (equipment + venue).
    {
        "keywords": ["оборудован", "кухонн", "барн", "ресторан",
                      "кафе", "столов", "пекарн", "общепит",
                      "horeca", "хорека", "фаст-фуд", "фастфуд",
                      "ресторанное", "гостиничн"],
        "niche": "рестораны, кафе, столовые, отели",
        "segments": ["ресторан", "кафе", "столовая", "отель", "гостиница",
                     "пекарня", "кондитерская", "бар", "пиццерия", "фастфуд"],
        "target_types": ["Рестораны", "Кафе", "Столовые", "Отели", "Пекарни", "Пиццерии"],
        "search_niche": "ресторан кафе столовая отель пекарня пиццерия бар",
    },
    # Accounting / Tax / Legal services for B2B
    {
        "keywords": ["бухгалтерск", "бухучет", "бухгалтери", "налогов",
                      "аудит", "аутсорсинг бухгалтерии", "ведение налоговой",
                      "юридическ услуг", "правов консультац"],
        "niche": "малый и средний бизнес, ИП, ООО",
        "segments": ["магазин", "салон красоты", "стоматология", "автосервис",
                     "ресторан", "кафе", "медицинский центр", "фитнес-клуб",
                     "турагентство", "строительная компания"],
        "target_types": ["Магазины", "Салоны красоты", "Стоматологии", "Автосервисы",
                         "Рестораны", "Фитнес-клубы"],
        "search_niche": "магазин салон красоты стоматология автосервис фитнес-клуб",
    },
    # Cleaning services (MOVED UP — must beat Industrial "промышлен" match)
    # Targets commercial real estate, hospitality, industrial sites needing cleaning
    {
        "keywords": ["клинин", "уборк", "клининг", "химчист", "стирк",
                      "чистк", "мойк", "клининговые услуги",
                      "уборка офисов", "уборка помещений",
                      "профессиональная уборка"],
        "niche": "коммерческая недвижимость, HoReCa, торговые центры",
        "segments": ["бизнес-центр", "торговый центр", "отель", "гостиница",
                     "ресторан", "медицинский центр", "фитнес-клуб",
                     "коворкинг", "офисный центр", "управляющая недвижимостью"],
        "target_types": ["Бизнес-центры", "ТЦ", "Отели", "Рестораны", "Клиники", "Фитнес-клубы"],
        "search_niche": "бизнес-центр торговый центр отель гостиница ресторан медицинский центр",
    },
    # Vet / Animal products
    {
        "keywords": ["кормов", "корм ", "комбикорм", "премикс", "добавк", "ветеринар", "ветпрепарат",
                      "вакцин", "антибиотик", "витамин для животн"],
        "niche": "животноводство, птицеводство, сельское хозяйство",
        "segments": ["птицефабрика", "свиноферма", "животноводческая ферма", "агрохолдинг",
                     "зоомагазин", "ветеринарная клиника", "конный клуб", "рыбоводство"],
        "target_types": ["Птицефабрики", "Свинофермы", "КФХ", "Агрохолдинги", "Зоомагазины", "Ветклиники"],
        "search_niche": "ферма птицефабрика свиноферма агрохолдинг зоомагазин ветклиника",
    },
    # Construction materials
    {
        "keywords": ["стройматериал", "бетон", "кирпич", "цемент", "арматур", "пиломатериал",
                      "утеплител", "кровл", "фасад", "штукатурк", "гипсокартон", "строительн"],
        "niche": "строительство, девелопмент, ремонт",
        "segments": ["строительная компания", "девелопер", "застройщик", "подрядчик",
                     "ремонтная бригада", "архитектурное бюро", "управляющая компания"],
        "target_types": ["Строительные компании", "Застройщики", "Подрядчики", "Ремонтные бригады"],
        "search_niche": "строительная компания застройщик подрядчик ремонт квартир",
    },
    # Wood / Timber — raw timber materials (not furniture)
    {
        "keywords": ["древесин", "пиломатериал", "брус ", "доска ", "фанер", "деревообработк",
                      "вагонк", "паркет", "лесоматериал", "дерев"],
        "niche": "мебельное производство, строительство, столярные мастерские",
        "segments": ["мебельная фабрика", "столярная мастерская", "строительная компания",
                     "дизайн интерьера", "бани под ключ", "деревянное домостроение"],
        "target_types": ["Мебельные фабрики", "Столярные мастерские", "Строители деревянных домов"],
        "search_niche": "мебельная фабрика столярная мастерская деревянное домостроение",
    },
    # IT / Web development
    {
        "keywords": ["сайт", "приложени", "разработк", "программир", "веб-", "web ", "мобильн",
                      "crm", "erp", "автоматизац", "софт", "it ", "ит "],
        "niche": "малый и средний бизнес, e-commerce, HoReCa",
        "segments": ["ресторан", "магазин", "салон красоты", "стоматология", "автосервис",
                     "фитнес-клуб", "турагентство", "юридическая компания"],
        "target_types": ["Рестораны", "Магазины", "Салоны красоты", "Клиники", "Автосервисы"],
        "search_niche": "ресторан салон красоты стоматология автосервис магазин",
    },
    # Marketing / Advertising
    {
        "keywords": ["маркетинг", "реклам", "smm", "seo", "продвижени", "таргет", "контент",
                      "брендинг", "pr ", "пиар", "дизайн"],
        "niche": "малый и средний бизнес, стартапы, e-commerce",
        "segments": ["интернет-магазин", "ресторан", "клиника", "застройщик",
                     "производственная компания", "юридическая фирма"],
        "target_types": ["Интернет-магазины", "Рестораны", "Клиники", "Застройщики"],
        "search_niche": "интернет-магазин ресторан клиника застройщик производство",
    },
    # Food products / wholesale
    {
        "keywords": ["продукт питан", "продовольств", "молоч", "мяс", "колбас", "заморож",
                      "полуфабрикат", "кондитерск", "хлеб", "напитк", "снек"],
        "niche": "розничная торговля, общепит, HoReCa",
        "segments": ["продуктовый магазин", "супермаркет", "ресторан", "кафе", "столовая",
                     "отель", "детский сад", "школа", "больница"],
        "target_types": ["Магазины продуктов", "Рестораны", "Кафе", "Столовые", "Отели"],
        "search_niche": "продуктовый магазин ресторан кафе столовая отель",
    },
    # Industrial equipment
    {
        "keywords": ["оборудован", "станк", "компрессор", "насос", "генератор", "конвейер",
                      "промышлен", "запчаст", "инструмент", "электро"],
        "niche": "производственные предприятия, заводы, фабрики",
        "segments": ["завод", "фабрика", "производственная компания", "цех",
                     "горнодобывающая компания", "нефтегазовая компания"],
        "target_types": ["Заводы", "Фабрики", "Производственные компании", "Цеха"],
        "search_niche": "завод фабрика производство цех предприятие",
    },
    # Transport / Logistics
    {
        "keywords": ["перевозк", "логистик", "доставк", "транспорт", "грузоперевоз",
                      "склад", "фулфилмент", "карго"],
        "niche": "производство, e-commerce, торговля",
        "segments": ["интернет-магазин", "производственная компания", "торговая компания",
                     "оптовая база", "строительная компания"],
        "target_types": ["Интернет-магазины", "Производства", "Торговые компании", "Оптовые базы"],
        "search_niche": "интернет-магазин производство торговая компания оптовая база",
    },
    # Packaging
    {
        "keywords": ["упаков", "тар ", "тары", "коробк", "пакет", "этикетк", "полиэтилен", "стрейч"],
        "niche": "пищевое производство, e-commerce, торговля",
        "segments": ["пищевое производство", "кондитерская", "молокозавод", "пивоварня",
                     "интернет-магазин", "косметическая компания"],
        "target_types": ["Пищевые производства", "Кондитерские", "Интернет-магазины", "Косметические компании"],
        "search_niche": "пищевое производство кондитерская молокозавод пивоварня",
    },
    # Security
    {
        "keywords": ["охран", "безопасност", "видеонаблюден", "сигнализац", "скуд", "контроль доступ",
                      "пожарн", "огнетуш"],
        "niche": "коммерческая недвижимость, склады, офисы",
        "segments": ["бизнес-центр", "торговый центр", "склад", "банк",
                     "ювелирный магазин", "аптека", "застройщик"],
        "target_types": ["Бизнес-центры", "ТЦ", "Склады", "Банки", "Застройщики"],
        "search_niche": "бизнес-центр торговый центр склад банк застройщик",
    },
    # Textiles / Uniforms
    {
        "keywords": ["спецодежд", "униформ", "текстил", "ткан", "пошив", "швейн", "одежд оптом"],
        "niche": "производственные предприятия, HoReCa, медицина",
        "segments": ["завод", "больница", "ресторан", "отель", "строительная компания",
                     "клининговая компания", "охранное предприятие"],
        "target_types": ["Заводы", "Больницы", "Рестораны", "Отели", "Строительные компании"],
        "search_niche": "завод больница ресторан отель строительная компания",
    },
]


def enhance_prompt(raw_prompt: str) -> dict:
    """Take a user's raw business description and generate a search strategy."""
    if llm_client.is_configured():
        result = _try_llm_enhance(raw_prompt)
        if result:
            return result

    # Fallback to smart rule-based enhancement
    return _smart_fallback(raw_prompt)


def _try_llm_enhance(raw_prompt: str) -> dict | None:
    """Try to enhance using LLM. Returns None on failure."""
    system_prompt = """Ты — AI-ассистент B2B платформы лидогенерации БАЗА. Твоя задача — проанализировать описание бизнеса пользователя и создать стратегию поиска ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ.

ВАЖНО: Пользователь описывает СВОЙ бизнес и что он продаёт/предлагает. Тебе нужно определить, КТО будет ПОКУПАТЕЛЕМ его товара/услуги, и настроить поиск именно этих компаний.

Пример:
- Пользователь: "Продаю кормовые добавки для животных в Томске"
- НЕПРАВИЛЬНО: искать компании, которые продают кормовые добавки (это конкуренты!)
- ПРАВИЛЬНО: искать животноводческие фермы, птицефабрики, свинокомплексы, зоомагазины, ветклиники, агрохолдинги — тех, кому НУЖНЫ кормовые добавки

Ответь СТРОГО в JSON формате (без markdown, без ```):
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
        answer = llm_client.chat(
            raw_prompt,
            system=system_prompt,
            max_tokens=800,
            temperature=0.3,
        )
        if not answer:
            return None
        answer = answer.strip()

        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0].strip()
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0].strip()

        # Extract JSON object if LLM added extra text
        first_brace = answer.find("{")
        last_brace = answer.rfind("}")
        if first_brace != -1 and last_brace != -1:
            answer = answer[first_brace:last_brace + 1]

        result = json.loads(answer)

        required = ["niche", "geography", "segments", "project_name"]
        for field in required:
            if field not in result:
                return None

        if isinstance(result.get("segments"), str):
            result["segments"] = [s.strip() for s in result["segments"].split(",")]

        result["raw_prompt"] = raw_prompt
        return result

    except Exception as e:
        logger.warning(f"LLM prompt enhancement failed: {e}")
        return None


def _smart_fallback(raw_prompt: str) -> dict:
    """Smart rule-based fallback: maps product/service → target customers."""
    prompt_lower = raw_prompt.lower().strip()

    # Extract geography
    geography = _extract_geography(prompt_lower)

    # Try to match against known product → customer mappings.
    # Scoring: longer phrases weigh more (a 2-word phrase match is ~4x stronger
    # than a single-word root match). This ensures specific B2B contexts like
    # "офисная мебель" beat generic "мебельн"/"дерев" mapping.
    best_match = None
    best_score = 0.0

    for mapping in _PRODUCT_TO_CUSTOMERS:
        score = 0.0
        for keyword in mapping["keywords"]:
            if keyword in prompt_lower:
                # Score proportional to keyword length (longer = more specific)
                # 3-char stem = 1.0, 10-char word = 3.0, 20-char phrase = 5.0
                word_count = max(1, len(keyword.strip().split()))
                length_bonus = min(len(keyword) / 4.0, 5.0)
                score += length_bonus * (1.5 if word_count > 1 else 1.0)
        if score > best_score:
            best_score = score
            best_match = mapping

    if best_match and best_score >= 1.0:
        # Clean prompt from geography and action words for project name
        clean_name = re.sub(
            r'\b(продаю|продаём|оказываю|предлагаю|делаю|произвожу|поставляю|в\s+\w+е?)\b',
            '', raw_prompt, flags=re.IGNORECASE
        ).strip()
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()
        project_name = clean_name[:50] if clean_name else raw_prompt[:50]

        return {
            "enhanced_prompt": raw_prompt,
            "project_name": f"Клиенты: {project_name[:40]}",
            "niche": best_match["niche"],
            "geography": geography,
            "segments": best_match["segments"],
            "target_customer_types": best_match["target_types"],
            "search_queries_niche": best_match["search_niche"],
            "explanation": f"Ищем потенциальных покупателей: {', '.join(best_match['target_types'][:4])}",
            "raw_prompt": raw_prompt,
        }

    # No match — generic fallback
    return {
        "enhanced_prompt": raw_prompt,
        "project_name": raw_prompt[:50],
        "niche": raw_prompt[:120],
        "geography": geography,
        "segments": [],
        "target_customer_types": [],
        "search_queries_niche": raw_prompt[:120],
        "explanation": "Не удалось автоматически определить целевых клиентов. Уточните нишу вручную.",
        "raw_prompt": raw_prompt,
    }


def _extract_geography(text: str) -> str:
    """Extract city name from Russian text."""
    cities = [
        "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
        "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
        "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград", "Краснодар",
        "Саратов", "Тюмень", "Тольятти", "Ижевск", "Барнаул", "Ульяновск",
        "Иркутск", "Хабаровск", "Ярославль", "Владивосток", "Махачкала",
        "Томск", "Оренбург", "Кемерово", "Новокузнецк", "Рязань", "Астрахань",
        "Пенза", "Липецк", "Тула", "Киров", "Чебоксары", "Калининград",
        "Брянск", "Курск", "Иваново", "Магнитогорск", "Тверь", "Белгород",
        "Сочи", "Сургут", "Владимир", "Нижний Тагил", "Архангельск",
        "Чита", "Калуга", "Смоленск", "Волжский", "Якутск", "Саранск",
        "Вологда", "Комсомольск-на-Амуре", "Мурманск", "Тамбов",
    ]

    # Check for prepositional forms (в Томске → Томск)
    city_forms = {}
    for city in cities:
        city_forms[city.lower()] = city
        # Common prepositional case endings
        if city.endswith("ск"):
            city_forms[city.lower() + "е"] = city
        elif city.endswith("а"):
            city_forms[city.lower()[:-1] + "е"] = city
        elif city.endswith("ь"):
            city_forms[city.lower()[:-1] + "и"] = city

    for form, original in city_forms.items():
        if form in text:
            return original

    return "Россия"

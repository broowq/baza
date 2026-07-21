"""
Модуль скоринга лидов БАЗА.

Итоговый score (0–100) складывается из:
  base            — базовый балл (по умолчанию 35)
  + domain        — есть домен (+10)
  + email         — есть email (+20)
  + phone         — есть телефон (+10)
  + address       — есть адрес (+8)
  + keyword_bonus — ключевое слово ниши в имени/домене/описании (+12)
  - no_contacts_penalty  — нет ни email, ни телефона, ни домена (−12);
                           адрес контактом НЕ считается (только свои +8)
  - demo_penalty         — демо/фолбэк лид (−20)
  - aggregator_penalty   — агрегатор/каталог (−25)
  - seller_penalty       — продавцовая сигнатура в имени/домене при охоте
                           на покупателей (−15, см. _SELLER_MARKERS)

Аудит P0: лид без единого матч-сигнала (keyword / segment / relevance) не
может получить больше 70 — полный набор контактов сам по себе не делает лид
«горячим» (≥80).

Веса можно переопределить через env-переменные:
  SCORING_WEIGHTS_JSON  = '{"base":35,"email":20,...}'
  SCORING_NICHE_WEIGHTS_JSON = '{"деревообработка":{"keyword_bonus":10}}'
"""

from app.core.config import get_settings
from app.utils.url_tools import is_aggregator_domain

# Русские нишевые ключевые слова (слова, присутствие в домене/компании дает бонус)
NICHE_KEYWORDS: dict[str, list[str]] = {
    # --- Existing 8 niches ---
    "деревообработка": ["лес", "дерев", "пилом", "вагонк", "погонаж", "паркет", "брус", "доск", "пиломат"],
    "строительство": ["строй", "ремонт", "монтаж", "стройматер", "кровля", "кирпич", "цемент", "бетон"],
    "it": ["tech", "soft", "dev", "cloud", "digital", "it-", "информ", "программ"],
    "медицина": ["мед", "клиник", "здоров", "аптек", "фармац", "диагност"],
    "юридические услуги": ["юрид", "правов", "адвокат", "нотари", "юрист"],
    "бухгалтерия": ["бухгалт", "аудит", "налог", "учет", "финанс"],
    "логистика": ["логист", "доставк", "грузовой", "транспорт", "склад", "карго"],
    "пищевая промышленность": ["продукт", "пищев", "еда", "напит", "мяс", "молок", "хлеб"],
    # --- New niches (45+) ---
    # 1. IT / Software
    "программирование": ["программ", "разработк", "софт", "кодинг", "приложен", "devops", "backend", "frontend"],
    # 2. Marketing / Advertising
    "маркетинг": ["маркетинг", "реклам", "продвижен", "smm", "seo", "брендинг", "пиар", "таргет"],
    # 3. Education
    "образование": ["образован", "обучен", "школ", "курс", "репетитор", "тренинг", "лекци", "педагог"],
    # 4. Real estate
    "недвижимость": ["недвижимост", "риелтор", "квартир", "новостройк", "ипотек", "застройщик", "жилье"],
    # 5. Finance / Banking
    "финансы": ["финанс", "банк", "кредит", "инвестиц", "вклад", "страхов", "брокер", "займ"],
    # 6. Law / Legal
    "юрист": ["юрист", "адвокат", "правов", "судебн", "арбитраж", "нотариус", "правовой", "законод"],
    # 7. Auto / Car services
    "автосервис": ["автосервис", "автомобил", "автозапчаст", "шиномонтаж", "автомойк", "кузовн", "сто"],
    # 8. Beauty / Salon
    "салон красоты": ["салон", "красот", "парикмахер", "косметолог", "маникюр", "педикюр", "визажист", "эпиляц"],
    # 9. Fitness / Sports
    "фитнес": ["фитнес", "спорт", "тренажер", "тренировк", "спортзал", "йога", "пилатес", "кроссфит"],
    # 10. Travel / Tourism
    "туризм": ["туризм", "путешеств", "тур", "экскурси", "отель", "гостиниц", "бронирован", "визов"],
    # 11. Logistics / Transport (supplement to existing)
    "перевозки": ["перевозк", "грузоперевозк", "фура", "экспедиц", "таможн", "контейнер", "карго"],
    # 12. Agriculture
    "сельское хозяйство": ["агро", "фермер", "урожай", "зерно", "посев", "удобрен", "животновод", "растениевод"],
    # 13. Food production
    "пищевое производство": ["пищепром", "кондитер", "хлебопек", "мясопереработ", "молочн", "консерв"],
    # 14. Cleaning
    "клининг": ["клининг", "уборк", "химчистк", "чистот", "мойк", "дезинфекц", "стирк"],
    # 15. Security
    "охрана": ["охран", "безопасност", "чоп", "видеонаблюден", "пожарн", "сигнализац", "пульт"],
    # 16. Printing
    "типография": ["типограф", "полиграф", "печат", "визитк", "баннер", "листовк", "буклет", "этикетк"],
    # 17. Furniture
    "мебель": ["мебел", "кухн", "шкаф", "диван", "кроват", "стол", "фурнитур", "корпусн"],
    # 18. Textile / Clothing
    "текстиль": ["текстил", "одежд", "швейн", "ткан", "трикотаж", "пошив", "выкройк", "ателье"],
    # 19. Pharmacy
    "аптека": ["аптек", "фармацевт", "лекарств", "препарат", "бад", "витамин", "медикамент"],
    # 20. Veterinary
    "ветеринар": ["ветеринар", "ветклиник", "зоо", "животн", "питомец", "вакцинац", "ветврач"],
    # 21. Photography
    "фотограф": ["фотограф", "видеосъемк", "фотосесси", "фотостуди", "видеограф", "съемк", "монтаж видео"],
    # 22. Event / Wedding
    "мероприятия": ["свадьб", "мероприят", "праздник", "банкет", "тамада", "декор", "кейтеринг", "торжеств"],
    # 23. Dental
    "стоматология": ["стоматолог", "зубн", "ортодонт", "имплант", "протезирован", "отбеливан", "пломб"],
    # 24. Optics
    "оптика": ["оптик", "очк", "линз", "зрен", "офтальмолог", "контактн", "оправ"],
    # 25. Electronics / Repair
    "ремонт техники": ["ремонт техник", "электроник", "сервисн", "компьютер", "ноутбук", "телефон", "бытов техник"],
    # 26. Metal / Welding
    "металлообработка": ["металл", "сварк", "ковк", "токарн", "фрезер", "металлоконструкц", "прокат", "литье"],
    # 27. Glass / Windows
    "окна": ["окн", "стеклопакет", "остеклен", "стекл", "витраж", "фасадн", "профил", "балкон"],
    # 28. Roofing
    "кровля": ["кровл", "крыш", "черепиц", "водосток", "гидроизоляц", "мягк кровл", "профнастил"],
    # 29. Plumbing
    "сантехника": ["сантехник", "водоснабж", "канализац", "трубопровод", "отоплен", "котел", "бойлер"],
    # 30. Electrical
    "электрика": ["электрик", "электромонтаж", "электропровод", "щитов", "освещен", "розетк", "кабел"],
    # 31. Landscaping
    "ландшафт": ["ландшафт", "озеленен", "благоустройств", "газон", "цветник", "дренаж", "полив"],
    # 32. Accounting (supplement to existing)
    "аудит": ["аудит", "бухгалтерск", "отчетност", "налогов", "баланс", "ревизи", "бухучет"],
    # 33. HR / Recruiting
    "кадры": ["кадр", "рекрутинг", "персонал", "подбор", "вакансии", "hr", "трудоустройств", "резюме"],
    # 34. Insurance
    "страхование": ["страхован", "полис", "каско", "осаго", "страховк", "выплат", "андеррайтинг"],
    # 35. Consulting
    "консалтинг": ["консалтинг", "консультац", "аутсорсинг", "стратеги", "оптимизац", "управленческ"],
    # 36. E-commerce
    "интернет-магазин": ["интернет-магазин", "ecommerce", "онлайн-магазин", "маркетплейс", "корзин", "каталог товар"],
    # 37. Design / Interior
    "дизайн интерьера": ["дизайн интерьер", "ремонт квартир", "отделк", "перепланировк", "интерьерн", "декорирован"],
    # 38. Pet services
    "зоотовары": ["зоомагазин", "груминг", "зоотовар", "корм для животн", "питомник", "дрессировк"],
    # 39. Children
    "детские товары": ["детск", "игрушк", "развивающ", "новорожден", "коляск", "детсад", "развлечен"],
    # 40. Agriculture equipment
    "спецтехника": ["спецтехник", "трактор", "экскаватор", "погрузчик", "бульдозер", "комбайн", "навесн"],
    # 41. Chemical
    "химическая промышленность": ["химич", "реагент", "полимер", "пластик", "растворител", "химпром", "лакокрасочн"],
    # 42. Energy
    "энергетика": ["энергетик", "электростанц", "генератор", "солнечн", "трансформатор", "энергосбережен"],
    # 43. Mining
    "горнодобыча": ["горнодобыва", "добыч", "руда", "карьер", "обогатител", "геологи", "бурен"],
    # 44. Packaging
    "упаковка": ["упаковк", "тар", "картон", "полиэтилен", "гофр", "пакет", "стрейч"],
    # 45. Warehousing
    "складское хозяйство": ["склад", "хранен", "стеллаж", "складск", "палет", "инвентаризац", "грузооборот"],
    # 46. Restaurant / Catering
    "ресторан": ["ресторан", "кафе", "общепит", "повар", "кулинар", "меню", "бар", "столов"],
    # 47. Hotel / Hospitality
    "гостиничный бизнес": ["гостиниц", "отел", "хостел", "номер", "размещен", "бронирован", "рецепц"],
    # 48. Telecom
    "телекоммуникации": ["телеком", "связ", "провайдер", "интернет", "сот", "оператор", "кабельн"],
    # 49. Jewelry
    "ювелирное дело": ["ювелир", "золот", "серебр", "украшен", "бриллиант", "драгоценн", "кольц"],
    # 50. Construction materials wholesale
    "стройматериалы": ["стройматериал", "сухие смеси", "гипсокартон", "утеплител", "арматур", "плитк", "сайдинг"],
    # 51. Cargo/Shipping
    "грузоперевозки": ["грузоперевозк", "фрахт", "транспортн", "автопарк", "рефрижератор", "негабарит"],
    # 52. Water treatment
    "водоподготовка": ["водоподготовк", "фильтр", "очистк вод", "водоочист", "скважин", "насос"],
    # 53. Waste management
    "утилизация отходов": ["утилизац", "отход", "мусор", "вторсырье", "переработк", "рециклинг", "экологич"],
}


# Маркеры того, что кандидат — ПРОДАВЕЦ/конкурент, а не покупатель.
# Локальная копия очевидных слов из lead_collection._COMPETITOR_SIGNALS —
# импортировать lead_collection здесь нельзя (тяжёлый модуль: pymorphy3 и
# весь сборочный пайплайн). «тд » — с пробелом, чтобы не матчить случайные
# буквосочетания внутри слов.
_SELLER_MARKERS = [
    "опт", "оптом", "торговый дом", "тд ", "склад", "магазин",
    "продажа", "поставщик", "интернет-магазин", "маркет",
]

# Если сами сегменты — продавцовые категории (заказчик целенаправленно ищет
# магазины/дилеров/оптовиков), штраф за продавцовую сигнатуру не применяем:
# продавец и есть целевой лид. Концептуально зеркалит выбор негативов в
# lead_collection._pick_negatives.
_SELLER_SEGMENT_HINTS = (
    "магазин", "дилер", "дистрибьютор", "оптов", "поставщик", "маркетплейс",
)


def _clamp(value: int, min_value: int = 0, max_value: int = 100) -> int:
    return max(min_value, min(max_value, value))


def _get_niche_keywords(niche: str) -> list[str]:
    """Получить ключевые слова для ниши (прямые + нечёткое совпадение по словарю)."""
    niche_lower = niche.strip().lower()
    # Ключевые слова из названия самой ниши (слова длиннее 3 символов)
    base_keywords = [part.strip().lower() for part in niche_lower.split() if len(part.strip()) > 3]
    # Дополнительные ключевые слова из словаря.
    # BUG FIX 1: Use stem/prefix matching instead of exact equality so inflected
    # Russian niche names ('строительные работы', 'мебельное производство',
    # 'логистические услуги') still resolve their keyword set.  Two tokens are
    # considered a stem-match when they share a common prefix of ≥5 characters
    # (long enough to identify a Russian root, short enough to cover inflections).
    # This covers cases like 'мебель'↔'мебельн', 'строительств'↔'строительн',
    # 'логистик'↔'логистическ'.
    #
    # BUG FIX 2: Require whole-word / token-level match for short dict keys (≤2 chars,
    # e.g. 'it') instead of substring-in-string, which caused 'digital', 'visit',
    # 'security' to wrongly match and receive IT keyword_bonus.
    _STEM_PREFIX_LEN = 5  # min shared-prefix length for a stem match

    def _tokens_stem_match(a: str, b: str) -> bool:
        """True when a and b share a common prefix of at least _STEM_PREFIX_LEN chars."""
        min_len = min(len(a), len(b))
        return min_len >= _STEM_PREFIX_LEN and a[:_STEM_PREFIX_LEN] == b[:_STEM_PREFIX_LEN]

    niche_tokens = niche_lower.split()
    dict_keywords: list[str] = []
    for dict_niche, keywords in NICHE_KEYWORDS.items():
        matched = False
        for dict_word in dict_niche.split():
            if len(dict_word) <= 2:
                # Short keys (e.g. 'it'): require exact token match, not substring.
                if dict_word in niche_tokens:
                    matched = True
                    break
            else:
                # Longer keys: exact substring match OR stem/prefix match to handle
                # Russian inflections.
                for tok in niche_tokens:
                    if dict_word in tok or tok in dict_word or _tokens_stem_match(dict_word, tok):
                        matched = True
                        break
            if matched:
                break
        if matched:
            dict_keywords.extend(keywords)
    return list(set(base_keywords + dict_keywords))


def score_lead(
    *,
    domain: str,
    company: str,
    niche: str,
    has_email: bool,
    has_phone: bool,
    has_address: bool,
    demo: bool,
    relevance_score: int = 0,
    segments: list[str] | None = None,
    description: str = "",
    hiring: bool = False,
    legal_status: str = "",
) -> int:
    """Скоринг лида 0–100 (≥80 — «горячий», 60–79 — amber).

    Правила (аудит P0/P1):
      * «Контакт» = email | телефон | домен. Адрес контактом не считается
        (только свои +8): address-only карточки 2GIS не должны выходить
        в amber/mint на одних контактных баллах.
      * Лид без единого матч-сигнала (keyword / segment / relevance) капится
        на 70 — полный набор контактов сам по себе не делает лид «горячим».
      * В режиме охоты на покупателей (segments переданы) продавцовая
        сигнатура в имени/домене («ТД … Оптом», «магазин …») — конкурент
        заказчика: нишевой бонус пропускается, применяется −15. Исключение —
        сами сегменты являются продавцовыми категориями.
      * description — сниппет/notes/описание кандидата (warehouse-строки
        несут в нём свою релевантность); участвует в keyword/segment матче.
    """
    settings = get_settings()
    niche_key = niche.strip().lower()
    global_weights = settings.scoring_weights
    niche_weights = settings.scoring_niche_weights.get(niche_key, {})

    # Keys that must always remain negative (penalties).
    # BUG FIX 4: If a niche-weight override supplies a positive value for a penalty
    # key (e.g. "demo_penalty": 20 instead of -20), the sign would be inverted and
    # the penalty would become a bonus.  Force the value negative so overrides never
    # silently flip a penalty into a reward.
    _PENALTY_KEYS = frozenset(
        {"demo_penalty", "aggregator_penalty", "no_contacts_penalty", "seller_penalty"}
    )

    def w(key: str, default: int) -> int:
        raw: int
        if key in niche_weights:
            raw = int(niche_weights[key])
        elif key in global_weights:
            raw = int(global_weights[key])
        else:
            return default
        # Preserve sign for penalty keys: the stored value must be negative.
        if key in _PENALTY_KEYS:
            return -abs(raw)
        return raw

    score = w("base", 35)

    if domain:
        score += w("domain", 10)
    if has_email:
        score += w("email", 20)
    if has_phone:
        score += w("phone", 10)
    if has_address:
        score += w("address", 8)

    # АУДИТ FIX 3 (P1): адрес — НЕ контакт. Раньше address-only строки 2GIS
    # избегали штрафа и добирались до amber/mint без способа связаться.
    has_any_contact = has_email or has_phone or bool(domain)
    if not has_any_contact:
        score += w("no_contacts_penalty", -12)
    if demo:
        score += w("demo_penalty", -20)
    if domain and is_aggregator_domain(domain):
        score += w("aggregator_penalty", -25)

    # Матч-компонента: сумма баллов за relevance / keyword / segment.
    # Если она нулевая — лид ничем не подтвердил принадлежность к целевой
    # аудитории, и контактные баллы капятся (см. конец функции).
    match_pts = 0

    # Вклад relevance_score из поискового ранжирования (0–15 баллов)
    if relevance_score:
        rel_pts = min(15, max(0, (relevance_score - 26) * 15 // 94))
        score += rel_pts
        match_pts += rel_pts

    lowered_domain = domain.lower()
    lowered_company = company.lower()
    lowered_description = (description or "").lower()

    # АУДИТ FIX 2 (P0): при охоте на покупателей (segments переданы) продавцовая
    # сигнатура в имени/домене («ТД … Оптом») означает, что нишевые слова в
    # названии — слова ПРОДУКТА, который кандидат сам продаёт. Это конкурент
    # заказчика, а не лид: нишевой бонус пропускаем и штрафуем на 15.
    seller_name_hit = any(
        marker in lowered_company or marker in lowered_domain
        for marker in _SELLER_MARKERS
    )
    seller_segments = False
    if segments:
        seg_blob = " ".join(segments).lower()
        seller_segments = any(hint in seg_blob for hint in _SELLER_SEGMENT_HINTS)
    seller_penalty_applies = bool(segments) and seller_name_hit and not seller_segments
    if seller_penalty_applies:
        score += w("seller_penalty", -15)

    # Бонус за ключевые слова ниши в домене, компании или описании/сниппете
    # (warehouse-строки несут свою релевантность в description)
    keywords = _get_niche_keywords(niche)
    if (
        not seller_penalty_applies
        and keywords
        and any(
            word in lowered_domain or word in lowered_company or word in lowered_description
            for word in keywords
        )
    ):
        kb = w("keyword_bonus", 12)
        score += kb
        match_pts += kb

    # Бонус за совпадение с целевым сегментом покупателя.
    # Когда prompt-enhancer вытащил segments (типы клиентов — «фермы», «птицефабрики»
    # для продавца кормовых добавок) — матч по этим словам в имени/домене даёт
    # +8, вплоть до +16. Это закрывает разрыв: раньше NICHE_KEYWORDS был только
    # product-side, и настоящий покупатель без «нишевых» слов в названии
    # недобирал очки.
    if segments:
        seg_terms: set[str] = set()
        for seg in segments:
            for part in seg.lower().split():
                if len(part) >= 4:
                    seg_terms.add(part)
        if seg_terms:
            seg_hits = sum(
                1 for term in seg_terms
                if term in lowered_domain
                or term in lowered_company
                or term in lowered_description
            )
            if seg_hits:
                # BUG FIX 3: w() returned a flat override value, so a 1-term match
                # and a 5-term match got the same bonus.  Treat segment_bonus as a
                # per-hit weight and multiply by seg_hits (capped at 16), consistent
                # with the default formula.
                per_hit = w("segment_bonus", 8)
                seg_pts = min(16, seg_hits * per_hit)
                score += seg_pts
                match_pts += seg_pts

    # Бонус за качество домена: .ru/.рф для российских ниш — признак местного бизнеса
    ru_niches = {"деревообработка", "строительство", "медицина", "юридические услуги", "бухгалтерия"}
    if niche_key in ru_niches and (domain.endswith(".ru") or domain.endswith(".рф")):
        score += w("ru_domain_bonus", 3)

    # Сигнал «компания нанимает» (hh.ru open_vacancies > 0): растущая компания
    # тратит деньги — небольшой бонус. НЕ входит в match_pts: найм не
    # подтверждает принадлежность к целевой нише, кап-70 остаётся в силе.
    if hiring:
        score += w("hiring_bonus", 5)

    # АУДИТ FIX 1 (P0): без единого матч-сигнала (keyword/segment/relevance)
    # лид не может быть «горячим». Раньше base(35)+domain(10)+email(20)+
    # phone(10)+address(8)=83 ≥ 80 при НУЛЕВОЙ релевантности нише.
    if match_pts == 0:
        score = min(score, 70)

    # ЕГРЮЛ-статус (DaData): мёртвому юрлицу продать нельзя — жёсткий кап
    # поверх всего остального. LIQUIDATING — юрлицо ещё живо, но сделка
    # рискованна: кап на уровне «холодного» лида.
    if legal_status in ("LIQUIDATED", "BANKRUPT"):
        score = min(score, 20)
    elif legal_status == "LIQUIDATING":
        score = min(score, 45)

    return _clamp(score)

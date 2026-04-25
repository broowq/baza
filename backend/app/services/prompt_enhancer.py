"""AI-powered prompt enhancement for B2B lead search.

Takes a raw user description of their business and product/service,
and generates an optimized search strategy to find POTENTIAL CUSTOMERS,
not competitors.
"""
import json
import logging
import re

import pymorphy3

from app.services import llm_client

logger = logging.getLogger(__name__)

# Module-level morph analyzer (thread-safe, caches parses internally).
_morph = pymorphy3.MorphAnalyzer()


def _lemmatize_phrase(phrase: str) -> str:
    """Convert each word of a Russian phrase to its nominative singular form.

    Example: "офисных центров" -> "офисный центр" so substring matching in the
    downstream lead filter works across grammatical cases the LLM may emit.
    Non-Russian and short tokens are passed through unchanged.
    """
    if not phrase:
        return phrase
    words = re.split(r'(\s+|-)', phrase.lower().replace("ё", "е"))
    out: list[str] = []
    for w in words:
        if re.match(r'^[а-я]{3,}$', w):
            try:
                out.append(_morph.parse(w)[0].normal_form)
            except Exception:
                out.append(w)
        else:
            out.append(w)
    return "".join(out)


def _normalize_segments(segments: list[str]) -> list[str]:
    """Lemmatize and dedupe a list of segment phrases returned by an LLM."""
    seen: set[str] = set()
    out: list[str] = []
    for seg in segments or []:
        if not isinstance(seg, str):
            continue
        norm = _lemmatize_phrase(seg.strip())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


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
    # Wood / Timber / Lumber — raw timber materials (not furniture).
    # Segments are the 2GIS CATEGORIES that these buyers sit in; we verified
    # against live 2gis.ru pages in April 2026.
    {
        "keywords": ["древесин", "пиломатериал", "брус", "доска", "фанер", "деревообработк",
                      "вагонк", "паркет", "лесоматериал", "дерев",
                      "лес ", "леса", "лесу", "переработка леса", "кругляк",
                      "опилк", "щепа", "сруб", "каркасн", "погонаж", "оцилиндровк"],
        "niche": "строительство, мебель, дачное домостроение",
        "segments": [
            # Verified 2GIS category names (return 50+ unique firms per city)
            "строительство дач и коттеджей",
            "строительство деревянных домов",
            "каркасные дома",
            "дома из бруса",
            "дома из бревна",
            "баня под ключ",
            "рубка домов",
            # Adjacent buyer categories
            "мебельная фабрика", "столярная мастерская",
            "строительная компания", "подрядчик",
            "оптовая база стройматериалов", "производство срубов",
            "дачное строительство", "застройщик",
            "деревянное домостроение",
        ],
        "target_types": ["Стройка дач/коттеджей", "Деревянные дома", "Мебельные фабрики",
                         "Столярные мастерские", "Подрядчики", "Бани"],
        "search_niche": "строительство дач и коттеджей деревянных домов баня под ключ сруб",
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
    # ── Extended B2B mappings (added via audit) ──
    # Medical / Pharma distribution
    {
        "keywords": ["лекарств", "фармацевтич", "медикамент", "препарат", "таблетк",
                      "капсул", "инфузион", "шприц", "аптечн", "фарма", "вакцин"],
        "niche": "здравоохранение, аптечные сети, медицинские учреждения",
        "segments": ["больница", "клиника", "аптека", "аптечная сеть", "медицинский центр",
                     "диагностический центр", "стоматология", "поликлиника"],
        "target_types": ["Больницы", "Клиники", "Аптеки", "Медицинские центры", "Стоматологии"],
        "search_niche": "больница клиника аптека медицинский центр диагностический центр",
    },
    # Automotive supply — parts for garages and dealers
    {
        "keywords": ["автозапчаст", "автомобильн запчаст", "запчаст для авто", "автомобильн",
                      "подвеск", "трансмисс", "тормоз", "масло моторн", "автомасл",
                      "автохим", "шиномонт", "авто запчаст"],
        "niche": "автосервисы, автодилеры, таксопарки",
        "segments": ["автосервис", "автодилер", "автомастерская", "таксопарк", "автомойка",
                     "шиномонтаж", "сто", "логистическая компания"],
        "target_types": ["Автосервисы", "Автодилеры", "Таксопарки", "Автомастерские", "Шиномонтажи"],
        "search_niche": "автосервис автодилер автомастерская таксопарк шиномонтаж",
    },
    # Printing / Polygraphy
    {
        "keywords": ["полиграф", "типограф", "баннер", "листовк", "бланк", "визитк",
                      "буклет", "брошюр", "плакат", "этикетк", "печатн"],
        "niche": "малый и средний бизнес, маркетинг, розница",
        "segments": ["магазин", "ресторан", "салон красоты", "стоматология",
                     "маркетинговое агентство", "event-агентство", "риелтор"],
        "target_types": ["Магазины", "Рестораны", "Салоны красоты", "Маркетинг-агентства", "Event-агентства"],
        "search_niche": "магазин ресторан салон красоты маркетинговое агентство",
    },
    # Agricultural equipment / supplies (not vet feed)
    {
        "keywords": ["трактор", "комбайн", "сельхозтехник", "агротехник", "плуг",
                      "культиватор", "сеялк", "опрыскиватель", "косилк", "сельхозмашин"],
        "niche": "растениеводство, животноводство, агропредприятия",
        "segments": ["фермерское хозяйство", "агрохолдинг", "кфх", "животноводческая ферма",
                     "птицефабрика", "тепличный комплекс", "элеватор"],
        "target_types": ["Фермерские хозяйства", "Агрохолдинги", "КФХ", "Тепличные комплексы", "Элеваторы"],
        "search_niche": "фермерское хозяйство агрохолдинг кфх птицефабрика тепличный комплекс",
    },
    # Industrial chemicals / reagents (not cleaning)
    {
        "keywords": ["химреагент", "антифриз", "растворитель", "промышленн масл",
                      "щелоч", "кислот", "коагулянт", "дезинфектант", "индустриальн масл"],
        "niche": "производство, водоочистка, прачечные, автопарки",
        "segments": ["завод", "фабрика", "прачечная", "водоканал", "автопарк",
                     "химический завод", "молокозавод", "пищевое производство"],
        "target_types": ["Заводы", "Прачечные", "Водоканалы", "Автопарки", "Химические предприятия"],
        "search_niche": "завод фабрика прачечная водоканал автопарк химический завод",
    },
    # Workwear / PPE (safety gear specifically)
    {
        "keywords": ["защитн очк", "каска", "респиратор", "защитн перчатк", "сапог",
                      "спецобувь", "сигнальн жилет", "средств защит", "сиз", "спецэкипир"],
        "niche": "производство, строительство, логистика, медицина",
        "segments": ["завод", "строительная компания", "склад", "больница",
                     "логистический центр", "горнодобывающая компания", "нефтегазовая компания"],
        "target_types": ["Заводы", "Строительные компании", "Склады", "Больницы", "Логистические центры"],
        "search_niche": "завод строительная компания склад больница логистический центр",
    },
    # Industrial packaging / containers (non-food)
    {
        "keywords": ["контейнер", "поддон", "паллет", "ящик пластик", "бочк", "канистр",
                      "промышленн тар", "биг-бег", "big-bag"],
        "niche": "производство, логистика, химическая промышленность",
        "segments": ["завод", "склад", "логистический центр", "химический завод",
                     "распределительный центр", "фабрика", "производственная компания"],
        "target_types": ["Заводы", "Склады", "Логистические центры", "Распределительные центры"],
        "search_niche": "завод склад логистический центр химический завод производственная компания",
    },
    # IT hardware / network equipment (distinct from software)
    {
        "keywords": ["сервер", "сетевое оборудован", "сетевого оборудован", "сетев оборудован",
                      "маршрутизатор", "коммутатор", "серверн стойк", "схд",
                      "система хранения", "цод", "datacenter", "поставк сервер"],
        "niche": "датацентры, интернет-провайдеры, телеком, крупный бизнес",
        "segments": ["датацентр", "интернет-провайдер", "телекоммуникационная компания",
                     "крупное предприятие", "банк", "хостинг-провайдер"],
        "target_types": ["Датацентры", "Интернет-провайдеры", "Телеком-компании", "Банки", "Корпорации"],
        "search_niche": "датацентр интернет-провайдер телекоммуникационная компания банк",
    },
    # ── Wholesale food distribution (B2B to stores/HoReCa) ──
    # Meat, frozen, dairy — sold TO retail + HoReCa, not to consumers
    {
        "keywords": ["мясопереработ", "мясн продукц", "мясом", "мясной", "колбас",
                      "торговля мяс", "оптовая мяс", "опт мяс",
                      "заморожен продукт", "полуфабрикат",
                      "молочн", "молокозавод", "кисломолочн", "молочка"],
        "niche": "розница, HoReCa, общепит",
        "segments": ["продуктовый магазин", "супермаркет", "ресторан", "кафе", "столовая",
                     "пиццерия", "отель", "пекарня", "кондитерская", "школьная столовая"],
        "target_types": ["Магазины продуктов", "Супермаркеты", "Рестораны", "Столовые", "Отели"],
        "search_niche": "продуктовый магазин супермаркет ресторан столовая отель",
    },
    # ── Metal products (прокат, арматура, сталь) ──
    {
        "keywords": ["металлопрокат", "арматур", "сталь ", "стали ", "сталь оптом",
                      "черн металл", "цветн металл", "труб металлич", "лист металлич",
                      "метизы", "крепеж"],
        "niche": "строительство, промышленность, машиностроение",
        "segments": ["строительная компания", "застройщик", "подрядчик", "завод",
                     "фабрика", "металлобаза", "производственная компания"],
        "target_types": ["Стройкомпании", "Застройщики", "Заводы", "Фабрики", "Металлобазы"],
        "search_niche": "строительная компания застройщик подрядчик завод фабрика",
    },
    # ── Legal / HR / Consulting B2B services ──
    {
        "keywords": ["юридическ", "юрист", "правов", "арбитражн", "регистрац ооо",
                      "подбор персонал", "кадров агентств", "hr-агентств", "рекрут",
                      "консалтинг", "управленч", "обучен сотрудник", "стратеги бизнес",
                      "сопровожден бизнес", "аутсорсинг"],
        "niche": "малый и средний бизнес, стартапы, ИП",
        "segments": ["интернет-магазин", "производственная компания", "строительная компания",
                     "ресторан", "салон красоты", "стоматология", "автосервис", "it-компания",
                     "оптовая база", "торговая компания"],
        "target_types": ["Магазины", "Производства", "Строительные компании", "Рестораны", "Клиники"],
        "search_niche": "производственная компания строительная компания магазин ресторан автосервис",
    },
    # ── Office supplies / Stationery ──
    {
        "keywords": ["канцтовар", "канцеляр", "офисн принадлежн", "офисн мебел",
                      "расходн материал для офис", "бумаг офисн", "картридж"],
        "niche": "офисы, организации, госучреждения",
        "segments": ["бизнес-центр", "офисный центр", "it-компания", "банк",
                     "страховая компания", "юридическая фирма", "школа", "больница", "мфц"],
        "target_types": ["Бизнес-центры", "IT-компании", "Банки", "Школы", "Больницы"],
        "search_niche": "бизнес-центр it-компания банк школа больница",
    },
    # ── Pet supplies wholesale ──
    {
        "keywords": ["зоотовар", "зоомагазин", "корм для животн", "товар для домашн живот",
                      "наполнитель для лот", "ошейник"],
        "niche": "зоомагазины, ветеринарные клиники, зоогостиницы",
        "segments": ["зоомагазин", "ветеринарная клиника", "ветклиника",
                     "зоогостиница", "груминг-салон", "питомник"],
        "target_types": ["Зоомагазины", "Ветклиники", "Зоогостиницы", "Груминг-салоны", "Питомники"],
        "search_niche": "зоомагазин ветеринарная клиника зоогостиница груминг-салон питомник",
    },
    # ── Household chemicals wholesale ──
    {
        "keywords": ["бытов химия", "бытовую химию", "бытхимия", "моющ",
                      "чистящ", "стиральн порошок", "средств для уборк",
                      "парфюмер оптом", "косметик оптом"],
        "niche": "магазины, клининг, HoReCa",
        "segments": ["продуктовый магазин", "супермаркет", "хозяйственный магазин",
                     "магазин косметики", "клининговая компания", "отель", "прачечная", "салон красоты"],
        "target_types": ["Магазины", "Супермаркеты", "Клининг", "Отели", "Салоны красоты"],
        "search_niche": "магазин супермаркет клининговая компания отель салон красоты",
    },
    # ── Construction: stretch ceilings, windows, interior ──
    {
        "keywords": ["натяжн потолк", "натяжные потолк", "потолк", "оконн профил",
                      "стеклопакет", "пластиков окн", "оконные профил",
                      "металлопластиков", "межкомнатн двер", "фасадн систем",
                      "алюминиев констр"],
        "niche": "строительство, ремонт, отделка",
        "segments": ["строительная компания", "застройщик", "подрядчик", "ремонтная бригада",
                     "дизайнер интерьера", "агентство недвижимости", "управляющая компания",
                     "бизнес-центр", "отель", "фитнес-клуб"],
        "target_types": ["Стройкомпании", "Застройщики", "Подрядчики", "Дизайнеры", "УК"],
        "search_niche": "строительная компания застройщик подрядчик дизайнер интерьера",
    },
    # ── Security systems (видеонаблюдение, СКУД, сигнализация) ──
    # Merged with existing "Security" mapping but with more specific trigger words
    {
        "keywords": ["видеонаблюден", "видеокамер", "система безопасност", "пожарн сигнализац",
                      "охранн систем", "скуд", "контроль доступ"],
        "niche": "коммерческая недвижимость, ритейл, офисы",
        "segments": ["бизнес-центр", "торговый центр", "склад", "магазин", "банк",
                     "ювелирный магазин", "аптека", "школа", "завод"],
        "target_types": ["Бизнес-центры", "ТЦ", "Магазины", "Склады", "Банки", "Школы"],
        "search_niche": "бизнес-центр торговый центр магазин склад банк",
    },
    # ── Refrigeration / HVAC service ──
    {
        "keywords": ["холодильн оборудован", "ремонт холодильник", "обслужив холодильн",
                      "сплит-систем", "кондиционер", "вентиляц", "тепловой насос"],
        "niche": "общепит, ритейл, производство",
        "segments": ["ресторан", "кафе", "магазин продуктов", "супермаркет",
                     "отель", "столовая", "молокозавод", "пищевое производство", "аптека"],
        "target_types": ["Рестораны", "Магазины", "Супермаркеты", "Отели", "Аптеки"],
        "search_niche": "ресторан кафе магазин продуктов супермаркет отель",
    },
    # ── Workwear/uniforms (distinct from PPE — just sewing/tailoring for corp) ──
    {
        "keywords": ["пошив спецодежд", "пошив униформ", "корпоративн одежд",
                      "форменн одежд", "рабоч одежд"],
        "niche": "производство, HoReCa, ритейл, медицина",
        "segments": ["завод", "ресторан", "отель", "строительная компания",
                     "клининговая компания", "больница", "салон красоты", "магазин"],
        "target_types": ["Заводы", "Рестораны", "Отели", "Строительные компании", "Больницы"],
        "search_niche": "завод ресторан отель строительная компания больница",
    },
    # ── Furniture manufacturing (office-oriented expansion) ──
    {
        "keywords": ["мебель на заказ", "мебел на заказ", "офисн мебел",
                      "производство мебели", "мебельн производств",
                      "корпусн мебел", "мебель для офис", "мебель для бизнес"],
        "niche": "офисы, бизнес-центры, отели",
        "segments": ["бизнес-центр", "офисный центр", "коворкинг", "it-компания",
                     "отель", "ресторан", "банк", "школа", "государственное учреждение"],
        "target_types": ["Бизнес-центры", "Офисные центры", "Коворкинги", "Отели", "Банки"],
        "search_niche": "бизнес-центр офисный центр коворкинг it-компания банк",
    },
    # ── ЖБИ / RC products / precast concrete ──
    {
        "keywords": ["жби", "железобетон", "бетонн издел", "фбс", "плита перекрытия",
                      "сваи", "фундаментн блок", "кольца колод"],
        "niche": "строительство, инфраструктура, девелопмент",
        "segments": ["строительная компания", "застройщик", "подрядчик",
                     "дорожно-строительная компания", "дсу", "девелопер", "инфраструктурн"],
        "target_types": ["Стройкомпании", "Застройщики", "Подрядчики", "ДСУ", "Девелоперы"],
        "search_niche": "строительная компания застройщик подрядчик дорожно-строительная",
    },
    # ── Roofing materials ──
    {
        "keywords": ["кровельн", "кровля", "кровли", "кровл оптом", "металлочерепиц",
                      "профнастил", "мягк кровл", "битумн кровл", "фальцев кровл"],
        "niche": "строительство, кровельные работы",
        "segments": ["строительная компания", "застройщик", "подрядчик",
                     "кровельщик", "загородное домостроение", "деревянное домостроение",
                     "склад стройматериалов"],
        "target_types": ["Стройкомпании", "Кровельщики", "Домостроение", "Склады стройматериалов"],
        "search_niche": "строительная компания застройщик подрядчик домостроение",
    },
    # ── Lubricants / Industrial oils ──
    {
        "keywords": ["смазочн", "смазк", "масла оптом", "индустриальн масл",
                      "трансмиссионн масл", "гидравлическ масл",
                      "автомасл", "моторн масл"],
        "niche": "автосервисы, производство, логистика",
        "segments": ["автосервис", "сто", "автомастерская", "автопарк", "таксопарк",
                     "завод", "фабрика", "логистическая компания", "транспортная компания"],
        "target_types": ["Автосервисы", "СТО", "Автопарки", "Заводы", "Транспорт"],
        "search_niche": "автосервис сто автопарк таксопарк завод транспортная компания",
    },
    # ── Apparel wholesale (одежда оптом, текстиль) ──
    {
        "keywords": ["одежд оптом", "текстил оптом", "одежда b2b", "одежд для магазин",
                      "форменн одежд для детск", "школьн форм"],
        "niche": "розница, школы, HoReCa",
        "segments": ["магазин одежды", "детский магазин", "школа", "детский сад",
                     "отель", "ресторан", "клининговая компания", "больница"],
        "target_types": ["Магазины одежды", "Школы", "Детские сады", "Отели", "Клининг"],
        "search_niche": "магазин одежды школа детский сад отель клининговая компания",
    },
]


def enhance_prompt(raw_prompt: str) -> dict:
    """Take a user's raw business description and generate a search strategy."""
    if llm_client.is_configured():
        result = _try_llm_enhance(raw_prompt)
        if result:
            # Augment LLM segments with auto-discovered 2GIS categories
            result["segments"] = _augment_with_2gis_categories(
                result.get("segments") or [],
                result.get("geography", ""),
                raw_prompt,
            )
            # If LLM missed OKVED (older prompt variant, or model skipped the
            # field), derive from segments using the rule-based map.
            if not result.get("okved_codes"):
                result["okved_codes"] = _okved_from_segments(result.get("segments") or [])
            return result

    # Fallback to smart rule-based enhancement
    result = _smart_fallback(raw_prompt)
    seed_count = len(result.get("segments") or [])
    # Only augment via 2GIS if rule-based found something — otherwise the probes
    # search by user's own product words and return mostly noise (sellers).
    # For totally unknown niches, better to return [] and let user add segments
    # manually than to populate them with unrelated categories.
    if seed_count >= 3:
        result["segments"] = _augment_with_2gis_categories(
            result["segments"], result.get("geography", ""), raw_prompt,
        )
    result["okved_codes"] = _okved_from_segments(result.get("segments") or [])
    return result


def _augment_with_2gis_categories(
    seed_segments: list[str],
    geography: str,
    raw_prompt: str,
) -> list[str]:
    """Extract additional customer categories from 2GIS search pages.

    Strategy:
      1. Try seed_segments one by one on 2gis.ru/{slug}/search/{segment}.
         Each page lists sibling categories the platform thinks are related.
      2. Collect unique sibling category names.
      3. Filter out sellers (categories that contain user's product keywords
         — they sell the same thing as the user).
      4. Merge with seed_segments, cap at 20.

    Falls back gracefully: if 2gis is unreachable, just returns seed_segments.
    """
    try:
        from app.services.lead_collection import _city_to_slug
    except Exception:
        return seed_segments

    if not geography:
        return seed_segments
    slug = _city_to_slug(geography)
    if not slug:
        return seed_segments

    # Build competitor filter: words that appear in user's prompt describing
    # what THEY sell. Other businesses in categories with these words are
    # competitors, not customers.
    product_words = _extract_prompt_product_words(raw_prompt)

    # Seeds to probe: first 3 seed segments + top product keywords as fallback
    probes: list[str] = []
    for s in (seed_segments or [])[:3]:
        probes.append(s)
    if len(probes) < 3 and product_words:
        # For unknown industries, use most specific product word as probe
        probes.append(product_words[0] if product_words else raw_prompt[:60])
    probes = [p for p in probes if p and len(p) >= 3][:4]

    discovered: list[str] = []
    seen_lower: set[str] = {s.lower() for s in seed_segments}
    try:
        import httpx
        import concurrent.futures
        from urllib.parse import quote_plus, unquote
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
             "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        headers = {
            "User-Agent": ua,
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }

        def _fetch_one(probe: str) -> str:
            url = f"https://2gis.ru/{slug}/search/{quote_plus(probe)}"
            try:
                with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                    r = client.get(url, headers=headers)
                if r.status_code == 200 and len(r.text) >= 5000:
                    return r.text
            except Exception:
                pass
            return ""

        # Parallelise probes — previously serial, took 4× longer.
        probe_htmls: list[str] = []
        if probes:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(probes))) as ex:
                probe_htmls = list(ex.map(_fetch_one, probes))

        _GENERIC_CATEGORY_BLOCKLIST = {
            "компания", "офис продаж", "торговая фирма", "фирма",
            "офис", "торговый дом", "торговая компания",
            "производственная компания", "сервисная компания",
            "экспертная компания", "консалтинговая компания",
            "посредническая компания", "представительство",
            "снеки", "продукция", "товары",
            "оптово-розничная компания", "торгово-сервисная компания",
            "торгово-производственная компания", "торгово-производственная фирма",
            "производственно-коммерческая фирма",
        }
        done = False
        for html in probe_htmls:
            if done or not html:
                continue
            cats = re.findall(
                r'href="/[a-z]+/search/([^"]+)"[^>]*class="_1jvng3r"',
                html,
            )
            for c in cats:
                name = unquote(c).replace("+", " ").strip().lower()
                if not name or len(name) > 80 or name in seen_lower:
                    continue
                # Filter competitors (contain user's product words)
                if any(pw in name for pw in product_words):
                    continue
                if name in _GENERIC_CATEGORY_BLOCKLIST:
                    continue
                discovered.append(name)
                seen_lower.add(name)
                if len(discovered) >= 15:
                    done = True
                    break
    except Exception as exc:
        logger.info("2GIS category discovery failed: %s", exc)

    # Merge: seed first (priority), then discovered. Cap at 20.
    merged: list[str] = []
    for s in seed_segments:
        if s.lower() not in {m.lower() for m in merged}:
            merged.append(s)
    for d in discovered:
        if d.lower() not in {m.lower() for m in merged}:
            merged.append(d)
        if len(merged) >= 20:
            break

    if discovered:
        logger.info(
            "2GIS category discovery: %d seed + %d auto-discovered = %d total segments",
            len(seed_segments), len(discovered), len(merged),
        )
    return merged


def _strip_product_echoes(segments: list[str], product_words: list[str]) -> list[str]:
    """Drop segments whose words substantially overlap the user's own products.

    A segment "echoes the product" if at least one of its >=4-char word stems
    appears in product_words. We keep segments that describe distinct customer
    types even if they share a word (e.g. prompt "мебельный магазин" →
    segment "ресторан": no echo, keep).
    """
    if not product_words:
        return segments
    product_set = {pw for pw in product_words if len(pw) >= 4}
    kept: list[str] = []
    for seg in segments:
        seg_lower = seg.lower()
        # If ANY word in segment is a product-word, consider it an echo
        seg_words = re.findall(r"[а-яa-z]{4,}", seg_lower)
        if not seg_words:
            kept.append(seg)
            continue
        # An echo is: every (or most) segment words match a product word.
        # Segments with mostly non-product words are real customer types.
        echo_hits = sum(
            1 for sw in seg_words
            if any(sw.startswith(pw) or pw.startswith(sw) for pw in product_set)
        )
        if echo_hits >= len(seg_words):  # every word echoes → drop
            continue
        kept.append(seg)
    return kept


def _extract_prompt_product_words(prompt: str) -> list[str]:
    """Extract product/service lemmas from a business description.

    Used to filter out competitor categories from 2GIS discovery. Uses pymorphy3
    lemmatization so "пиломатериалы" / "пиломатериалов" / "пиломатериал" all
    reduce to the same stem — letting us match "магазин пиломатериалов" as a
    competitor even when the prompt says "пиломатериалы".
    """
    text = (prompt or "").lower().replace("ё", "е")
    # Strip action verbs and prepositions
    for w in ("продаю", "продаем", "продаём", "предлагаю", "оказываю", "оказываем",
              "производим", "производу", "поставляем", "поставляю", "делаем", "делаю",
              "занимаюсь", "занимаемся", "работаю", "работаем", "ищем",
              "мы ", "мой ", "моя ", "наш ", "наша ", "в ", "для ", "и ", "с ", "на ",
              "по ", "из ", "под ", "через "):
        text = text.replace(w, " ")
    for city in _CITY_STRIP:
        text = text.replace(city.lower(), " ")

    # Lemmatize with pymorphy3 — same analyzer used in lead_collection.
    try:
        from app.services.lead_collection import _morph
    except Exception:
        _morph = None

    words = re.findall(r"[а-яa-z]{4,}", text)
    result: list[str] = []
    seen: set[str] = set()
    for w in words:
        # Generate multiple matching forms for robust substring check
        candidates = {w, w[:5] if len(w) >= 6 else w, w[:6] if len(w) >= 7 else w}
        if _morph is not None:
            try:
                lemma = _morph.parse(w)[0].normal_form.replace("ё", "е")
                candidates.add(lemma)
                if len(lemma) >= 6:
                    candidates.add(lemma[:6])
                if len(lemma) >= 5:
                    candidates.add(lemma[:5])
            except Exception:
                pass
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                result.append(c)
    # Keep short distinct stems first; cap size
    result.sort(key=len)
    return result[:15]


# Pre-built set of Russian city names (lowercased) to strip from product-word
# extraction. Used by _extract_prompt_product_words.
_CITY_STRIP = (
    "москва", "спб", "санкт-петербурге", "санкт-петербург", "петербург",
    "новосибирск", "екатеринбург", "казань", "красноярск", "нижний новгород",
    "челябинск", "самара", "омск", "уфа", "пермь", "волгоград", "воронеж",
    "краснодар", "ростов", "саратов", "тюмень", "томск", "барнаул", "иркутск",
    "ярославль", "владивосток", "хабаровск", "кемерово", "тула", "пенза",
    "рязань", "калининград", "астрахань", "липецк", "курск", "брянск",
    "белгород", "тверь", "сургут", "архангельск", "владимир", "смоленск",
    "калуга", "чита", "орел", "вологда", "якутск",
)


# ──────────────────────────────────────────────────────────────────────────
# ОКВЭД normalization + rule-based fallback
# ──────────────────────────────────────────────────────────────────────────

_OKVED_CODE_RE = re.compile(r"^\d{2}(\.\d{1,2})?$")

# Segment keyword → OKVED code (fallback when LLM omits okved_codes).
# Order matters: longer / more specific keywords should appear first.
_SEGMENT_OKVED_MAP: list[tuple[tuple[str, ...], list[dict]]] = [
    # Animal farming
    (("птицефабрик", "птицевод"), [
        {"code": "01.47", "label": "Разведение сельскохозяйственной птицы", "confidence": 0.9},
    ]),
    (("свиноферм", "свиноком", "свиновод"), [
        {"code": "01.46", "label": "Разведение свиней", "confidence": 0.9},
    ]),
    (("молочн", "молокозавод", "молочная ферма", "крс", "молочно"), [
        {"code": "01.41", "label": "Разведение молочного крупного рогатого скота", "confidence": 0.85},
    ]),
    (("ферма", "ферм", "фермер", "кфх", "агрохолдинг", "животновод"), [
        {"code": "01.41", "label": "Разведение молочного КРС", "confidence": 0.7},
        {"code": "01.47", "label": "Разведение сельскохозяйственной птицы", "confidence": 0.7},
        {"code": "01.46", "label": "Разведение свиней", "confidence": 0.6},
    ]),
    (("зоомагазин", "зоотовар", "ветклиник", "ветеринар"), [
        {"code": "47.76", "label": "Розничная торговля цветами, зоотоварами", "confidence": 0.85},
        {"code": "75.00", "label": "Деятельность ветеринарная", "confidence": 0.8},
    ]),
    # Construction
    (("застройщик", "строительная компания", "девелопер"), [
        {"code": "41.20", "label": "Строительство жилых и нежилых зданий", "confidence": 0.9},
    ]),
    (("подрядчик", "ремонт квартир", "отделочн"), [
        {"code": "43.99", "label": "Прочие специализированные строительные работы", "confidence": 0.8},
    ]),
    # Hospitality / HoReCa
    (("ресторан", "кафе", "столов", "общепит"), [
        {"code": "56.10", "label": "Деятельность ресторанов и услуги по доставке еды", "confidence": 0.9},
    ]),
    (("отел", "гостиниц", "хостел"), [
        {"code": "55.10", "label": "Деятельность гостиниц", "confidence": 0.9},
    ]),
    (("бизнес-центр", "торговый центр", "тц", "бц"), [
        {"code": "68.20", "label": "Аренда и управление недвижимостью", "confidence": 0.85},
    ]),
    # Retail / E-comm
    (("интернет-магазин", "маркетплейс", "e-commerce", "ecommerce"), [
        {"code": "47.91", "label": "Розничная торговля через интернет", "confidence": 0.9},
    ]),
    (("магазин", "торговая точка"), [
        {"code": "47.19", "label": "Прочая розничная торговля в неспециализированных магазинах", "confidence": 0.7},
    ]),
    # IT / digital
    (("it-компания", "ит-компания", "разработчик по", "softwar"), [
        {"code": "62.01", "label": "Разработка компьютерного ПО", "confidence": 0.9},
    ]),
    (("дата-центр", "датацентр", "хостинг"), [
        {"code": "63.11", "label": "Деятельность по обработке данных", "confidence": 0.9},
    ]),
    # Manufacturing
    (("завод", "фабрика", "производственная компания", "пищевое производство"), [
        {"code": "10.00", "label": "Производство пищевых продуктов", "confidence": 0.7},
        {"code": "25.00", "label": "Производство металлических изделий", "confidence": 0.6},
    ]),
    # Healthcare
    (("клиник", "стоматолог", "медицинск", "больниц"), [
        {"code": "86.10", "label": "Деятельность больничных организаций", "confidence": 0.8},
        {"code": "86.22", "label": "Специальная врачебная практика", "confidence": 0.8},
    ]),
    (("аптек", "фармацевт"), [
        {"code": "47.73", "label": "Торговля лекарственными средствами в аптеках", "confidence": 0.9},
    ]),
    # Logistics
    (("грузоперевозк", "транспортн компания", "логистическ"), [
        {"code": "49.41", "label": "Деятельность автомобильного грузового транспорта", "confidence": 0.9},
    ]),
    # Auto
    (("автосервис", "сто", "автомастерск"), [
        {"code": "45.20", "label": "Техобслуживание и ремонт автомобилей", "confidence": 0.9},
    ]),
    (("автодилер", "автосалон"), [
        {"code": "45.11", "label": "Торговля легковыми автомобилями", "confidence": 0.9},
    ]),
    # Services
    (("салон красот", "парикмахер", "косметолог"), [
        {"code": "96.02", "label": "Парикмахерские и косметические услуги", "confidence": 0.9},
    ]),
    (("фитнес", "спортзал", "тренажерн"), [
        {"code": "93.13", "label": "Деятельность фитнес-центров", "confidence": 0.9},
    ]),
    # Finance / professional
    (("банк", "финансовая компания"), [
        {"code": "64.19", "label": "Денежное посредничество прочее", "confidence": 0.9},
    ]),
    (("страхов",), [
        {"code": "65.11", "label": "Страхование жизни", "confidence": 0.8},
        {"code": "65.12", "label": "Прочие виды страхования", "confidence": 0.8},
    ]),
    (("юрист", "адвокат", "юридическ"), [
        {"code": "69.10", "label": "Деятельность в области права", "confidence": 0.9},
    ]),
    (("бухгалтер", "аудит", "налогов консалтинг"), [
        {"code": "69.20", "label": "Деятельность по аудиту и бухучёту", "confidence": 0.9},
    ]),
]


def _normalize_okved(raw: list) -> list[dict]:
    """Validate LLM-returned OKVED entries: enforce schema + clamp confidence."""
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        if not _OKVED_CODE_RE.match(code):
            continue
        if code in seen:
            continue
        seen.add(code)
        label = str(entry.get("label") or "").strip()[:140]
        try:
            conf = float(entry.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        out.append({"code": code, "label": label, "confidence": round(conf, 2)})
    # Highest confidence first, then lexicographic — deterministic order for UI.
    out.sort(key=lambda x: (-x["confidence"], x["code"]))
    return out[:6]


def _okved_from_segments(segments: list[str]) -> list[dict]:
    """Rule-based fallback when LLM didn't emit okved_codes. Looks up each
    segment in _SEGMENT_OKVED_MAP, aggregates confidences."""
    if not segments:
        return []
    blob = " ".join(segments).lower().replace("ё", "е")
    buckets: dict[str, dict] = {}
    for keywords, codes in _SEGMENT_OKVED_MAP:
        if any(kw in blob for kw in keywords):
            for entry in codes:
                current = buckets.get(entry["code"])
                if current is None or entry["confidence"] > current["confidence"]:
                    buckets[entry["code"]] = dict(entry)
    out = list(buckets.values())
    out.sort(key=lambda x: (-x["confidence"], x["code"]))
    return out[:6]


def _try_llm_enhance(raw_prompt: str) -> dict | None:
    """Try to enhance using LLM. Returns None on failure."""
    system_prompt = """Ты — AI-ассистент B2B платформы лидогенерации БАЗА. Твоя задача — проанализировать описание бизнеса пользователя и создать стратегию поиска ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ.

КЛЮЧЕВОЙ ПРИНЦИП: Пользователь описывает СВОЙ бизнес — что он продаёт, поставляет
или производит. Тебе нужно определить, КТО будет ПОКУПАТЕЛЕМ.

⚠️ ЗАПРЕЩЕНО возвращать в segments:
1. Конкурентов того же продукта (продавец кормов → НЕ другие производители кормов)
2. Поставщиков сырья пользователя (заготовитель кедра → НЕ другие лесорубы/рубщики)
3. Профессии или ремесленников (токарь, сварщик, рубщик, столяр)
4. Виды деятельности самого пользователя (заготовка/добыча/производство/продажа)
5. Слова из самого промта пользователя (это его продукт, не клиент)

✅ ОБЯЗАТЕЛЬНО думать о конечной цепочке: «кому нужен мой продукт КАК ВХОД?»

Пример A — продавец товара:
- Пользователь: "Продаю кормовые добавки для животных в Томске"
- НЕПРАВИЛЬНО: компании, которые продают кормовые добавки (конкуренты!)
- ПРАВИЛЬНО: птицефабрика, бройлерная фабрика, инкубатор, свинокомплекс, свиноферма,
  животноводческая ферма, КФХ, фермерское хозяйство, агрохолдинг, агрокомбинат,
  молочный комплекс, молочная ферма, козья ферма, овцеферма, конеферма,
  зверохозяйство, кролиководческое хозяйство, форелевое хозяйство, рыбхоз,
  птицеводческий комплекс, племенной завод, мясокомбинат, мясоперерабатывающий
  завод, ветеринарная клиника, зоомагазин, племенной питомник, страусиная ферма…

Пример B — поставщик сырья (ОЧЕНЬ ВАЖНО):
- Пользователь: "Я являюсь заготовителем кедра в Томской области"
- НЕПРАВИЛЬНО: рубщики, лесопилки, заготовители, лесорубы (это коллеги-поставщики!)
- ПРАВИЛЬНО: производитель срубов, домостроитель из бруса, фабрика клееного бруса,
  мебельная фабрика (массив дерева), производитель паркета, производитель дверей
  межкомнатных, столярный цех, фабрика музыкальных инструментов, гитарная мастерская,
  производитель эфирных масел, кондитерская фабрика (кедровый орех), пекарня
  премиум-класса, производитель халвы и козинаков, производитель БАДов, аптечная
  сеть, производитель косметики (кедровое масло), сеть органических продуктов,
  ресторан премиум, кафе крафтового хлеба, фасовщик орехов, производитель шоколада…

Пример C — производитель компонента:
- Пользователь: "Производим металлопрокат в Екатеринбурге"
- НЕПРАВИЛЬНО: другие металлопрокатчики, металлозавод, ферросплавы (конкуренты!)
- ПРАВИЛЬНО: строительная компания, генподрядчик, производитель металлоконструкций,
  машиностроительный завод, судостроительный завод, производитель автомобилей,
  завод сельхозтехники, нефтепровод, газопровод, производитель труб, котельный
  завод, мостостроитель, производитель железнодорожных вагонов…

ЦЕЛЬ — выдать 25-40 КОНКРЕТНЫХ типов компаний, которые ЗАКУПАЮТ продукт пользователя.

Ответь СТРОГО в JSON формате (без markdown, без ```):
{
  "enhanced_prompt": "Улучшенная версия описания бизнеса пользователя (1-2 предложения)",
  "project_name": "Короткое название проекта (2-4 слова)",
  "niche": "Целевая ниша КЛИЕНТОВ (не продавца!), например: животноводство, птицеводство",
  "geography": "Извлечённый регион/город или 'Россия' если не указан",
  "segments": ["конкретный тип 1", "конкретный тип 2", "...", "конкретный тип 25"],
  "target_customer_types": ["тип клиента 1", "тип клиента 2", "..."],
  "search_queries_niche": "Ключевые слова для поиска КЛИЕНТОВ на картах (Яндекс/2ГИС)",
  "okved_codes": [
    {"code": "01.47", "label": "Разведение сельскохозяйственной птицы", "confidence": 0.9},
    {"code": "01.46", "label": "Разведение свиней", "confidence": 0.85}
  ],
  "explanation": "Краткое объяснение стратегии поиска (1-2 предложения)"
}

ОБЯЗАТЕЛЬНО для segments:
- ВЕРНИ ОТ 20 ДО 40 ОТДЕЛЬНЫХ ЗАПИСЕЙ. Меньше 20 — недостаточно.
- Каждая запись — КОНКРЕТНЫЙ тип бизнеса (например "птицефабрика", а не общее "сельское хозяйство").
- Включай синонимы и формальные/неформальные варианты (ферма / хозяйство / комплекс / комбинат / агрохолдинг).
- Включай узкие подвиды (молочная ферма, козья ферма, овцеферма — как РАЗНЫЕ записи).
- Включай юридические формы клиентов (КФХ, ИП-фермер, ООО-агрохолдинг, ФГУП, ОАО).
- Если бизнес поставляет в HoReCa — добавь конкретику: ресторан, кафе, столовая, бистро,
  кофейня, бар, паб, фастфуд, доставка еды, банкетный зал, столовая при заводе…
- Если бизнес для застройщиков — застройщик, генподрядчик, субподрядчик, СРО, проектное
  бюро, архитектурное бюро, девелопер, ПИК-аналог, региональный девелопер…

ОБЯЗАТЕЛЬНО для target_customer_types:
- 5-10 более ВЫСОКОУРОВНЕВЫХ категорий покупателей (для UI и описания целевой аудитории).

search_queries_niche — это то, что будет искаться на картах и в поисковиках (ниша клиента, не продавца).

ВАЖНО для okved_codes: верни ОКВЭД-коды ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ (не продавца!) — российский классификатор видов деятельности.
- code: строка "XX" (раздел), "XX.X" или "XX.XX" (подкласс).
- label: краткое русское название вида деятельности.
- confidence: от 0.0 до 1.0.
Верни от 2 до 6 кодов, отсортированных по убыванию confidence. Только коды покупателей!
Неправильно: если пользователь продаёт корма, НЕ возвращай 46.21 (оптовая торговля зерном) — это продавец.
Правильно: 01.47 (птицеводство), 01.46 (свиноводство) — это покупатели кормов."""

    try:
        answer = llm_client.chat(
            raw_prompt,
            system=system_prompt,
            max_tokens=2500,  # bumped from 800: we now ask for 25-40 segments
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

        # Normalize segments to nominative case so downstream substring match in
        # llm_filter is robust to genitive/accusative forms the LLM may return.
        if isinstance(result.get("segments"), list):
            result["segments"] = _normalize_segments(result["segments"])
            # Post-LLM guard: strip segments that echo the user's PRODUCT words.
            # LLMs occasionally return `"segments": ["кормовая добавка"]` when the
            # prompt is "Продаю кормовые добавки" — that makes us search for
            # SELLERS of feed additives (competitors). Filter them out.
            product_words = _extract_prompt_product_words(raw_prompt)
            if product_words:
                result["segments"] = _strip_product_echoes(
                    result["segments"], product_words
                )

        # Normalize ОКВЭД codes: validate shape, clamp confidence to [0,1].
        if isinstance(result.get("okved_codes"), list):
            result["okved_codes"] = _normalize_okved(result["okved_codes"])
        else:
            # LLM didn't include okved_codes — use rule-based fallback from segments.
            result["okved_codes"] = _okved_from_segments(result.get("segments") or [])

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

    # Lowered from 1.0 to 0.5 — allowed short-stem matches like "жби" (3 chars)
    # to trigger their specialized mapping instead of falling through to fallback.
    if best_match and best_score >= 0.5:
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

    # Normalize each word in the text to nominative form via pymorphy3,
    # then look for exact city name matches. Robust against all Russian
    # case endings including compound cities (Санкт-Петербурге, Ростове-на-Дону).
    city_set = {c.lower() for c in cities}
    city_by_lc = {c.lower(): c for c in cities}

    # Tokenize preserving hyphenated compounds
    tokens = re.findall(r"[а-яё]+(?:-[а-яё]+)*", text.lower())
    normalized_tokens: list[str] = []
    for tok in tokens:
        try:
            normalized_tokens.append(_morph.parse(tok)[0].normal_form)
        except Exception:
            normalized_tokens.append(tok)

    # Also keep the raw (non-normalized) tokens for compound cities where
    # pymorphy may not normalize "ростове-на-дону" as a whole unit.
    combined = " ".join(normalized_tokens) + " " + " ".join(tokens)

    # Try longest cities first so "Санкт-Петербург" wins over "Петербург"
    for city_lc in sorted(city_set, key=len, reverse=True):
        # Word-boundary match
        pattern = rf"(?<![а-яё]){re.escape(city_lc)}(?![а-яё])"
        if re.search(pattern, combined):
            return city_by_lc[city_lc]

    # Region-form fallback: "томской области" → "Томск", "пермском крае" → "Пермь",
    # "ленинградской области" → "Санкт-Петербург", etc. The user often writes
    # the region instead of the city; we extract the root as the city anyway —
    # the geo-tier cascade will widen to the region/country if needed.
    region_to_city = {
        "московск": "Москва",
        "ленинградск": "Санкт-Петербург",
        "новосибирск": "Новосибирск",  # area uses same root
        "свердловск": "Екатеринбург",
        "татарстан": "Казань",
        "нижегородск": "Нижний Новгород",
        "челябинск": "Челябинск",
        "красноярск": "Красноярск",
        "самарск": "Самара",
        "омск": "Омск",
        "башкортостан": "Уфа",
        "башкирск": "Уфа",
        "ростовск": "Ростов-на-Дону",
        "пермск": "Пермь",
        "волгоградск": "Волгоград",
        "воронежск": "Воронеж",
        "краснодарск": "Краснодар",
        "саратовск": "Саратов",
        "тюменск": "Тюмень",
        "удмуртск": "Ижевск",
        "удмурти": "Ижевск",
        "алтайск": "Барнаул",
        "ульяновск": "Ульяновск",
        "иркутск": "Иркутск",
        "хабаровск": "Хабаровск",
        "ярославск": "Ярославль",
        "приморск": "Владивосток",
        "дагестан": "Махачкала",
        "томск": "Томск",
        "оренбургск": "Оренбург",
        "кемеровск": "Кемерово",
        "кузбасс": "Кемерово",
        "рязанск": "Рязань",
        "астраханск": "Астрахань",
        "пензенск": "Пенза",
        "липецк": "Липецк",
        "тульск": "Тула",
        "кировск": "Киров",
        "чувашск": "Чебоксары",
        "чувашия": "Чебоксары",
        "калининградск": "Калининград",
        "брянск": "Брянск",
        "курск": "Курск",
        "ивановск": "Иваново",
        "тверск": "Тверь",
        "белгородск": "Белгород",
        "архангельск": "Архангельск",
        "владимирск": "Владимир",
        "ставропольск": "Ставрополь",
        "крым": "Симферополь",
        "карелия": "Петрозаводск",
        "коми": "Сыктывкар",
        "якутия": "Якутск",
        "саха": "Якутск",
        "забайкальск": "Чита",
        "забайкалье": "Чита",
        "вологодск": "Вологда",
        "костромск": "Кострома",
        "новгородск": "Великий Новгород",
        "псковск": "Псков",
        "сахалинск": "Южно-Сахалинск",
        "сахалин": "Южно-Сахалинск",
        "камчатск": "Петропавловск-Камчатский",
        "камчатка": "Петропавловск-Камчатский",
        "магаданск": "Магадан",
        "мурманск": "Мурманск",
        "тамбовск": "Тамбов",
        "хмао": "Сургут",
        "ямало": "Салехард",
        "янао": "Салехард",
    }
    text_lower = text.lower()
    for region_root, city in sorted(region_to_city.items(), key=lambda x: -len(x[0])):
        if region_root in text_lower:
            return city

    return "Россия"

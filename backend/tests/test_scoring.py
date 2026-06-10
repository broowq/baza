from app.services.scoring import score_lead


def test_score_increases_with_contacts():
    with_contacts = score_lead(
        domain="example.com",
        company="Example",
        niche="it automation",
        has_email=True,
        has_phone=True,
        has_address=True,
        demo=False,
    )
    without_contacts = score_lead(
        domain="example.com",
        company="Example",
        niche="it automation",
        has_email=False,
        has_phone=False,
        has_address=False,
        demo=False,
    )
    assert with_contacts > without_contacts


def test_aggregator_penalty():
    aggregator = score_lead(
        domain="2gis.ru",
        company="2GIS",
        niche="services",
        has_email=True,
        has_phone=True,
        has_address=False,
        demo=False,
    )
    real_company = score_lead(
        domain="my-company.ru",
        company="My Company",
        niche="services",
        has_email=True,
        has_phone=True,
        has_address=False,
        demo=False,
    )
    assert aggregator < real_company


# ---------------------------------------------------------------------------
# Audit fixes (P0/P1)
# ---------------------------------------------------------------------------


def test_full_contacts_zero_match_capped_at_70():
    """FIX 1: контактные баллы без единого матч-сигнала не дают «горячий» лид.

    Раньше: base(35)+domain(10)+email(20)+phone(10)+address(8)=83 ≥ 80 при
    нулевой релевантности нише.
    """
    score = score_lead(
        domain="random-company.ru",
        company="ООО Ромашка",
        niche="кормовые добавки для ферм",
        has_email=True,
        has_phone=True,
        has_address=True,
        demo=False,
    )
    assert score <= 70


def test_description_text_counts_as_match_evidence():
    """FIX 1: keyword-матч по description/сниппету снимает кап на 70."""
    common = dict(
        domain="random-company.ru",
        company="ООО Ромашка",
        niche="кормовые добавки для ферм",
        has_email=True,
        has_phone=True,
        has_address=True,
        demo=False,
    )
    no_desc = score_lead(**common)
    with_desc = score_lead(
        **common,
        description="Птицефабрика: закупаем кормовые добавки и комбикорма",
    )
    assert no_desc <= 70
    assert with_desc > no_desc


def test_seller_signature_scores_below_real_buyer():
    """FIX 2: «ТД … Оптом» с полными контактами должен быть НИЖЕ реального
    покупателя с одним телефоном при охоте на покупателей (segments заданы)."""
    segments = ["фермы", "животноводческие хозяйства"]
    seller = score_lead(
        domain="korm-dobavki-opt.ru",
        company="ТД Кормовые Добавки Оптом",
        niche="кормовые добавки для ферм",
        has_email=True,
        has_phone=True,
        has_address=True,
        demo=False,
        segments=segments,
    )
    buyer = score_lead(
        domain="",
        company="Фермы Юга — КФХ",
        niche="кормовые добавки для ферм",
        has_email=False,
        has_phone=True,
        has_address=True,
        demo=False,
        segments=segments,
    )
    assert seller < buyer
    assert seller < 80  # продавец не может быть «горячим»


def test_seller_segments_guard_no_penalty():
    """FIX 2 guard: если заказчик сам охотится на магазины/оптовиков
    (продавцовые сегменты), продавцовая сигнатура — целевой лид, без штрафа."""
    common = dict(
        domain="zoo-opt.ru",
        company="ТД Зоотовары Оптом",
        niche="зоотовары",
        has_email=True,
        has_phone=True,
        has_address=False,
        demo=False,
    )
    hunting_shops = score_lead(**common, segments=["зоомагазины", "оптовики"])
    hunting_farms = score_lead(**common, segments=["фермы", "питомники"])
    # Продавцовые сегменты: нишевой бонус сохраняется, штрафа нет.
    assert hunting_shops >= 80
    # Покупательские сегменты: бонус снят + штраф −15.
    assert hunting_shops > hunting_farms


def test_address_only_lead_not_amber_without_match():
    """FIX 3: адрес — не контакт; address-only строка 2GIS без матч-сигнала
    не должна добираться до amber (≥60)."""
    score = score_lead(
        domain="",
        company="ООО Ромашка",
        niche="кормовые добавки для ферм",
        has_email=False,
        has_phone=False,
        has_address=True,
        demo=False,
    )
    assert score < 60


def test_domain_counts_as_contact():
    """FIX 3: домен — контакт (по нему достижимы), штрафа за «нет контактов» нет."""
    domain_only = score_lead(
        domain="ferma-rodniki.ru",
        company="КФХ Родники",
        niche="сельское хозяйство",
        has_email=False,
        has_phone=False,
        has_address=False,
        demo=False,
    )
    nothing = score_lead(
        domain="",
        company="КФХ Родники",
        niche="сельское хозяйство",
        has_email=False,
        has_phone=False,
        has_address=False,
        demo=False,
    )
    assert domain_only > nothing

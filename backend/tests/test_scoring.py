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

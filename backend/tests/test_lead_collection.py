from app.services.lead_collection import (
    _candidate_relevance_score,
    _finalize_candidates,
    _parse_yandex_business_feature,
)


def test_candidate_relevance_prefers_real_company_site_over_rating_page():
    good = {
        "company": "Фабрика окон",
        "website": "https://fabrikaokon.ru",
        "domain": "fabrikaokon.ru",
        "source_url": "https://fabrikaokon.ru/",
        "snippet": "Пластиковые окна в Москве, официальный сайт производителя",
        "source": "searxng",
    }
    bad = {
        "company": "20 лучших оконных компаний в Москве",
        "website": "https://kp.ru/russia/moskva/luchshie-okonnye-kompanii-moskvy/",
        "domain": "kp.ru",
        "source_url": "https://kp.ru/russia/moskva/luchshie-okonnye-kompanii-moskvy/",
        "snippet": "Рейтинг и обзор компаний по установке окон",
        "source": "searxng",
    }

    good_score = _candidate_relevance_score(good, "пластиковые окна", "москва", [])
    bad_score = _candidate_relevance_score(bad, "пластиковые окна", "москва", [])

    assert good_score > bad_score
    assert good_score >= 26
    assert bad_score < 0


def test_parse_yandex_business_feature_extracts_domain_and_city():
    feature = {
        "properties": {
            "name": "Фабрика окон",
            "description": "Москва, ул. Ленина, 10",
            "CompanyMetaData": {
                "name": "Фабрика окон",
                "url": "https://fabrikaokon.ru",
                "address": "Москва, ул. Ленина, 10",
                "Address": {
                    "formatted": "Москва, ул. Ленина, 10",
                    "Components": [
                        {"kind": "country", "name": "Россия"},
                        {"kind": "locality", "name": "Москва"},
                    ],
                },
                "Categories": [{"name": "Остекление"}, {"name": "Окна"}],
                "Hours": {"text": "ежедневно, 09:00-18:00"},
            },
        }
    }

    item = _parse_yandex_business_feature(feature, "пластиковые окна москва")

    assert item is not None
    assert item["company"] == "Фабрика окон"
    assert item["website"] == "https://fabrikaokon.ru"
    assert item["domain"] == "fabrikaokon.ru"
    assert item["city"] == "Москва"
    assert item["source"] == "yandex_maps"
    assert "Окна" in item["snippet"]


def test_finalize_candidates_keeps_highest_scored_source_for_same_domain():
    ranked = _finalize_candidates(
        [
            {
                "company": "Фабрика окон",
                "website": "https://fabrikaokon.ru",
                "domain": "fabrikaokon.ru",
                "source": "searxng",
                "relevance_score": 48,
            },
            {
                "company": "Фабрика окон",
                "website": "https://fabrikaokon.ru",
                "domain": "fabrikaokon.ru",
                "source": "yandex_maps",
                "relevance_score": 82,
            },
        ],
        10,
    )

    assert len(ranked) == 1
    assert ranked[0]["source"] == "yandex_maps"
    assert ranked[0]["relevance_score"] == 82


def test_candidate_relevance_rejects_synthetic_spam_result():
    spam = {
        "company": "Odievami omoloni cawneli aja utoberum wabezhi пластиковые окна завод москва",
        "website": "http://dotiat.io/je",
        "domain": "dotiat.io",
        "source_url": "http://dotiat.io/je",
        "snippet": (
            "Gotlutfos mujiruw ken ifobih epzada ad firfiz tuhhejsag jus pihojrih "
            "wimi puhifme tapucidib cit"
        ),
        "source": "searxng",
    }

    spam_score = _candidate_relevance_score(spam, "пластиковые окна", "москва", [])

    assert spam_score < 0

import app.services.lead_collection as lc
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


# ─── Fix [yandex-budget]: один вызов на гео, бюджет делится по сегментам ─────


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeYandexClient:
    """Эмулятор Yandex Places API: считает геокодинг bbox и поисковые вызовы,
    отдаёт по 10 уникальных организаций на (query, skip)-страницу."""

    def __init__(self, recorder):
        self.recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, params=None, **kwargs):
        params = params or {}
        if params.get("type") == "geo":
            self.recorder["bbox_calls"] += 1
            return _FakeResp(
                {"features": [{"properties": {"boundedBy": [[55.0, 37.0], [56.0, 38.0]]}}]}
            )
        assert params.get("type") == "biz"
        query = params["text"]
        skip = params.get("skip", 0)
        self.recorder["search_calls"].append((query, skip))
        # «тонкие» сегменты: запросы с этими подстроками не дают результатов
        for empty_marker in self.recorder.get("empty_markers", ()):
            if empty_marker in query:
                return _FakeResp({"features": []})
        feats = []
        for i in range(10):
            name = f"{query}-{skip}-{i}"
            feats.append({
                "properties": {
                    "name": name,
                    "CompanyMetaData": {
                        "name": name,
                        "address": f"ул. Тестовая, {i}",
                        "Address": {
                            "formatted": f"ул. Тестовая, {i}",
                            "Components": [{"kind": "locality", "name": "Томск"}],
                        },
                        "Phones": [{"formatted": f"+7 999 00{skip % 10}-{10 + i}-22"}],
                    },
                }
            })
        return _FakeResp({"features": feats})


def _patch_yandex_api(monkeypatch, recorder):
    from types import SimpleNamespace

    monkeypatch.setattr(lc, "_YANDEX_DEAD_KEY", False)
    lc._YANDEX_BBOX_CACHE.clear()
    monkeypatch.setattr(
        lc, "get_settings",
        lambda: SimpleNamespace(yandex_maps_api_key="test-key", yandex_maps_lang="ru_RU"),
    )
    monkeypatch.setattr(lc.httpx, "Client", lambda *a, **k: _FakeYandexClient(recorder))
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_yandex_budget_split_across_segments(monkeypatch):
    """Каждый сегмент получает свою долю бюджета — раньше ранний break отдавал
    весь бюджет первому сегменту, остальные получали ноль покрытия."""
    recorder = {"bbox_calls": 0, "search_calls": []}
    _patch_yandex_api(monkeypatch, recorder)

    segments = ["ферма", "птицефабрика", "комбинат", "теплица"]
    results = lc._search_yandex_maps("корм", "Томск", segments, 40, has_prompt=True)

    assert len(results) == 40
    per_segment = {seg: sum(1 for r in results if seg in r["company"]) for seg in segments}
    # равные доли: 40 // 4 = 10 на сегмент, никто не съел весь бюджет
    assert per_segment == {seg: 10 for seg in segments}, per_segment
    # bbox геокодился РОВНО один раз
    assert recorder["bbox_calls"] == 1


def test_yandex_leftover_budget_redistributed_to_dense_segments(monkeypatch):
    """Тонкий сегмент не выбрал свою долю — остаток бюджета добирают плотные
    сегменты вторым проходом (без перезапроса уже оплаченных страниц)."""
    recorder = {"bbox_calls": 0, "search_calls": [], "empty_markers": ("теплица",)}
    _patch_yandex_api(monkeypatch, recorder)

    results = lc._search_yandex_maps(
        "корм", "Томск", ["ферма", "теплица"], 20, has_prompt=True,
    )

    # 10 (доля фермы) + 0 (теплица пуста) + 10 (leftover-проход) = 20
    assert len(results) == 20
    assert sum(1 for r in results if "ферма" in r["company"]) == 20
    # leftover-проход продолжил пагинацию фермы с нового offset'а,
    # а не перезапросил оплаченную страницу skip=0
    ferma_skips = [s for q, s in recorder["search_calls"] if "ферма" in q]
    assert sorted(ferma_skips) == sorted(set(ferma_skips)), "повторный платный вызов той же страницы"


def test_yandex_bbox_cached_across_calls(monkeypatch):
    """bbox гео кэшируется на процесс — повторный вызов не платит за геокодинг."""
    recorder = {"bbox_calls": 0, "search_calls": []}
    _patch_yandex_api(monkeypatch, recorder)

    lc._search_yandex_maps("корм", "Томск", ["ферма"], 10, has_prompt=True)
    lc._search_yandex_maps("корм", "Томск", ["теплица"], 10, has_prompt=True)

    assert recorder["bbox_calls"] == 1


def _patch_collection_sources(
    monkeypatch,
    *,
    map_rows=None,
    web_pages=None,
    yandex_spy=None,
    llm_filter=None,
):
    """Заглушки всех внешних источников _search_leads_one_tier."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(lc, "_search_2gis", lambda *a, **k: list(map_rows or []))
    monkeypatch.setattr(lc, "_search_2gis_scrape", lambda *a, **k: list(map_rows or []))
    monkeypatch.setattr(lc, "_search_yandex_maps_scrape", lambda *a, **k: [])
    monkeypatch.setattr(lc, "_search_rusprofile", lambda *a, **k: [])
    monkeypatch.setattr(lc, "_search_bing", lambda *a, **k: [])
    monkeypatch.setattr(lc, "_search_yandex_maps", yandex_spy or (lambda *a, **k: []))
    monkeypatch.setattr(
        lc, "_searxng_fetch_page",
        web_pages or (lambda client, query, page, settings: []),
    )
    import app.services.llm_filter as llm_mod
    monkeypatch.setattr(
        llm_mod, "filter_candidates_llm",
        llm_filter or (lambda cands, *a, **k: list(cands)),
    )


def test_search_one_tier_calls_yandex_once_per_geo(monkeypatch):
    """Fix [yandex-budget]: _search_yandex_maps вызывается ОДИН раз на гео со
    всем списком сегментов — не внутри цикла по term (раньше до 24×)."""
    calls = []

    def spy(niche, geo, segments, limit, *, has_prompt=False):
        calls.append({"geo": geo, "segments": list(segments), "limit": limit,
                      "has_prompt": has_prompt})
        return []

    _patch_collection_sources(monkeypatch, yandex_spy=spy)

    segs = [f"сегмент{i}" for i in range(6)]
    lc._search_leads_one_tier(
        "корм", 10,
        niche="корм", geography="Томск", segments=segs, prompt="продаю корм",
    )

    assert len(calls) == 1
    assert calls[0]["geo"] == "Томск"
    assert calls[0]["segments"] == segs
    assert calls[0]["has_prompt"] is True
    assert calls[0]["limit"] >= 20  # бюджет — остаток oversample-окна


def _make_map_item(i: int) -> dict:
    return {
        "company": f"Ферма №{i}",
        "city": "Томск",
        "website": "",
        "domain": "",
        "phone": "+79990001122",
        "source_url": "https://2gis.ru/tomsk/search/ферма",
        "snippet": f"ул. Полевая, {i}, +7 999 000-11-22",
        "address": f"ул. Полевая, {i}",
        "demo": False,
        "source": "2gis",
        "firm_id": str(1000 + i),
    }


def _make_web_item(i: int) -> dict:
    return {
        "company": f"Столовая Сибирь {i}",
        "city": "",
        "website": f"https://stolovaya{i}.ru",
        "domain": f"stolovaya{i}.ru",
        "source_url": f"https://stolovaya{i}.ru/",
        "snippet": "Кейтеринг и корпоративное питание в Томске. ООО, звоните +7 999 111-22-33",
        "demo": False,
        "source": "searxng",
    }


def test_web_pass_reserved_budget_when_maps_fill_cap(monkeypatch):
    """Fix [unique-cap]/[web-reserve]: карты забили oversample-кап ещё ДО
    SearXNG — веб-проход всё равно обязан добрать свой резерв (раньше он
    обрывался на полном капе → лиды без сайтов/email)."""
    map_rows = [_make_map_item(i) for i in range(200)]  # кап (60) забит с запасом
    served = iter(range(10_000))

    def web_pages(client, query, page, settings):
        return [_make_web_item(next(served)) for _ in range(10)]

    _patch_collection_sources(monkeypatch, map_rows=map_rows, web_pages=web_pages)

    result = lc._search_leads_one_tier(
        "кейтеринг", 10,
        niche="кейтеринг", geography="Томск", segments=[], prompt="",
    )

    assert result, "ожидали непустой результат"
    web_rows = [r for r in result if r.get("source") == "searxng"]
    assert web_rows, "веб-кандидаты не попали в выдачу — резерв веб-прохода не сработал"


def test_llm_filter_shortfall_refilled_from_buffer(monkeypatch):
    """Fix [llm-refill]: финализация с буфером 2×limit — фильтр, срезающий
    50%, больше не оставляет недобор (раньше truncate шёл ДО фильтра)."""
    map_rows = [_make_map_item(i) for i in range(200)]
    served = iter(range(10_000))

    def web_pages(client, query, page, settings):
        return [_make_web_item(next(served)) for _ in range(10)]

    def drop_every_other(cands, *a, **k):
        return [c for idx, c in enumerate(cands) if idx % 2 == 0]

    _patch_collection_sources(
        monkeypatch, map_rows=map_rows, web_pages=web_pages,
        llm_filter=drop_every_other,
    )

    result = lc._search_leads_one_tier(
        "кейтеринг", 10,
        niche="кейтеринг", geography="Томск", segments=[], prompt="",
    )

    # буфер 2×10=20 → фильтр оставил 10 → ровно limit, недобора нет
    assert len(result) == 10


# ─── Fix [scrape-guard]: чужой телефон со страницы поиска 2GIS ───────────────


def _two_firm_search_html() -> str:
    filler = " проспект Ленина, дом 1, офис 2 " * 30  # > 500 символов между карточками
    return (
        '<div class="card">'
        '{"primary":"Кафе Ромашка"} тел. +7 (495) 111-11-11 '
        '<a href="/tomsk/firm/111111111">Кафе Ромашка</a>'
        "</div>"
        + filler +
        '<div class="card">'
        '{"primary":"Пекарня Колосок"} тел. +7 (495) 222-22-22 '
        '<a href="/tomsk/firm/222222222">Пекарня Колосок</a>'
        "</div>"
    )


def test_find_firm_id_matches_right_card():
    html = _two_firm_search_html()
    assert lc._find_firm_id_in_search_html(html, "Пекарня Колосок") == "222222222"
    assert lc._find_firm_id_in_search_html(html, "Кафе Ромашка") == "111111111"
    assert lc._find_firm_id_in_search_html(html, "Шиномонтаж Вулкан") == ""


def test_name_window_isolates_own_card():
    filler = " наполнитель страницы поиска " * 40
    html = (
        "Кафе Ромашка тел. +7 (495) 111-11-11"
        + filler +
        "Пекарня Колосок тел. +7 (495) 222-22-22"
    )
    window = lc._name_window_html(html, "Пекарня Колосок")
    assert "222-22-22" in window
    assert "111-11-11" not in window
    assert lc._name_window_html(html, "Шиномонтаж Вулкан") == ""


def test_enrich_2gis_scrape_takes_phone_from_matched_firm_page(monkeypatch):
    """Страница поиска с ДВУМЯ фирмами: берём /firm/{id} карточки, прошедшей
    name-match, и контакты со страницы самой фирмы — а не phones[0] со всей
    многокомпанийной страницы (раньше так клеился чужой телефон)."""
    search_html = _two_firm_search_html()
    firm_html = (
        '<div>Пекарня Колосок</div><a href="tel:+7 (495) 222-22-22">позвонить</a>'
    )
    fetched: list[str] = []

    def fake_fetch(url, *, _is_enrich=False):
        fetched.append(url)
        if "/firm/222222222" in url:
            return firm_html
        if "/search/" in url:
            return search_html
        return ""

    monkeypatch.setattr(
        lc, "_fetch_2gis_contacts_api",
        lambda *a, **k: {"emails": [], "phones": [], "addresses": []},
    )
    monkeypatch.setattr(lc, "_fetch_2gis_html", fake_fetch)
    monkeypatch.setattr(lc, "_TWOGIS_SCRAPE_BLOCKED_ENRICH", False)

    result = lc.enrich_2gis_lead("Пекарня Колосок", "Томск")

    assert result["phones"] == ["+74952222222"]
    assert "+74951111111" not in result["phones"]
    assert any("/firm/222222222" in u for u in fetched)


def test_enrich_2gis_scrape_proximity_guard_without_firm_links(monkeypatch):
    """Ссылок /firm/{id} нет — телефон засчитывается только в ±500 символах
    от совпадения имени (минимальный гард)."""
    filler = " наполнитель страницы поиска " * 40
    search_html = (
        "Кафе Ромашка тел. +7 (495) 111-11-11"
        + filler +
        "Пекарня Колосок тел. +7 (495) 222-22-22"
    )
    monkeypatch.setattr(
        lc, "_fetch_2gis_contacts_api",
        lambda *a, **k: {"emails": [], "phones": [], "addresses": []},
    )
    monkeypatch.setattr(
        lc, "_fetch_2gis_html",
        lambda url, *, _is_enrich=False: search_html if "/search/" in url else "",
    )
    monkeypatch.setattr(lc, "_TWOGIS_SCRAPE_BLOCKED_ENRICH", False)

    result = lc.enrich_2gis_lead("Пекарня Колосок", "Томск")
    assert result["phones"] == ["+74952222222"]

    # имя вообще не встречается на странице → контактов не берём НИКАКИХ
    result_miss = lc.enrich_2gis_lead("Шиномонтаж Вулкан", "Томск")
    assert result_miss["phones"] == []


# ── address-component priority + federal-district region guard ──────────────

def test_extract_address_component_honors_argument_priority():
    """Yandex lists province «ЦФО» before locality «Рязань» — the extractor
    must honor the caller's kind priority, not component order, and prefer the
    most specific match within a kind."""
    payload = {
        "Components": [
            {"kind": "country", "name": "Россия"},
            {"kind": "province", "name": "Центральный федеральный округ"},
            {"kind": "province", "name": "Рязанская область"},
            {"kind": "locality", "name": "Рязань"},
        ]
    }
    assert lc._extract_address_component(payload, "locality", "province") == "Рязань"
    # No locality → most specific province (last match), not the federal district.
    payload_no_loc = {"Components": payload["Components"][:-1]}
    assert lc._extract_address_component(payload_no_loc, "locality", "province") == "Рязанская область"


def test_region_of_federal_district_is_unknown_not_mismatch():
    """A federal district spans many subjects — it must resolve to '' so the
    hard geo guard can't disqualify rows whose city parsed as «ЦФО»."""
    assert lc._region_of("Центральный федеральный округ") == ""
    # Autonomous okrugs are real federal subjects and must still resolve.
    assert lc._region_of("Ханты-Мансийский автономный округ") != ""


def test_merge_fields_carries_website_and_domain():
    target = {"company": "Приз", "phone": "", "website": "", "domain": ""}
    source = {"company": "Приз", "phone": "+7 4912 21-44-80",
              "website": "http://prizprint.ru", "domain": "prizprint.ru"}
    lc._merge_fields(target, source)
    assert target["phone"] == "+7 4912 21-44-80"
    assert target["website"] == "http://prizprint.ru"
    assert target["domain"] == "prizprint.ru"

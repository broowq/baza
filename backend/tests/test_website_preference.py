"""website_preference — «клиенты без сайта» (инцидент 14.07.2026).

Живой кейс: веб-студия просила «клиентов, у которых НЕТ сайтов» — констрейнт
не имел места в модели и молча терялся, а выдача систематически дискримини-
ровала бездоменных (+8 к скору за сайт). Здесь: экстракция (эвристика фолбэка),
жёсткие фильтры дозы/live, складской SQL, промпт LLM-фильтра и его кэш-ключ,
lookup-хелпер Yandex Search.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

import app.services.lead_collection as lc
from app.services import llm_filter
from app.services.prompt_enhancer import _website_preference_heuristic
from app.tasks.jobs import _matches_website_preference


# ── экстракция: rule-based эвристика (LLM-путь покрыт промптом) ──────────────

@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Я делаю сайты, мне нужны клиенты, у которых нет сайтов", "no_website"),
        ("нужны клиенты без сайта в Томске", "no_website"),
        ("ищу компании у которых отсутствует сайт", "no_website"),
        ("нужны клиенты в Томске у которых нет своего сайта", "no_website"),  # E2E 17.07
        ("клиенты без собственного сайта", "no_website"),
        ("у нас нет своего сайта, делаем клиентам", "any"),  # про себя, не клиента
        ("дорабатываю существующие сайты компаний", "with_website"),
        ("редизайн: нужны компании, у которых есть сайт", "with_website"),
        ("продаю кормовые добавки", "any"),
        ("делаю сайты для бизнеса", "any"),  # без явного «без сайтов» — any
    ],
)
def test_heuristic(prompt, expected):
    assert _website_preference_heuristic(prompt) == expected


# ── жёсткий фильтр дозы ──────────────────────────────────────────────────────

def test_matches_website_preference():
    with_site = {"website": "https://firm.ru", "domain": "firm.ru"}
    maps_only = {"website": "maps://2gis/123", "domain": "", "phone": "+7 999"}
    bare = {"company": "ООО Ромашка"}
    assert _matches_website_preference(with_site, "any")
    assert not _matches_website_preference(with_site, "no_website")
    assert _matches_website_preference(with_site, "with_website")
    assert _matches_website_preference(maps_only, "no_website")
    assert not _matches_website_preference(maps_only, "with_website")
    assert _matches_website_preference(bare, "no_website")


# ── LLM-фильтр: промпт и кэш-ключ ────────────────────────────────────────────

def test_filter_config_hash_varies_with_preference():
    base = llm_filter._filter_config_hash("ниша", "Томск", ["с1"], "промпт", [])
    nosite = llm_filter._filter_config_hash("ниша", "Томск", ["с1"], "промпт", [], "no_website")
    anyv = llm_filter._filter_config_hash("ниша", "Томск", ["с1"], "промпт", [], "any")
    assert base != nosite
    # any — исторический дефолт: ключ БАЙТ-В-БАЙТ прежний (кэш всех
    # существующих проектов переживает деплой без LLM-респенда)
    assert base == anyv


def test_filter_prompt_carries_website_rule(monkeypatch):
    captured = {}

    def fake_chat(prompt, **kw):
        captured["prompt"] = prompt
        return '{"keep": [1]}'

    monkeypatch.setattr(llm_filter.llm_client, "chat", fake_chat)
    batch = [{"company": "ООО Ромашка", "domain": "romashka.ru", "city": "Томск"}]
    llm_filter._ai_filter_batch(
        batch, "ниша", "Томск", ["с1"], "делаю сайты",
        website_preference="no_website",
    )
    assert "БЕЗ сайта" in captured["prompt"]
    assert "ОТКЛОНЯЙ кандидатов, у которых указан сайт" in captured["prompt"]


def test_filter_prompt_unchanged_for_any(monkeypatch):
    captured = {}

    def fake_chat(prompt, **kw):
        captured["prompt"] = prompt
        return '{"keep": [1]}'

    monkeypatch.setattr(llm_filter.llm_client, "chat", fake_chat)
    batch = [{"company": "ООО Ромашка", "domain": "romashka.ru", "city": "Томск"}]
    llm_filter._ai_filter_batch(batch, "ниша", "Томск", ["с1"], "промпт", website_preference="any")
    assert "ТРЕБОВАНИЕ К САЙТУ" not in captured["prompt"]


# ── Yandex Search company lookup (фолбэк контактов + верификатор сайта) ──────

_LOOKUP_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <results><grouping>
      <group><doc>
        <url>https://romashka-tomsk.ru/contacts</url>
        <domain>romashka-tomsk.ru</domain>
        <title>Ромашка — стоматологическая клиника | Томск</title>
        <passages><passage>Запись на приём: +7 (3822) 55-44-33, info@romashka-tomsk.ru</passage></passages>
      </doc></group>
    </grouping></results>
  </response>
</yandexsearch>"""


@pytest.fixture
def _no_lookup_cache(monkeypatch):
    """Redis-кэш lookup'а отключён: тесты не должны видеть вердикты друг друга."""
    monkeypatch.setattr(lc, "_get_redis", lambda: None)


def test_yandex_lookup_extracts_site_and_contacts(monkeypatch, _no_lookup_cache):
    def fake_fetch(client, query, page, settings):
        assert "Ромашка" in query and "контакты" in query
        return lc._parse_yandex_search_xml(_LOOKUP_XML)

    monkeypatch.setattr(lc, "_yandex_search_fetch_page", fake_fetch)
    monkeypatch.setattr(lc, "_yandex_search_configured", lambda s: True)
    got = lc.yandex_search_company_lookup("Ромашка стоматологическая", "Томск")
    assert "romashka-tomsk.ru" in got["website"]
    assert got["phone"] == "+73822554433"  # 4-значный код города распознан
    assert got["email"] == "info@romashka-tomsk.ru"


def test_yandex_lookup_quoted_name_still_matches(monkeypatch, _no_lookup_cache):
    """«Ромашка» в кавычках/с запятой в тайтле — токенизация срезает
    пунктуацию (ревью 14.07: .split() оставлял «ромашка,» и матч не случался)."""
    xml = _LOOKUP_XML.replace(
        "<title>Ромашка — стоматологическая клиника | Томск</title>",
        "<title>Стоматологическая клиника «Ромашка», Томск</title>",
    )
    monkeypatch.setattr(lc, "_yandex_search_fetch_page",
                        lambda c, q, page, settings: lc._parse_yandex_search_xml(xml))
    monkeypatch.setattr(lc, "_yandex_search_configured", lambda s: True)
    got = lc.yandex_search_company_lookup("Ромашка", "Томск")
    assert "romashka-tomsk.ru" in got["website"]


def test_yandex_lookup_no_match_returns_nothing(monkeypatch, _no_lookup_cache):
    """Чужая выдача: ни сайт, ни КОНТАКТЫ не приписываются — телефон чужой
    компании из соседнего сниппета хуже пустого (major ревью 14.07)."""
    monkeypatch.setattr(lc, "_yandex_search_fetch_page",
                        lambda c, q, page, settings: lc._parse_yandex_search_xml(_LOOKUP_XML))
    monkeypatch.setattr(lc, "_yandex_search_configured", lambda s: True)
    got = lc.yandex_search_company_lookup("Пилорама Сибирь", "Томск")
    assert got == {"website": "", "phone": "", "email": ""}


def test_yandex_lookup_generic_words_do_not_match(monkeypatch, _no_lookup_cache):
    """Пересечение только по generic-словам («строительная», «компания») —
    НЕ матч: иначе «Альфа» получала бы сайт и телефон «Домостроя»."""
    xml = _LOOKUP_XML.replace(
        "<title>Ромашка — стоматологическая клиника | Томск</title>",
        "<title>Строительная компания Домострой — Томск</title>",
    )
    monkeypatch.setattr(lc, "_yandex_search_fetch_page",
                        lambda c, q, page, settings: lc._parse_yandex_search_xml(xml))
    monkeypatch.setattr(lc, "_yandex_search_configured", lambda s: True)
    got = lc.yandex_search_company_lookup("Строительная компания Альфа", "Томск")
    assert got == {"website": "", "phone": "", "email": ""}


def test_yandex_lookup_unconfigured_returns_empty(monkeypatch):
    monkeypatch.setattr(lc, "_yandex_search_configured", lambda s: False)
    assert lc.yandex_search_company_lookup("Ромашка", "Томск") == {}


# ── бэкстоп LLM-пути (E2E 17.07) ─────────────────────────────────────────────

def _stub_llm(monkeypatch, website_preference):
    import json as _json

    from app.services import prompt_enhancer as pe

    payload = {
        "enhanced_prompt": "x", "project_name": "P", "niche": "малый бизнес",
        "geography": "Томск", "segments": ["кафе", "магазин", "салон"],
        "excluded_segments": [], "website_preference": website_preference,
        "okved_codes": [], "explanation": "e",
    }
    monkeypatch.setattr(pe.llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(pe.llm_client, "chat", lambda *a, **k: _json.dumps(payload))
    return pe


def test_llm_any_overridden_by_heuristic_when_prompt_is_explicit(monkeypatch):
    """LLM часто возвращает website_preference="any" при явном «нет своего
    сайта» (воспроизведено вживую 17.07 — инцидент 14.07 повторялся). Финали-
    зация в _try_llm_enhance доверяет regex-эвристике, когда LLM сказал "any"."""
    pe = _stub_llm(monkeypatch, "any")
    out = pe._try_llm_enhance("делаю сайты, нужны клиенты у которых нет своего сайта", organization_id=None)
    assert out is not None
    assert out["website_preference"] == "no_website"


def test_llm_definite_verdict_survives_backstop(monkeypatch):
    """Если LLM дал НЕ-"any" вердикт — он сохраняется (ловит формулировки,
    которые regex пропускает); эвристика не перетирает его."""
    pe = _stub_llm(monkeypatch, "no_website")
    # промпт без явного regex-сигнала — эвристика вернула бы "any", но LLM уверен
    out = pe._try_llm_enhance("хочу выйти на компании, которым нужен новый лендинг", organization_id=None)
    assert out is not None
    assert out["website_preference"] == "no_website"

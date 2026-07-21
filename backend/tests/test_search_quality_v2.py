"""Батч «поиск v2» (21.07.2026): рейтинг/отзывы 2GIS, ЕГРЮЛ-справка DaData,
сигнал найма hh.ru, соцсети, петля обратной связи rejected-лидов, скоринг.

Warehouse-тесты бьют в реальный локальный Postgres (как test_company_warehouse);
чистят за собой по уникальному префиксу. Сетевые сервисы (DaData/hh) мокаются
на уровне httpx, Redis-кэши отключаются monkeypatch'ем.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Company, Lead, LeadStatus, Organization, PlanType, Project
from app.services import company_warehouse as cw
from app.services import dadata, hh, llm_filter
from app.services.lead_collection import (
    _extract_social_links,
    _merge_fields,
    _parse_2gis_reviews,
    sanitize_social,
)
from app.services.scoring import score_lead
from app.tasks.jobs import _rejected_examples

_PFX = "sq2test-"


# ── 2GIS: рейтинг/отзывы ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("reviews", "expected"),
    [
        ({"general_rating": 4.63, "general_review_count": 21}, (4.6, 21)),
        ({"rating": "4.0", "review_count": "7"}, (4.0, 7)),
        ({"general_rating": 0, "general_review_count": 0}, (None, None)),  # 0 = нет оценок
        ({"general_rating": 9.9}, (None, None)),   # вне шкалы 0–5 — мусор
        ({"general_review_count": 3}, (None, 3)),  # отзывы без рейтинга
        ({"general_rating": "NaN"}, (None, None)),  # NaN-безопасность (ревью 21.07)
        ({}, (None, None)),
        (None, (None, None)),
        ("мусор", (None, None)),
    ],
)
def test_parse_2gis_reviews(reviews, expected):
    assert _parse_2gis_reviews({"reviews": reviews}) == expected


def test_merge_fields_keeps_quality_fields():
    """Ревью 21.07 (major): при swap'е базы в _finalize_candidates (веб-кандидат
    победил 2GIS по relevance) rating/vk/firm_id 2GIS-записи не должны теряться."""
    target = {"company": "Хвоя", "relevance_score": 90, "domain": "hvoya.ru"}
    source = {
        "rating": 4.5, "review_count": 7, "vk": "https://vk.com/hvoya",
        "telegram": "https://t.me/hvoya", "firm_id": "123", "extra_phones": ["+79990000000"],
    }
    _merge_fields(target, source)
    assert target["rating"] == 4.5 and target["review_count"] == 7
    assert target["vk"] == "https://vk.com/hvoya" and target["telegram"] == "https://t.me/hvoya"
    assert target["firm_id"] == "123" and target["extra_phones"] == ["+79990000000"]
    # fill-empty: непустое у цели не затирается
    _merge_fields(target, {"rating": 1.0})
    assert target["rating"] == 4.5


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("vk", "https://vk.com/lesprom", "https://vk.com/lesprom"),
        ("vk", "vk.com/lesprom", "https://vk.com/lesprom"),          # бессхемный → https
        ("vk", "Наша группа", ""),                                    # подпись, не URL
        ("vk", "javascript:alert(1)", ""),                            # чужая схема
        ("vk", "https://vk.com/share.php?url=x", ""),                 # сервисный путь
        ("vk", "https://vk.com/videostudio70", "https://vk.com/videostudio70"),  # ник с префиксом video
        ("telegram", "t.me/lesprom_bot", "https://t.me/lesprom_bot"),
        ("telegram", "https://t.me/joinchat/AAAAAEkk2WdoEd8vh1x2Ag",
         "https://t.me/joinchat/AAAAAEkk2WdoEd8vh1x2Ag"),             # инвайт целиком
        ("telegram", "@lesprom", ""),
        ("telegram", "", ""),
    ],
)
def test_sanitize_social(kind, raw, expected):
    assert sanitize_social(kind, raw) == expected


# ── Соцсети из HTML (краулер сайтов) ─────────────────────────────────────────

def test_social_links_extracted():
    html = (
        '<a href="https://vk.com/share.php?url=x">поделиться</a>'
        '<a href="https://vk.com/lesprom_tomsk">наша группа</a>'
        '<footer><a href="https://t.me/lesprom_bot">телеграм</a></footer>'
    )
    got = _extract_social_links(html)
    assert got["vk"] == "https://vk.com/lesprom_tomsk"  # share.php отсеян
    assert got["telegram"] == "https://t.me/lesprom_bot"


def test_social_links_absent():
    assert _extract_social_links("<p>没有</p>") == {"vk": "", "telegram": ""}
    assert _extract_social_links("") == {"vk": "", "telegram": ""}


# ── DaData: ЕГРЮЛ-справка по названию ────────────────────────────────────────

def _sug(short, inn, status="ACTIVE", city="Томск", okved="16.10", addr=None, party_type="LEGAL"):
    return {
        "value": short,
        "data": {
            "inn": inn,
            "type": party_type,
            "okved": okved,
            "state": {"status": status, "registration_date": 1_600_000_000_000},
            "address": {"value": addr or f"634050, г {city}, ул Ленина, 1"},
            "name": {"full": short, "short_with_opf": short},
        },
    }


class _FakeResp:
    def __init__(self, suggestions):
        self._s = suggestions

    def raise_for_status(self):
        return None

    def json(self):
        return {"suggestions": self._s}


@pytest.fixture
def _dadata_ready(monkeypatch):
    monkeypatch.setattr(dadata, "_get_redis", lambda: None)
    monkeypatch.setattr(get_settings(), "dadata_api_key", "test-key", raising=False)


def test_dadata_match_with_city(monkeypatch, _dadata_ready):
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug('ООО "Хвоя Сибири"', "7017123456")]),
    )
    got = dadata.find_party("Хвоя Сибири", "Томск")
    assert got["inn"] == "7017123456"
    assert got["status"] == "ACTIVE"
    assert got["okved"] == "16.10"
    assert isinstance(got["registered_at"], datetime)


def test_dadata_city_mismatch_returns_empty(monkeypatch, _dadata_ready):
    """Тёзка из другого региона: чужой ИНН хуже пустого."""
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug('ООО "Хвоя Сибири"', "7017123456", city="Москва")]),
    )
    assert dadata.find_party("Хвоя Сибири", "Томск") == {}


def test_dadata_generic_name_skips_http(monkeypatch, _dadata_ready):
    """Название целиком из generic-слов — матч дал бы случайного тёзку."""
    def _boom(*a, **kw):
        raise AssertionError("HTTP не должен вызываться")
    monkeypatch.setattr(dadata.httpx, "post", _boom)
    assert dadata.find_party("Торговая компания", "Томск") == {}


def test_dadata_generic_only_overlap_no_match(monkeypatch, _dadata_ready):
    """Пересечение только по generic-словам — не матч (принцип веб-lookup)."""
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug('ООО "Строительная компания Домострой"', "7017999999")]),
    )
    assert dadata.find_party("Строительная компания Альфа", "Томск") == {}


def test_dadata_ambiguous_inns_return_empty(monkeypatch, _dadata_ready):
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([
            _sug('ООО "Хвоя"', "7017111111"),
            _sug('ООО "Хвоя"', "7017222222"),
        ]),
    )
    assert dadata.find_party("Хвоя", "Томск") == {}


def test_dadata_prefers_active_over_liquidated(monkeypatch, _dadata_ready):
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([
            _sug('ООО "Хвоя"', "7017111111", status="LIQUIDATED"),
            _sug('ООО "Хвоя"', "7017222222", status="ACTIVE"),
        ]),
    )
    got = dadata.find_party("Хвоя", "Томск")
    assert got["inn"] == "7017222222"
    assert got["status"] == "ACTIVE"


def test_dadata_liquidated_only_still_reported(monkeypatch, _dadata_ready):
    """Единственный матч ликвидирован — честно возвращаем статус (лид получит
    тег и кап скора, а не молчаливое отсутствие данных)."""
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug('ООО "Хвоя"', "7017111111", status="LIQUIDATED")]),
    )
    got = dadata.find_party("Хвоя", "Томск")
    assert got["inn"] == "7017111111"
    assert got["status"] == "LIQUIDATED"


def test_dadata_region_city_matches_abbreviated_address(monkeypatch, _dadata_ready):
    """«Московская область» лида должна матчиться на «Московская обл» в адресе
    ЕГРЮЛ (ревью 21.07: substring по полной строке ложно отбрасывал)."""
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug(
            'ООО "Хвоя Сибири"', "5029123456",
            addr="141021, Московская обл, г Мытищи, ул Мира, 5",
        )]),
    )
    got = dadata.find_party("Хвоя Сибири", "Московская область")
    assert got.get("inn") == "5029123456"


def test_dadata_no_city_never_reports_dead(monkeypatch, _dadata_ready):
    """Без гео-подтверждения «смертный приговор» не выносится: ошибочный матч
    тёзки навсегда пометил бы живую компанию ликвидированной (ревью 21.07)."""
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug('ООО "Хвоя"', "7017111111", status="LIQUIDATED")]),
    )
    assert dadata.find_party("Хвоя", "") == {}
    # А живой статус без города — ок.
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug('ООО "Хвоя"', "7017222222", status="ACTIVE")]),
    )
    assert dadata.find_party("Хвоя", "").get("inn") == "7017222222"


def test_dadata_skips_individuals(monkeypatch, _dadata_ready):
    """ИП (type=INDIVIDUAL) не берём: ИНН ИП — персональные данные физлица."""
    monkeypatch.setattr(
        dadata.httpx, "post",
        lambda *a, **kw: _FakeResp([_sug("ИП Хвоин Иван", "701701234567", party_type="INDIVIDUAL")]),
    )
    assert dadata.find_party("Хвоин Иван", "Томск") == {}


def test_dadata_peek_miss_without_redis(monkeypatch):
    monkeypatch.setattr(dadata, "_get_redis", lambda: None)
    assert dadata.peek_party("Хвоя", "Томск") is None


def test_dadata_unconfigured(monkeypatch):
    monkeypatch.setattr(dadata, "_get_redis", lambda: None)
    monkeypatch.setattr(get_settings(), "dadata_api_key", "", raising=False)
    assert dadata.find_party("Хвоя Сибири", "Томск") == {}
    assert not dadata.is_configured()


# ── hh.ru: сигнал найма ──────────────────────────────────────────────────────

def test_hh_match_employer_tokens():
    items = [
        {"name": "СИБУР", "open_vacancies": 500},
        {"name": "Хвоя Сибири, ООО", "open_vacancies": 3},
    ]
    got = hh.match_employer("ООО «Хвоя Сибири»", items)
    assert got is not None and got["open_vacancies"] == 3


def test_hh_match_employer_generic_only_none():
    assert hh.match_employer("Торговая компания", [{"name": "Торговая компания Юг", "open_vacancies": 9}]) is None


def test_hh_match_employer_single_toponym_overlap_none():
    """Ревью 21.07: «Мебель Томск» не должен матчиться на «Томск Хостел» по
    одному общему топониму — чужие вакансии приписывались лиду."""
    assert hh.match_employer("Мебель Томск", [{"name": "Томск Хостел", "open_vacancies": 12}]) is None


def test_hh_match_employer_tie_is_ambiguous():
    items = [
        {"name": "Хвоя Томск", "open_vacancies": 2},
        {"name": "Хвоя Кемерово", "open_vacancies": 5},
    ]
    assert hh.match_employer("Хвоя", items) is None  # ничья 1:1 → неоднозначно


def test_hh_match_employer_single_token_query_ok():
    assert hh.match_employer("СИБУР", [{"name": "СИБУР", "open_vacancies": 500}]) is not None


def test_hh_peek_miss_without_redis(monkeypatch):
    monkeypatch.setattr(hh, "_get_redis", lambda: None)
    assert hh.peek_vacancies("Хвоя Сибири") == (False, None)


def test_hh_open_vacancies(monkeypatch):
    monkeypatch.setattr(hh, "_get_redis", lambda: None)

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"items": [{"name": "Хвоя Сибири", "open_vacancies": 4}]}

    monkeypatch.setattr(hh.httpx, "get", lambda *a, **kw: _R())
    assert hh.open_vacancies("Хвоя Сибири") == 4


def test_hh_disabled(monkeypatch):
    monkeypatch.setattr(hh, "_get_redis", lambda: None)
    monkeypatch.setattr(get_settings(), "hh_enabled", False, raising=False)
    try:
        assert hh.open_vacancies("Хвоя Сибири") is None
    finally:
        monkeypatch.setattr(get_settings(), "hh_enabled", True, raising=False)


# ── Скоринг: найм и статус юрлица ────────────────────────────────────────────

def _score(**kw):
    base = dict(
        domain="hvoya.ru", company="Хвоя Сибири", niche="пиломатериалы",
        has_email=True, has_phone=True, has_address=True, demo=False,
        relevance_score=120, segments=["строительные компании"],
    )
    base.update(kw)
    return score_lead(**base)


def test_scoring_hiring_bonus():
    # База ниже потолка 100 (без email), иначе бонус съедается клампом.
    assert _score(has_email=False) < 95  # прекондиция
    assert _score(has_email=False, hiring=True) == _score(has_email=False) + 5


def test_scoring_dead_legal_status_caps():
    assert _score() > 45  # прекондиция: живой лид набирает больше капа
    assert _score(legal_status="LIQUIDATED") <= 20
    assert _score(legal_status="BANKRUPT") <= 20
    assert _score(legal_status="LIQUIDATING") <= 45
    assert _score(legal_status="ACTIVE") == _score()


# ── LLM-фильтр: петля обратной связи ─────────────────────────────────────────

def test_filter_hash_stable_without_rejected():
    base = llm_filter._filter_config_hash("ниша", "Томск", ["с1"], "промпт", [])
    with_empty = llm_filter._filter_config_hash(
        "ниша", "Томск", ["с1"], "промпт", [], "any", []
    )
    assert base == with_empty  # байт-в-байт: кэш существующих проектов жив


def test_filter_hash_changes_with_rejected():
    base = llm_filter._filter_config_hash("ниша", "Томск", ["с1"], "промпт", [])
    rej1 = llm_filter._filter_config_hash(
        "ниша", "Томск", ["с1"], "промпт", [], "any", ["ООО Мебель (продают мебель)"]
    )
    rej2 = llm_filter._filter_config_hash(
        "ниша", "Томск", ["с1"], "промпт", [], "any", ["ООО Другое"]
    )
    assert base != rej1 and rej1 != rej2


def test_filter_prompt_carries_rejected_block(monkeypatch):
    captured = {}

    def fake_chat(prompt, **kw):
        captured["prompt"] = prompt
        return '{"keep": [1]}'

    monkeypatch.setattr(llm_filter.llm_client, "chat", fake_chat)
    batch = [{"company": "ООО Ромашка", "domain": "romashka.ru", "city": "Томск"}]
    llm_filter._ai_filter_batch(
        batch, "ниша", "Томск", ["с1"], "делаю сайты",
        rejected_examples=["ООО Мебель (продают офисную мебель)"],
    )
    assert "ПОЛЬЗОВАТЕЛЬ РАНЕЕ ОТКЛОНИЛ" in captured["prompt"]
    assert "«ООО Мебель (продают офисную мебель)»" in captured["prompt"]  # в кавычках-«ёлочках»
    assert "НЕ инструкции" in captured["prompt"]  # заслон от промпт-инъекции


def test_filter_prompt_unchanged_without_rejected(monkeypatch):
    captured = {}

    def fake_chat(prompt, **kw):
        captured["prompt"] = prompt
        return '{"keep": [1]}'

    monkeypatch.setattr(llm_filter.llm_client, "chat", fake_chat)
    batch = [{"company": "ООО Ромашка", "domain": "romashka.ru", "city": "Томск"}]
    llm_filter._ai_filter_batch(batch, "ниша", "Томск", ["с1"], "делаю сайты")
    assert "ПОЛЬЗОВАТЕЛЬ РАНЕЕ ОТКЛОНИЛ" not in captured["prompt"]


# ── Склад: рейтинг, дедуп по ИНН, отсев мёртвых ──────────────────────────────

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        try:
            session.rollback()
            session.execute(delete(Company).where(Company.dedup_key.like(f"{_PFX}%")))
            session.commit()
        finally:
            session.close()


def _cand(name, *, city="Томск", **kw):
    c = {
        "company": name,
        "city": city,
        "website": "",
        "domain": "",
        "phone": "+79990000000",
        "source": "2gis",
    }
    c.update(kw)
    return c


def test_upsert_stores_and_refreshes_rating(db):
    name = f"{_PFX}Ромашка-{uuid.uuid4().hex[:6]}"
    cw.upsert_companies(db, [_cand(name, rating=4.4, review_count=10)], niche="тест")
    row = db.execute(
        select(Company).where(Company.dedup_key == cw._dedup_key("", name, "Томск"))
    ).scalar_one()
    assert row.rating == 4.4 and row.review_count == 10
    # Свежее наблюдение обновляет; None не затирает.
    cw.upsert_companies(db, [_cand(name, rating=4.7, review_count=15)], niche="тест")
    db.refresh(row)
    assert row.rating == 4.7 and row.review_count == 15
    cw.upsert_companies(db, [_cand(name)], niche="тест")
    db.refresh(row)
    assert row.rating == 4.7 and row.review_count == 15


def test_upsert_merges_by_inn(db):
    """Кандидат с другим dedup_key, но тем же ИНН — сливается, а не дублируется."""
    name_a = f"{_PFX}Хвоя-{uuid.uuid4().hex[:6]}"
    inn = "70" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "123456"))
    cw.upsert_companies(db, [_cand(name_a, inn=inn)], niche="тест")
    name_b = f"{_PFX}Хвоя-Групп-{uuid.uuid4().hex[:6]}"
    cw.upsert_companies(db, [_cand(name_b, inn=inn)], niche="тест")
    rows = db.execute(select(Company).where(Company.inn == inn)).scalars().all()
    assert len(rows) == 1
    assert rows[0].times_seen == 2


def test_upsert_social_into_contacts_json(db):
    name = f"{_PFX}Соцсети-{uuid.uuid4().hex[:6]}"
    cw.upsert_companies(db, [_cand(name, vk="https://vk.com/hvoya")], niche="тест")
    key = cw._dedup_key("", name, "Томск")
    row = db.execute(select(Company).where(Company.dedup_key == key)).scalar_one()
    assert row.contacts_json.get("vk") == "https://vk.com/hvoya"
    # Поключевой merge: telegram добавляется, vk не затирается.
    cw.upsert_companies(db, [_cand(name, telegram="https://t.me/hvoya")], niche="тест")
    db.refresh(row)
    assert row.contacts_json.get("vk") == "https://vk.com/hvoya"
    assert row.contacts_json.get("telegram") == "https://t.me/hvoya"


def test_search_warehouse_excludes_dead_legal(db):
    niche = f"{_PFX}ниша-{uuid.uuid4().hex[:6]}"
    alive = f"{_PFX}Живая-{uuid.uuid4().hex[:6]}"
    dead = f"{_PFX}Мёртвая-{uuid.uuid4().hex[:6]}"
    cw.upsert_companies(db, [_cand(alive), _cand(dead)], niche=niche)
    # Помечаем вторую ликвидированной (эмулируем DaData write-back).
    dead_row = db.execute(
        select(Company).where(Company.dedup_key == cw._dedup_key("", dead, "Томск"))
    ).scalar_one()
    dead_row.legal_status = "LIQUIDATED"
    db.commit()
    got = cw.search_warehouse(db, niche=niche, geography="Томск", limit=50)
    names = {c["company"] for c in got}
    assert alive in names and dead not in names


def test_company_to_candidate_carries_quality_fields(db):
    name = f"{_PFX}Кандидат-{uuid.uuid4().hex[:6]}"
    cw.upsert_companies(
        db, [_cand(name, rating=4.2, review_count=8, vk="https://vk.com/hvoya")], niche="тест"
    )
    row = db.execute(
        select(Company).where(Company.dedup_key == cw._dedup_key("", name, "Томск"))
    ).scalar_one()
    row.inn = "7017000001"
    row.legal_status = "ACTIVE"
    db.commit()
    c = cw._company_to_candidate(row)
    assert c["rating"] == 4.2 and c["review_count"] == 8
    assert c["inn"] == "7017000001" and c["legal_status"] == "ACTIVE"
    assert c["vk"] == "https://vk.com/hvoya"


# ── Петля обратной связи: выборка rejected-примеров ──────────────────────────

def test_rejected_examples_shape(db):
    org = Organization(name=f"{_PFX}org", plan=PlanType.free)
    db.add(org)
    db.flush()
    project = Project(organization_id=org.id, name="p", niche="н", geography="Томск")
    db.add(project)
    db.flush()
    try:
        for i, (status, desc) in enumerate([
            (LeadStatus.rejected, "продают офисную мебель"),
            (LeadStatus.rejected, ""),
            (LeadStatus.new, "не должен попасть"),
        ]):
            db.add(Lead(
                organization_id=org.id, project_id=project.id,
                company=f"{_PFX}Лид-{i}", website=f"https://{_PFX}{i}.ru",
                status=status, description=desc,
            ))
        db.flush()
        got = _rejected_examples(db, project.id)
        assert f"{_PFX}Лид-0 (продают офисную мебель)" in got
        assert f"{_PFX}Лид-1" in got
        assert all("не должен попасть" not in x for x in got)
        assert len(got) == 2
    finally:
        db.rollback()

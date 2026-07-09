"""Жёсткие исключения из промпта («только b2b», «не розница», «кроме…»).

Клиентский кейс (прод, 09.07.2026): промпт «нужны только b2b компании»
превратился в 20 сегментов «все типы организаций», и warehouse-first сбор
принёс фермерские магазины и розницу. Регресс закрывает всю цепочку:
энхансер (извлечение + вычистка сегментов) → склад (NOT-клаузы) →
LLM-фильтр (блок исключений в промпте + кэш-хэш) → rule-based фолбэк (Step 0).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import Company
from app.services import company_warehouse as cw
from app.services import llm_filter as lf
from app.services import prompt_enhancer as pe

_PFX = "exseg-"


# ── энхансер: _filter_excluded_segments ──────────────────────────────────────

def test_filter_excluded_drops_lemma_overlaps():
    segs = ["оптовая компания", "дистрибьютор", "КФХ", "розничный магазин продуктов",
            "маркетинговое агентство", "фермерское хозяйство"]
    excl = ["розничный магазин", "КФХ", "фермерское хозяйство"]
    out = pe._filter_excluded_segments(segs, excl)
    assert out == ["оптовая компания", "дистрибьютор", "маркетинговое агентство"]


def test_filter_excluded_ignores_generic_words():
    """Пересечение только по генерик-слову («компания») не убивает сегмент."""
    segs = ["оптовая компания", "производственная компания"]
    excl = ["торговая компания"]  # значимая лемма — только «торговый»
    assert pe._filter_excluded_segments(segs, excl) == segs


def test_filter_excluded_subset_semantics():
    """Subset-семантика: гибнет то, что ПОКРЫТО исключением (в обе стороны),
    а пересечение по одной общей лемме валидный сегмент НЕ убивает."""
    excl = ["розничный магазин"]
    # исключение ⊆ сегмент (склонённые формы) → гибнет
    assert pe._filter_excluded_segments(["розничные магазины продуктов"], excl) == []
    # сегмент ⊆ исключение («магазин» покрыт «розничный магазин») → гибнет
    assert pe._filter_excluded_segments(["магазин"], excl) == []
    # общая лемма «магазин», но свой модификатор → ВЫЖИВАЕТ (major ревью:
    # «оптовый магазин» — валидная B2B-цель; спорное добьёт LLM-фильтр)
    survivors = ["оптовый магазин", "интернет-магазин", "оптовая база"]
    assert pe._filter_excluded_segments(survivors, excl) == survivors


def test_filter_excluded_noop_without_exclusions():
    segs = ["птицефабрика"]
    assert pe._filter_excluded_segments(segs, []) == segs


# ── энхансер: парсинг excluded_segments из ответа LLM ────────────────────────

def test_llm_enhance_parses_and_applies_excluded(monkeypatch):
    answer = """{
      "enhanced_prompt": "SaaS для B2B-лидогенерации",
      "project_name": "B2B клиенты",
      "niche": "компании с B2B-продажами",
      "geography": "Томск",
      "segments": ["маркетинговое агентство", "оптовая компания", "КФХ", "розничный магазин"],
      "excluded_segments": ["КФХ", "розничный магазин", "НКО"],
      "target_customer_types": ["агентства"],
      "search_queries_niche": "агентства",
      "okved_codes": []
    }"""
    monkeypatch.setattr(pe.llm_client, "chat", lambda *a, **k: answer)
    res = pe._try_llm_enhance("нужны только b2b компании")
    assert res is not None
    # исключения нормализованы и сохранены
    assert res["excluded_segments"] == ["КФХ", "розничный магазин", "НКО"]
    # сегменты вычищены от пересечений с исключениями (LLM положил в оба списка)
    assert res["segments"] == ["маркетинговое агентство", "оптовая компания"]


def test_llm_enhance_excluded_capped_at_12(monkeypatch):
    excl = [f"тип {i}" for i in range(20)]
    answer = (
        '{"niche": "x", "geography": "y", "project_name": "p", '
        '"segments": ["оптовая компания"], "excluded_segments": '
        + str(excl).replace("'", '"') + "}"
    )
    monkeypatch.setattr(pe.llm_client, "chat", lambda *a, **k: answer)
    res = pe._try_llm_enhance("промпт")
    assert len(res["excluded_segments"]) == 12


def test_fallback_path_always_has_excluded_field(monkeypatch):
    monkeypatch.setattr(pe.llm_client, "is_configured", lambda: False)
    res = pe.enhance_prompt("Продаю корм для птицефабрик в Томске")
    assert res["excluded_segments"] == []


def test_2gis_augment_is_filtered_against_excluded(monkeypatch):
    """Добор категорий-сиблингов с 2ГИС не возвращает исключённые типы."""
    monkeypatch.setattr(pe.llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        pe, "_try_llm_enhance",
        lambda raw_prompt, organization_id=None: {
            "niche": "b2b", "geography": "Томск", "project_name": "p",
            "segments": ["оптовая компания"],
            "excluded_segments": ["розничный магазин"],
            "okved_codes": [],
        },
    )
    # 2ГИС «дообогатил» список розницей — фильтр обязан её снять.
    monkeypatch.setattr(
        pe, "_augment_with_2gis_categories",
        lambda s, g, p: list(s) + ["розничный магазин у дома"],
    )
    res = pe.enhance_prompt("нужны только b2b компании")
    assert "розничный магазин у дома" not in res["segments"]
    assert "оптовая компания" in res["segments"]


# ── LLM-фильтр: кэш-хэш и промпт ─────────────────────────────────────────────

def test_config_hash_includes_excluded_segments():
    base = lf._filter_config_hash("n", "g", ["s"], "p")
    with_excl = lf._filter_config_hash("n", "g", ["s"], "p", ["розница"])
    assert base != with_excl
    # ПУСТЫЕ исключения дают тот же ключ, что и отсутствие параметра — деплой
    # не инвалидирует 7-дневный кэш вердиктов у проектов без ограничений.
    assert lf._filter_config_hash("n", "g", ["s"], "p", []) == base
    assert lf._filter_config_hash("n", "g", ["s"], "p", None) == base
    # детерминизм и независимость от порядка
    assert with_excl == lf._filter_config_hash("n", "g", ["s"], "p", ["розница"])
    assert (
        lf._filter_config_hash("n", "g", ["s"], "p", ["а", "б"])
        == lf._filter_config_hash("n", "g", ["s"], "p", ["б", "а"])
    )


def test_ai_filter_prompt_contains_exclusion_block(monkeypatch):
    captured: dict = {}

    def fake_chat(prompt_text, **kw):
        captured["prompt"] = prompt_text
        return '{"keep": []}'

    monkeypatch.setattr(lf.llm_client, "chat", fake_chat)
    batch = [{"company": "КФХ Русское поле", "domain": "", "city": "Томск"}]
    lf._ai_filter_batch(
        batch, "b2b", "Томск", ["оптовая компания"], "нужны только b2b компании",
        excluded_segments=["КФХ", "розничный магазин"],
    )
    assert "ЖЁСТКИЕ ИСКЛЮЧЕНИЯ ПОЛЬЗОВАТЕЛЯ: КФХ, розничный магазин" in captured["prompt"]
    assert "ДАЖЕ если его тип есть в целевых сегментах" in captured["prompt"]


def test_ai_filter_prompt_has_no_exclusion_block_when_empty(monkeypatch):
    """Без исключений промпт фильтра ПРЕЖНИЙ: ни блока исключений, ни
    ужесточения «подсказка, НЕ гарантия» — вердикты у существующих проектов
    не сдвигаются (major ревью: глобальное ужесточение без изоляции)."""
    captured: dict = {}
    monkeypatch.setattr(
        lf.llm_client, "chat",
        lambda p, **kw: captured.update(prompt=p) or '{"keep": []}',
    )
    lf._ai_filter_batch(
        [{"company": "X"}], "n", "g", ["s"], "промпт", excluded_segments=None,
    )
    assert "ЖЁСТКИЕ ИСКЛЮЧЕНИЯ" not in captured["prompt"]
    assert "подсказка, НЕ гарантия" not in captured["prompt"]
    assert "СОХРАНЯЙ (KEEP): потенциальные покупатели, компании из целевых сегментов." in captured["prompt"]


# ── rule-based фолбэк: Step 0 ────────────────────────────────────────────────

def _c(company, categories=None, snippet=""):
    return {"company": company, "snippet": snippet, "domain": "",
            "categories": categories or []}


def test_rule_based_rejects_excluded_even_if_in_segments():
    """«КФХ» есть и в segments (LLM положил в оба) — исключение главнее."""
    cands = [
        _c("КФХ Русское поле"),
        _c("Оптовая компания Северторг", categories=["оптовая компания"]),
    ]
    kept = lf._rule_based_competitor_filter(
        cands, "нужны только b2b компании", "b2b",
        ["оптовая компания", "КФХ"],
        synthesized_prompt=True,
        excluded_segments=["КФХ", "розничный магазин"],
    )
    names = [c["company"] for c in kept]
    assert "КФХ Русское поле" not in names
    assert "Оптовая компания Северторг" in names


def test_rule_based_multiword_exclusion_not_decomposed():
    """Blocker-сценарий ревью: «услуги для физлиц» раньше давало термы
    «услуги»/«для» и убивало почти всех. Фраза матчится ТОЛЬКО целиком."""
    cands = [
        _c("Дистрибьютор Альфа", snippet="решения для бизнеса и услуги дистрибуции"),
        _c("Оптовая компания Бета", snippet="поставляем в магазины города"),
        _c("Салон Гамма", snippet="услуги для физлиц и населения"),
    ]
    kept = lf._rule_based_competitor_filter(
        cands, "только b2b", "b2b",
        ["дистрибьютор", "оптовая компания", "салон"],
        synthesized_prompt=True,
        excluded_segments=["услуги для физлиц", "розничный магазин"],
    )
    names = [c["company"] for c in kept]
    # легитимные выжили, несмотря на «для»/«услуги»/«магазины» в сниппетах
    assert "Дистрибьютор Альфа" in names
    assert "Оптовая компания Бета" in names
    # а фразовый матч целиком — отбит
    assert "Салон Гамма" not in names


def test_rule_based_short_exclusion_respects_word_boundary():
    """Blocker-сценарий ревью: «НКО» не должно матчить «стаНКОстроительный»."""
    cands = [
        _c("Станкостроительный завод", categories=["станкостроительный завод"]),
        _c("НКО Помощь"),
    ]
    kept = lf._rule_based_competitor_filter(
        cands, "только b2b", "b2b", ["станкостроительный завод"],
        synthesized_prompt=True,
        excluded_segments=["НКО"],
    )
    names = [c["company"] for c in kept]
    assert "Станкостроительный завод" in names
    assert "НКО Помощь" not in names


def test_rule_based_rejects_by_excluded_category():
    cands = [_c("Про паркет", categories=["розничный магазин напольных покрытий"])]
    kept = lf._rule_based_competitor_filter(
        cands, "только b2b", "b2b", ["оптовая компания"],
        synthesized_prompt=True,
        excluded_segments=["розничный магазин"],
    )
    assert kept == []


def test_rule_based_without_exclusions_keeps_segment_match():
    """Без исключений сегментный матч сохраняется — Step 0 ничего не трогает.
    (Сегмент ≥4 символов: короткие типа «КФХ» и раньше не попадали в
    positive-термы — это преднамеренный стоп-слов фильтр, не наш регресс.)"""
    cands = [_c("Фермерское хозяйство Русское поле", categories=["фермерское хозяйство"])]
    kept = lf._rule_based_competitor_filter(
        cands, "корм для ферм", "животноводство", ["фермерское хозяйство"],
        synthesized_prompt=True,
    )
    assert [c["company"] for c in kept] == ["Фермерское хозяйство Русское поле"]


# ── склад: NOT-клаузы ────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
        s.rollback()
        s.execute(delete(Company).where(Company.normalized_name.like(f"{_PFX}%")))
        s.commit()
    finally:
        s.close()


def _wh_cand(company, domain, categories=None):
    return {
        "company": company, "city": "Томск", "domain": domain,
        "website": f"https://{domain}", "email": "", "phone": "+7 999 000-00-00",
        "address": "Томск", "source": "2gis", "score": 40,
        "categories": categories or [],
    }


def test_search_warehouse_excluded_segments_filters_rows(db):
    d_farm = f"{_PFX}{uuid.uuid4().hex[:6]}-farm.ru"
    d_opt = f"{_PFX}{uuid.uuid4().hex[:6]}-opt.ru"
    cw.upsert_companies(
        db,
        [
            _wh_cand(f"{_PFX}КФХ магазин", d_farm),
            _wh_cand(f"{_PFX}Оптовая база", d_opt),
        ],
        niche="торговая компания",
    )
    # без исключений — приходят оба
    all_hits = {h["domain"] for h in cw.search_warehouse(
        db, niche="торговая компания", geography="Томск",
        segments=[f"{_PFX}КФХ магазин", f"{_PFX}Оптовая база"], limit=50,
    )}
    assert {d_farm, d_opt} <= all_hits
    # с исключением «КФХ» — ферма отсечена SQL-ом, оптовик остался
    hits = {h["domain"] for h in cw.search_warehouse(
        db, niche="торговая компания", geography="Томск",
        segments=[f"{_PFX}КФХ магазин", f"{_PFX}Оптовая база"],
        excluded_segments=["КФХ"], limit=50,
    )}
    assert d_farm not in hits
    assert d_opt in hits


def test_search_warehouse_short_exclusion_word_boundary(db):
    """Major-сценарий ревью: NOT-клауза «НКО» не должна резать
    «Станкостроительный завод» substring-ом ('нко' ⊂ 'станко...')."""
    d = f"{_PFX}{uuid.uuid4().hex[:6]}-stanko.ru"
    cw.upsert_companies(
        db, [_wh_cand(f"{_PFX}Станкостроительный завод", d)],
        niche="производственное предприятие",
    )
    hits = {h["domain"] for h in cw.search_warehouse(
        db, niche="производственное предприятие", geography="Томск",
        segments=[f"{_PFX}Станкостроительный завод"],
        excluded_segments=["НКО"], limit=50,
    )}
    assert d in hits


def test_search_warehouse_single_word_exclusion_skips_description(db):
    """Описание упоминает КЛИЕНТОВ компании: оптовик «поставляем в розничные
    магазины» не должен гибнуть от однословного исключения «магазин»."""
    d = f"{_PFX}{uuid.uuid4().hex[:6]}-optbaza.ru"
    cand = _wh_cand(f"{_PFX}Оптовая база Северная", d)
    cand["description"] = "поставляем товары в розничные магазины города"
    cw.upsert_companies(db, [cand], niche="оптовая компания")
    hits = {h["domain"] for h in cw.search_warehouse(
        db, niche="оптовая компания", geography="Томск",
        segments=[f"{_PFX}Оптовая база Северная"],
        excluded_segments=["магазин"], limit=50,
    )}
    assert d in hits


def test_search_warehouse_excluded_matches_categories(db):
    d = f"{_PFX}{uuid.uuid4().hex[:6]}-parquet.ru"
    cw.upsert_companies(
        db,
        [_wh_cand(f"{_PFX}Про паркет", d, categories=["розничный магазин"])],
        niche="торговая компания",
    )
    hits = {h["domain"] for h in cw.search_warehouse(
        db, niche="торговая компания", geography="Томск",
        segments=[f"{_PFX}Про паркет"],
        excluded_segments=["розничный магазин"], limit=50,
    )}
    assert d not in hits

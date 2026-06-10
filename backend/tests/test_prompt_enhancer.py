"""Tests for prompt_enhancer — focus on the post-LLM seller-echo filter
that prevents the LLM from returning product-words as customer segments,
plus the audit fixes: SELL/BUY clause split, natural-form segments,
word-boundary keyword matching, ОКВЭД boundary bugs, source markers,
and extended geography extraction."""
from __future__ import annotations

import pytest

import app.services.prompt_enhancer as pe
from app.services.prompt_enhancer import (
    _extract_geography,
    _extract_prompt_buyer_words,
    _extract_prompt_product_words,
    _name_echoes_product,
    _normalize_segments,
    _okved_from_segments,
    _smart_fallback,
    _strip_product_echoes,
)


@pytest.mark.parametrize(
    "prompt, segments_in, expect_dropped, expect_kept",
    [
        # Classic feed-additives case — competitor echo
        (
            "Продаю кормовые добавки для животных в Томске",
            ["кормовая добавка", "животноводческая ферма", "птицефабрика"],
            ["кормовая добавка"],
            ["животноводческая ферма", "птицефабрика"],
        ),
        # Marble windowsills — both words are product, LLM echo
        (
            "Продаем мраморные подоконники в Москве",
            ["мраморный подоконник", "строительная компания", "застройщик"],
            ["мраморный подоконник"],
            ["строительная компания", "застройщик"],
        ),
        # Accounting services for SMB
        (
            "Оказываем бухгалтерские услуги для малого бизнеса",
            ["бухгалтерская услуга", "малый бизнес", "ип", "ооо"],
            ["бухгалтерская услуга"],
            ["малый бизнес", "ип", "ооо"],
        ),
        # Web dev for B2B — "разработка сайта" is echo
        (
            "Разрабатываем сайты для B2B клиентов",
            ["разработка сайта", "интернет-магазин", "it-компания"],
            ["разработка сайта"],
            ["интернет-магазин", "it-компания"],
        ),
    ],
    ids=["feed_additives", "marble_windowsills", "accounting", "web_dev"],
)
def test_strip_product_echoes_drops_echo_segments(
    prompt: str,
    segments_in: list[str],
    expect_dropped: list[str],
    expect_kept: list[str],
) -> None:
    product_words = _extract_prompt_product_words(prompt)
    kept = _strip_product_echoes(segments_in, product_words)

    for seg in expect_kept:
        assert seg in kept, f"expected to KEEP '{seg}' for prompt '{prompt}'"
    for seg in expect_dropped:
        assert seg not in kept, f"expected to DROP '{seg}' for prompt '{prompt}'"


def test_strip_product_echoes_empty_product_words() -> None:
    """No product words → nothing gets stripped."""
    segments = ["ресторан", "магазин", "отель"]
    result = _strip_product_echoes(segments, [])
    assert result == segments


def test_strip_product_echoes_preserves_order_and_duplicates() -> None:
    """Stable filter — segments stay in input order."""
    segments = ["птицефабрика", "ферма", "агрохолдинг", "зоомагазин"]
    result = _strip_product_echoes(segments, ["wildcard"])  # no echoes
    assert result == segments


# ──────────────────────────────────────────────────────────────────────────
# FIX 1: SELL/BUY clause split — buyers named after «для» are NOT product words
# ──────────────────────────────────────────────────────────────────────────

def test_buyers_after_dlya_are_not_product_words() -> None:
    """«Продаю корм для птицефабрик» — «птицефабрик» is a BUYER, not a product."""
    pw = _extract_prompt_product_words("Продаю корм для птицефабрик")
    assert not any(w.startswith("птицефабрик") for w in pw), pw
    assert any(w.startswith("корм") for w in pw), pw
    bw = _extract_prompt_buyer_words("Продаю корм для птицефабрик")
    assert "птицефабрика" in bw


def test_explicitly_named_buyer_segment_survives_echo_strip() -> None:
    """The user SAID «для птицефабрик» — segment «птицефабрика» must be kept."""
    prompt = "Продаю корм для птицефабрик"
    pw = _extract_prompt_product_words(prompt)
    bw = _extract_prompt_buyer_words(prompt)
    kept = _strip_product_echoes(["птицефабрика", "свиноферма"], pw, bw)
    assert "птицефабрика" in kept
    assert "свиноферма" in kept


def test_cleaning_for_restaurants_keeps_restaurant_and_hotel() -> None:
    prompt = "клининговые услуги для ресторанов и отелей"
    pw = _extract_prompt_product_words(prompt)
    bw = _extract_prompt_buyer_words(prompt)
    assert "ресторан" in bw and "отель" in bw
    kept = _strip_product_echoes(["ресторан", "отель", "бизнес-центр"], pw, bw)
    assert "ресторан" in kept
    assert "отель" in kept


def test_2gis_category_filter_is_word_boundary_not_substring() -> None:
    """Prefix «клини» (from «клининговые») must NOT kill category «клиника»."""
    pw = _extract_prompt_product_words("клининговые услуги для ресторанов и отелей")
    assert not _name_echoes_product("клиника", pw)
    # …but a real competitor category is still filtered
    assert _name_echoes_product("клининговая компания", pw)


def test_cities_in_oblique_cases_not_in_product_words() -> None:
    """«в Казани» / «в Томске» must not leak into product words."""
    pw = _extract_prompt_product_words("Продаем мраморные подоконники в Казани")
    assert not any(w.startswith("казан") for w in pw), pw
    pw2 = _extract_prompt_product_words("Продаю корм в Томске")
    assert not any(w.startswith("томск") for w in pw2), pw2


# ──────────────────────────────────────────────────────────────────────────
# FIX 2: segments are stored in NATURAL form, deduped by lemma key
# ──────────────────────────────────────────────────────────────────────────

def test_normalize_segments_dedupes_and_lemmatizes() -> None:
    """Lemma is only a DEDUP KEY: 'Ресторанам'/'ресторан'/'РЕСТОРАН' collapse
    to one entry, and the stored value is the first NATURAL form."""
    result = _normalize_segments(["Ресторанам", "ресторан", "РЕСТОРАН "])
    assert len(result) == 1, f"expected 1 unique segment, got {result}"
    assert result == ["Ресторанам"]


def test_normalize_segments_keeps_natural_form() -> None:
    """Broken lemmatized Russian («строительный компания») must never be
    stored — it is used verbatim in quoted search queries and shown in UI."""
    result = _normalize_segments(["строительные компании", "строительная компания"])
    assert result == ["строительные компании"]
    assert "строительный компания" not in result


# ──────────────────────────────────────────────────────────────────────────
# FIX 3: _smart_fallback word-boundary keyword matching + HoReCa 2-keyword rule
# ──────────────────────────────────────────────────────────────────────────

def test_wheels_and_tires_do_not_match_timber() -> None:
    """«колеса» must not trigger the timber mapping via substring «леса»."""
    res = _smart_fallback("Продаю колеса и шины оптом")
    assert "дома из бруса" not in res["segments"]
    assert "мебельная фабрика" not in res["segments"]
    assert res["niche"] != "строительство, мебель, дачное домостроение"


def test_bruschatka_does_not_match_brus() -> None:
    """«брусчатка» STARTS with «брус» — full-word check required."""
    res = _smart_fallback("Производим брусчатку в Москве")
    assert "дома из бруса" not in res["segments"]
    assert res["geography"] == "Москва"


def test_brus_houses_still_match_timber() -> None:
    """Genuine «брус» (lemma of «бруса») still triggers the timber mapping."""
    res = _smart_fallback("Продаю дома из бруса")
    assert res["source"] == "fallback"
    assert res["niche"] == "строительство, мебель, дачное домостроение"


def test_horeca_requires_equipment_and_venue_words() -> None:
    """HoReCa branch needs BOTH an equipment word AND a venue word."""
    # equipment + venue → fires
    res = _smart_fallback("Продаю оборудование для ресторанов и кафе")
    assert res["source"] == "fallback"
    assert res["niche"] == "рестораны, кафе, столовые, отели"
    # venue only → must NOT fire HoReCa equipment mapping
    res2 = _smart_fallback("посуда и инвентарь для ресторанов")
    assert res2["niche"] != "рестораны, кафе, столовые, отели"
    # equipment only → falls to industrial, not HoReCa
    res3 = _smart_fallback("Продаю промышленное оборудование")
    assert res3["niche"] == "производственные предприятия, заводы, фабрики"


# ──────────────────────────────────────────────────────────────────────────
# FIX 4: ОКВЭД word-boundary keys («сто», «банк», «тц»/«бц»)
# ──────────────────────────────────────────────────────────────────────────

def test_stolovaya_is_not_auto_repair() -> None:
    out = _okved_from_segments(["столовая"])
    codes = {e["code"] for e in out}
    assert "45.20" not in codes, out
    assert "56.10" in codes


def test_stomatology_is_not_auto_repair() -> None:
    out = _okved_from_segments(["стоматология"])
    codes = {e["code"] for e in out}
    assert "45.20" not in codes, out
    assert codes & {"86.10", "86.22"}


def test_banquet_hall_is_not_a_bank() -> None:
    out = _okved_from_segments(["банкетный зал"])
    assert "64.19" not in {e["code"] for e in out}, out


def test_sto_and_bank_still_match_as_whole_words() -> None:
    assert "45.20" in {e["code"] for e in _okved_from_segments(["сто", "автосервис"])}
    assert "64.19" in {e["code"] for e in _okved_from_segments(["банк"])}


# ──────────────────────────────────────────────────────────────────────────
# FIX 5: source marker + generic fallback must not echo raw prompt
# ──────────────────────────────────────────────────────────────────────────

def test_fallback_paths_set_source() -> None:
    assert _smart_fallback("Продаю корм для птицефабрик")["source"] == "fallback"
    assert _smart_fallback("Туманное нечто непонятное")["source"] == "fallback_generic"


def test_generic_fallback_does_not_echo_raw_prompt() -> None:
    """The user's PRODUCT text must not become niche/search_queries_niche —
    searching by it finds competitors, not customers."""
    raw = "Туманное нечто непонятное"
    res = _smart_fallback(raw)
    assert res["niche"] == ""
    assert res["search_queries_niche"] == ""
    # explicitly named buyers ARE a valid neutral niche
    res2 = _smart_fallback("посуда и инвентарь для ресторанов")
    assert res2["source"] == "fallback_generic"
    assert "ресторан" in res2["niche"]
    assert "посуда" not in res2["search_queries_niche"]


def test_enhance_prompt_marks_llm_source(monkeypatch) -> None:
    monkeypatch.setattr(pe.llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        pe, "_try_llm_enhance",
        lambda raw_prompt, organization_id=None: {
            "niche": "птицеводство",
            "geography": "Томск",
            "segments": ["птицефабрика"],
            "project_name": "Корм для птицефабрик",
            "okved_codes": [],
        },
    )
    monkeypatch.setattr(pe, "_augment_with_2gis_categories", lambda s, g, p: s)
    res = pe.enhance_prompt("Продаю корм для птицефабрик в Томске")
    assert res["source"] == "llm"


def test_enhance_prompt_marks_fallback_source(monkeypatch) -> None:
    monkeypatch.setattr(pe.llm_client, "is_configured", lambda: False)
    monkeypatch.setattr(pe, "_augment_with_2gis_categories", lambda s, g, p: s)
    res = pe.enhance_prompt("Продаю корм для птицефабрик в Томске")
    assert res["source"] == "fallback"


# ──────────────────────────────────────────────────────────────────────────
# FIX 6: geography — extended city list + two-sided pymorphy normalization
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, city",
    [
        ("в ставрополе", "Ставрополь"),
        ("в севастополе", "Севастополь"),
        ("в грозном", "Грозный"),
        ("в набережных челнах", "Набережные Челны"),
        ("в казани", "Казань"),
        ("в санкт-петербурге", "Санкт-Петербург"),
        ("в томске", "Томск"),
        ("в улан-удэ", "Улан-Удэ"),
        ("работаем по всей россии", "Россия"),
        ("томской области", "Томск"),
    ],
)
def test_extract_geography(text: str, city: str) -> None:
    assert _extract_geography(text) == city


def test_extract_geography_no_false_positive_from_product_words() -> None:
    """«оборудование для шахт» — mining gear, not the city Шахты."""
    assert _extract_geography("оборудование для шахт") == "Россия"

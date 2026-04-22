"""Tests for prompt_enhancer — focus on the post-LLM seller-echo filter
that prevents the LLM from returning product-words as customer segments."""
from __future__ import annotations

import pytest

from app.services.prompt_enhancer import (
    _extract_prompt_product_words,
    _strip_product_echoes,
    _normalize_segments,
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


def test_normalize_segments_dedupes_and_lemmatizes() -> None:
    """Make sure segments like 'Ресторанам' and 'ресторан' dedupe to one entry."""
    result = _normalize_segments(["Ресторанам", "ресторан", "РЕСТОРАН "])
    assert len(result) == 1, f"expected 1 unique segment, got {result}"

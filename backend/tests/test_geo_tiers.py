"""Tests for the geographic fallback ladder used by lead collection.

When a city-scoped search returns too few candidates we step out to the
region, then to country-wide. _geo_tiers returns the ladder; the actual
cascade is wired into search_leads (later wave).
"""
from __future__ import annotations

import pytest

from app.services.lead_collection import _geo_tiers


@pytest.mark.parametrize(
    "geo, expected",
    [
        ("Томск", ["Томск", "Томская область", "Россия"]),
        ("томск", ["томск", "Томская область", "Россия"]),
        ("Москва", ["Москва", "Московская область", "Россия"]),
        ("Санкт-Петербург", ["Санкт-Петербург", "Ленинградская область", "Россия"]),
        ("СПб", ["СПб", "Ленинградская область", "Россия"]),
        ("Екатеринбург", ["Екатеринбург", "Свердловская область", "Россия"]),
        ("Россия", ["Россия"]),
        ("россия", ["Россия"]),
        ("", [""]),
        ("   ", [""]),
    ],
)
def test_known_city_expands(geo: str, expected: list[str]) -> None:
    assert _geo_tiers(geo) == expected


def test_unknown_city_falls_through_to_russia() -> None:
    """Cities not in the table still get a Russia fallback."""
    tiers = _geo_tiers("Урюпинск")
    assert tiers[0] == "Урюпинск"
    assert tiers[-1] == "Россия"
    # No region tier available — should be just 2 entries.
    assert len(tiers) == 2


def test_strips_whitespace() -> None:
    assert _geo_tiers("  Томск  ") == ["Томск", "Томская область", "Россия"]

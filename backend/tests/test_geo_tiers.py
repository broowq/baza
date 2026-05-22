"""Tests for the geographic fallback ladder used by lead collection.

When a city-scoped search returns too few candidates we step out to the
region, then to country-wide. _geo_tiers returns the ladder; the actual
cascade is wired into search_leads (later wave).
"""
from __future__ import annotations

import pytest

from app.services.lead_collection import _geo_tiers, _maps_geo_targets, _MAJOR_RU_CITIES


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


# ── _maps_geo_targets: city fan-out for nationwide searches ──────────────

@pytest.mark.parametrize("geo", ["Россия", "россия", "РФ", "", "  ", "вся Россия"])
def test_nationwide_geo_fans_out_to_cities(geo: str) -> None:
    """A nationwide setting must expand to the major-cities list, because
    2GIS/Yandex Maps return nothing for a whole-country query."""
    targets = _maps_geo_targets(geo)
    assert targets == _MAJOR_RU_CITIES
    assert "Москва" in targets and "Санкт-Петербург" in targets
    assert len(targets) >= 10


@pytest.mark.parametrize("geo", ["Москва", "Томск", "Екатеринбург"])
def test_specific_city_is_passthrough(geo: str) -> None:
    """A concrete city queries only that city — no fan-out."""
    assert _maps_geo_targets(geo) == [geo]

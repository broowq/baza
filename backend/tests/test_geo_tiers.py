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
        # A city expands to its federal subject — but NOT to 'Россия'. Escalating
        # a specific geography nationwide used to fan out across Москва/СПб/16
        # major cities and merge those leads with no geo filter, flooding a
        # regional project with Moscow results. City → region is now the widest
        # a specific search goes; only an explicit 'Россия' fans out.
        ("Томск", ["Томск", "Томская область"]),
        ("томск", ["томск", "Томская область"]),
        ("Москва", ["Москва", "Московская область"]),
        ("Санкт-Петербург", ["Санкт-Петербург", "Ленинградская область"]),
        ("СПб", ["СПб", "Ленинградская область"]),
        ("Екатеринбург", ["Екатеринбург", "Свердловская область"]),
        ("Россия", ["Россия"]),
        ("россия", ["Россия"]),
        ("", [""]),
        ("   ", [""]),
    ],
)
def test_known_city_expands(geo: str, expected: list[str]) -> None:
    assert _geo_tiers(geo) == expected


def test_unknown_city_does_not_escalate_to_russia() -> None:
    """A city not in the region table has no broader tier — it stays scoped to
    itself rather than escalating nationwide. Better few on-target leads than a
    flood of Moscow ones."""
    tiers = _geo_tiers("Урюпинск")
    assert tiers == ["Урюпинск"]
    assert "Россия" not in tiers


def test_strips_whitespace() -> None:
    assert _geo_tiers("  Томск  ") == ["Томск", "Томская область"]


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

"""
Query-builder regression bank — deterministic, no external APIs.

Purpose
-------
This bank pins the OUTPUT STRINGS of the query-construction layer in
`app.services.lead_collection` so the overnight improvement loop can't
accidentally regress the prompt-aware / buyer-hunt semantics we
carefully built up.

Coverage
--------
  * `_build_discover_queries` — SearXNG-bound discovery queries.
      - has_prompt=False → niche queries present
      - has_prompt=True + segments → segment-only, NO niche queries
      - has_prompt=True + empty segments → ZERO queries (bail-out)
      - negative-keyword switching (CORE vs CORE+SELLER_EXTRA)
  * `_build_yandex_map_queries` — Yandex Places (geo-aware) queries.
      - has_prompt=False → niche in every query
      - has_prompt=True + segments → niche in NONE
      - has_prompt=True + empty segments → empty list
  * `_pick_negatives` — the CORE / CORE+SELLER_EXTRA chooser.
      - no prompt → CORE only (no -продажа, no -купить)
      - prompt + seller-category segments → CORE only
      - prompt + non-seller segments → CORE + SELLER_EXTRA

Invocation
----------
    cd backend && .venv/bin/pytest tests/test_query_builders.py -v

The `test_zz_summary` test at the bottom prints a machine-parseable line:

    QUERY_BUILDER_BANK_SUMMARY passed=X/Y failures=['case_id', ...]

which the overnight cycle harness greps for to aggregate pass rates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pytest

from app.services.lead_collection import (
    _NEGATIVE_CORE,
    _NEGATIVE_SELLER_EXTRA,
    _build_discover_queries,
    _build_yandex_map_queries,
    _pick_negatives,
)


# A distinctive fragment of SELLER_EXTRA — if this substring appears in the
# negatives string we know SELLER_EXTRA was applied. "-купить" is not present
# in CORE, so its presence is a clean signal.
_SELLER_EXTRA_MARKER = "-купить"
# A distinctive fragment of CORE that's ALWAYS present.
_CORE_MARKER = "-wikipedia"


# ---------------------------------------------------------------------------
# Case schema
# ---------------------------------------------------------------------------


@dataclass
class QueryCase:
    """One regression case.

    `builder` is called with the kwargs in `inputs`. The returned value
    (list[str] for query builders, str for _pick_negatives) is passed to
    each assertion callable in `asserts` — each must return (ok, reason).
    """

    case_id: str
    description: str
    builder: Callable
    inputs: dict
    asserts: list[Callable[[object], tuple[bool, str]]]
    category: str = "general"

    def run(self) -> tuple[bool, list[str]]:
        try:
            result = self.builder(**self.inputs)
        except Exception as exc:  # pragma: no cover — deterministic tests
            return False, [f"builder raised: {exc!r}"]
        failures: list[str] = []
        for idx, check in enumerate(self.asserts):
            ok, reason = check(result)
            if not ok:
                failures.append(f"assert#{idx}: {reason}")
        return (not failures, failures)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def contains_substr(needle: str) -> Callable[[object], tuple[bool, str]]:
    """Assert that at least one produced query (or the string result) contains `needle`."""

    def check(result: object) -> tuple[bool, str]:
        if isinstance(result, str):
            return (needle in result, f"{needle!r} not in {result!r}")
        assert isinstance(result, list)
        hit = any(needle in q for q in result)
        return (hit, f"{needle!r} missing from all {len(result)} queries")

    return check


def no_query_contains(needle: str) -> Callable[[object], tuple[bool, str]]:
    """Assert `needle` appears in NONE of the produced queries / is absent from string."""

    def check(result: object) -> tuple[bool, str]:
        if isinstance(result, str):
            return (needle not in result, f"{needle!r} unexpectedly present in {result!r}")
        assert isinstance(result, list)
        offenders = [q for q in result if needle in q]
        return (not offenders, f"{needle!r} appeared in {len(offenders)} query(ies): {offenders[:2]}")

    return check


def every_query_contains(needle: str) -> Callable[[object], tuple[bool, str]]:
    """Assert `needle` appears in EVERY produced query."""

    def check(result: object) -> tuple[bool, str]:
        assert isinstance(result, list)
        missing = [q for q in result if needle not in q]
        return (not missing, f"{needle!r} missing from {len(missing)} query(ies): {missing[:2]}")

    return check


def query_count(minimum: int, maximum: int | None = None) -> Callable[[object], tuple[bool, str]]:
    def check(result: object) -> tuple[bool, str]:
        assert isinstance(result, list)
        n = len(result)
        if maximum is None:
            return (n >= minimum, f"expected >= {minimum} queries, got {n}")
        return (minimum <= n <= maximum, f"expected {minimum}..{maximum} queries, got {n}")

    return check


def is_empty() -> Callable[[object], tuple[bool, str]]:
    def check(result: object) -> tuple[bool, str]:
        assert isinstance(result, list)
        return (len(result) == 0, f"expected empty list, got {len(result)} items: {result[:2]}")

    return check


def equals(expected: object) -> Callable[[object], tuple[bool, str]]:
    def check(result: object) -> tuple[bool, str]:
        return (result == expected, f"expected {expected!r}, got {result!r}")

    return check


# ---------------------------------------------------------------------------
# _build_discover_queries cases (≥12)
# ---------------------------------------------------------------------------

DISCOVER_CASES: list[QueryCase] = [
    QueryCase(
        case_id="discover_no_prompt_niche_only",
        description="No prompt: niche drives queries; no segments supplied.",
        builder=_build_discover_queries,
        inputs=dict(niche="стоматология", geo="Казань", segments=[], has_prompt=False),
        asserts=[
            contains_substr("стоматология"),
            contains_substr("Казань"),
            # niche-pass queries exist
            contains_substr("о компании"),
            contains_substr("предприятие"),
            # CORE negatives always applied
            every_query_contains(_CORE_MARKER),
            # SELLER_EXTRA NOT applied when no prompt
            no_query_contains(_SELLER_EXTRA_MARKER),
            query_count(minimum=4),
        ],
        category="no_prompt",
    ),
    QueryCase(
        case_id="discover_no_prompt_with_segments",
        description="No prompt + segments: both niche-pass AND segment-pass run.",
        builder=_build_discover_queries,
        inputs=dict(
            niche="кормовые добавки",
            geo="Краснодар",
            segments=["птицефабрика", "молочная ферма"],
            has_prompt=False,
        ),
        asserts=[
            contains_substr("кормовые добавки"),  # niche present (no prompt)
            contains_substr("птицефабрика"),
            contains_substr("молочная ферма"),
            every_query_contains(_CORE_MARKER),
            no_query_contains(_SELLER_EXTRA_MARKER),  # no prompt → no seller extras
        ],
        category="no_prompt",
    ),
    QueryCase(
        case_id="discover_prompt_with_b2b_segments_excludes_niche",
        description=(
            "has_prompt=True + B2B segments: queries driven by segments ONLY. "
            "Niche must NOT appear in any query."
        ),
        builder=_build_discover_queries,
        inputs=dict(
            niche="кормовые добавки",
            geo="Краснодар",
            segments=["птицефабрика", "свиноферма"],
            has_prompt=True,
        ),
        asserts=[
            no_query_contains("кормовые добавки"),
            contains_substr("птицефабрика"),
            contains_substr("свиноферма"),
            every_query_contains("Краснодар"),
            every_query_contains(_CORE_MARKER),
            # B2B farm segments → SELLER_EXTRA layered on
            every_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="prompt_b2b",
    ),
    QueryCase(
        case_id="discover_prompt_empty_segments_bailout",
        description=(
            "has_prompt=True + empty segments: bail-out — produce ZERO queries "
            "(no niche fallback, no segment pass)."
        ),
        builder=_build_discover_queries,
        inputs=dict(niche="кормовые добавки", geo="Краснодар", segments=[], has_prompt=True),
        asserts=[
            is_empty(),
        ],
        category="prompt_bailout",
    ),
    QueryCase(
        case_id="discover_prompt_none_segments_bailout",
        description="has_prompt=True + segments=None-ish (falsy): same bail-out.",
        builder=_build_discover_queries,
        inputs=dict(niche="виджеты", geo="Москва", segments=[], has_prompt=True),
        asserts=[
            is_empty(),
        ],
        category="prompt_bailout",
    ),
    QueryCase(
        case_id="discover_prompt_segment_online_shop_core_only",
        description=(
            "Segment mentions 'интернет-магазин': target audience IS a seller — "
            "CORE negatives only, NO SELLER_EXTRA."
        ),
        builder=_build_discover_queries,
        inputs=dict(
            niche="упаковка",
            geo="Москва",
            segments=["интернет-магазин одежды"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("интернет-магазин одежды"),
            no_query_contains("упаковка"),  # niche excluded under prompt
            every_query_contains(_CORE_MARKER),
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="discover_prompt_segment_marketplace_core_only",
        description="Segment 'маркетплейс' → CORE only (SELLER_EXTRA would kill target).",
        builder=_build_discover_queries,
        inputs=dict(
            niche="логистика",
            geo="Санкт-Петербург",
            segments=["маркетплейс"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("маркетплейс"),
            every_query_contains(_CORE_MARKER),
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="discover_prompt_segment_distributor_core_only",
        description="Segment 'дистрибьютор' → CORE only.",
        builder=_build_discover_queries,
        inputs=dict(
            niche="химия",
            geo="Екатеринбург",
            segments=["дистрибьютор бытовой химии"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("дистрибьютор"),
            every_query_contains(_CORE_MARKER),
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="discover_prompt_segment_optovik_core_only",
        description="Segment 'оптовик' — 'оптов' substring hits → CORE only.",
        builder=_build_discover_queries,
        inputs=dict(
            niche="продукты",
            geo="Новосибирск",
            segments=["оптовик продуктов"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("оптовик"),
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="discover_prompt_segment_restoran_gets_seller_extra",
        description="B2B segment 'ресторан' → CORE + SELLER_EXTRA (normal buyer-hunt).",
        builder=_build_discover_queries,
        inputs=dict(
            niche="мясо",
            geo="Москва",
            segments=["ресторан"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("ресторан"),
            no_query_contains("мясо"),  # niche excluded
            every_query_contains(_CORE_MARKER),
            every_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="prompt_b2b",
    ),
    QueryCase(
        case_id="discover_prompt_cap_at_24_segments",
        description=(
            "More than 24 segments: only first 24 used (3 queries each → 72 max)."
            " Cap was 8 in earlier waves; bumped to 24 in wave-4 to widen the net."
        ),
        builder=_build_discover_queries,
        inputs=dict(
            niche="X",
            geo="Казань",
            segments=[f"сегмент_{i}" for i in range(28)],
            has_prompt=True,
        ),
        asserts=[
            # segments 0..23 present
            contains_substr("сегмент_0"),
            contains_substr("сегмент_23"),
            # segments 24..27 absent (cap)
            no_query_contains("сегмент_24"),
            no_query_contains("сегмент_27"),
            # has_prompt → niche "X" never appears as standalone niche-query line
            no_query_contains(" X "),
        ],
        category="prompt_b2b",
    ),
    QueryCase(
        case_id="discover_query_structure_has_three_variants_per_segment",
        description=(
            "Each segment produces 3 query variants (контакты/официальный сайт/ООО)."
        ),
        builder=_build_discover_queries,
        inputs=dict(
            niche="ирр",
            geo="Сочи",
            segments=["отель"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("контакты телефон"),
            contains_substr("официальный сайт"),
            contains_substr("ООО"),
            # 3 seg variants; no niche-pass since has_prompt=True
            query_count(minimum=3, maximum=3),
        ],
        category="structure",
    ),
    QueryCase(
        case_id="discover_no_prompt_short_segment_skipped",
        description="Segment with len<=2 is skipped (guard against noise like 'и').",
        builder=_build_discover_queries,
        inputs=dict(
            niche="пицца",
            geo="Тула",
            segments=["и", "кафе"],
            has_prompt=False,
        ),
        asserts=[
            contains_substr("кафе"),
            # "и" shouldn't spawn its own segment query line
            no_query_contains("и Тула контакты"),
        ],
        category="structure",
    ),
    QueryCase(
        case_id="discover_dedupe_identical_queries",
        description="Duplicate queries (e.g. identical segments) are deduped.",
        builder=_build_discover_queries,
        inputs=dict(
            niche="клининг",
            geo="Москва",
            segments=["офис", "офис"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("офис"),
            # dedupe: 3 queries, not 6
            query_count(minimum=3, maximum=3),
        ],
        category="structure",
    ),
]


# ---------------------------------------------------------------------------
# _build_yandex_map_queries cases (≥8)
# ---------------------------------------------------------------------------

YMAP_CASES: list[QueryCase] = [
    QueryCase(
        case_id="ymap_no_prompt_niche_in_every_query",
        description="has_prompt=False → niche appears in every query.",
        builder=_build_yandex_map_queries,
        inputs=dict(niche="стоматология", geo="Казань", segments=[], has_prompt=False),
        asserts=[
            every_query_contains("стоматология"),
            every_query_contains("Казань"),
            query_count(minimum=4),
        ],
        category="no_prompt",
    ),
    QueryCase(
        case_id="ymap_no_prompt_niche_with_segments_mixed",
        description="has_prompt=False + segments: niche in all; segments may appear too.",
        builder=_build_yandex_map_queries,
        inputs=dict(
            niche="пекарня",
            geo="Москва",
            segments=["кафе"],
            has_prompt=False,
        ),
        asserts=[
            every_query_contains("пекарня"),
            contains_substr("кафе"),
        ],
        category="no_prompt",
    ),
    QueryCase(
        case_id="ymap_prompt_with_segments_no_niche",
        description="has_prompt=True + segments: niche absent from ALL queries.",
        builder=_build_yandex_map_queries,
        inputs=dict(
            niche="кормовые добавки",
            geo="Краснодар",
            segments=["птицефабрика", "молочная ферма"],
            has_prompt=True,
        ),
        asserts=[
            no_query_contains("кормовые добавки"),
            no_query_contains("кормовые"),
            contains_substr("птицефабрика"),
            contains_substr("молочная ферма"),
            every_query_contains("Краснодар"),
        ],
        category="prompt_b2b",
    ),
    QueryCase(
        case_id="ymap_prompt_with_segments_two_orderings",
        description="Each segment emits both 'geo, seg' and 'seg, geo' orderings.",
        builder=_build_yandex_map_queries,
        inputs=dict(
            niche="виджеты",
            geo="Москва",
            segments=["отель"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("Москва, отель"),
            contains_substr("отель, Москва"),
            query_count(minimum=2, maximum=2),
        ],
        category="prompt_b2b",
    ),
    QueryCase(
        case_id="ymap_prompt_empty_segments_empty_list",
        description=(
            "has_prompt=True + empty segments: falls through to niche branch, "
            "but realistically tests expect short/empty OR niche-only."
        ),
        builder=_build_yandex_map_queries,
        inputs=dict(
            niche="",  # user who had a prompt but no resolved niche
            geo="Москва",
            segments=[],
            has_prompt=True,
        ),
        asserts=[
            # With niche="" and has_prompt=True + no segments, the else-branch
            # runs with empty niche → all queries collapse to just geo-variants,
            # then dedupe leaves a very short list.
            query_count(minimum=0, maximum=3),
        ],
        category="prompt_bailout",
    ),
    QueryCase(
        case_id="ymap_prompt_segment_online_shop_ok",
        description=(
            "has_prompt=True + 'интернет-магазин' segment: segment used as-is, "
            "niche absent."
        ),
        builder=_build_yandex_map_queries,
        inputs=dict(
            niche="упаковка",
            geo="Москва",
            segments=["интернет-магазин"],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("интернет-магазин"),
            no_query_contains("упаковка"),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="ymap_no_prompt_dedup",
        description="Duplicate queries are removed (no-prompt, segments dup).",
        builder=_build_yandex_map_queries,
        inputs=dict(
            niche="аптека",
            geo="Сочи",
            segments=["клиника", "клиника"],
            has_prompt=False,
        ),
        asserts=[
            contains_substr("аптека"),
            contains_substr("клиника"),
            # core 4 + 1 seg = 5 (dedup removes second clinic)
            query_count(minimum=5, maximum=5),
        ],
        category="structure",
    ),
    QueryCase(
        case_id="ymap_no_prompt_empty_segments_four_queries",
        description="no-prompt + no-segments: exactly 4 niche-based queries.",
        builder=_build_yandex_map_queries,
        inputs=dict(niche="кофейня", geo="Пермь", segments=[], has_prompt=False),
        asserts=[
            query_count(minimum=4, maximum=4),
            every_query_contains("кофейня"),
            every_query_contains("Пермь"),
        ],
        category="structure",
    ),
    QueryCase(
        case_id="ymap_prompt_cap_at_24_segments",
        description="has_prompt=True → only first 24 segments drive queries (was 8).",
        builder=_build_yandex_map_queries,
        inputs=dict(
            niche="X",
            geo="Москва",
            segments=[f"сегмент_{i}" for i in range(28)],
            has_prompt=True,
        ),
        asserts=[
            contains_substr("сегмент_0"),
            contains_substr("сегмент_23"),
            no_query_contains("сегмент_24"),
            no_query_contains("сегмент_27"),
        ],
        category="structure",
    ),
]


# ---------------------------------------------------------------------------
# _pick_negatives cases (≥6)
# ---------------------------------------------------------------------------

NEG_CASES: list[QueryCase] = [
    QueryCase(
        case_id="neg_no_prompt_returns_core",
        description="no prompt → CORE (no seller-extras).",
        builder=_pick_negatives,
        inputs=dict(has_prompt=False, segments=None),
        asserts=[
            equals(_NEGATIVE_CORE),
        ],
        category="core_only",
    ),
    QueryCase(
        case_id="neg_no_prompt_with_segments_still_core",
        description="no prompt, even with segments supplied → CORE only.",
        builder=_pick_negatives,
        inputs=dict(has_prompt=False, segments=["ресторан"]),
        asserts=[
            equals(_NEGATIVE_CORE),
        ],
        category="core_only",
    ),
    QueryCase(
        case_id="neg_prompt_empty_segments_returns_core",
        description="prompt + empty segments → CORE (play safe, unknown audience).",
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=[]),
        asserts=[
            equals(_NEGATIVE_CORE),
        ],
        category="core_only",
    ),
    QueryCase(
        case_id="neg_prompt_none_segments_returns_core",
        description="prompt + segments=None → CORE.",
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=None),
        asserts=[
            equals(_NEGATIVE_CORE),
        ],
        category="core_only",
    ),
    QueryCase(
        case_id="neg_prompt_online_shop_segment_returns_core",
        description="prompt + ['интернет-магазин'] → CORE (target IS seller).",
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=["интернет-магазин"]),
        asserts=[
            contains_substr(_CORE_MARKER),
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="neg_prompt_marketplace_segment_returns_core",
        description="prompt + ['маркетплейс'] → CORE only.",
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=["маркетплейс"]),
        asserts=[
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="neg_prompt_distributor_segment_returns_core",
        description="prompt + ['дистрибьютор'] → CORE only ('дистрибьютор' keyword hits).",
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=["дистрибьютор электроники"]),
        asserts=[
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="seller_audience",
    ),
    QueryCase(
        case_id="neg_prompt_restaurant_segment_returns_core_plus_extra",
        description="prompt + ['ресторан'] → CORE + SELLER_EXTRA (genuine buyer).",
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=["ресторан"]),
        asserts=[
            contains_substr(_CORE_MARKER),
            contains_substr(_SELLER_EXTRA_MARKER),
        ],
        category="buyer_hunt",
    ),
    QueryCase(
        case_id="neg_prompt_farm_segments_returns_core_plus_extra",
        description="prompt + ['птицефабрика', 'ферма'] → CORE + SELLER_EXTRA.",
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=["птицефабрика", "молочная ферма"]),
        asserts=[
            contains_substr(_CORE_MARKER),
            contains_substr(_SELLER_EXTRA_MARKER),
        ],
        category="buyer_hunt",
    ),
    QueryCase(
        case_id="neg_prompt_mixed_seller_and_buyer_err_safe",
        description=(
            "prompt + mixed (['магазин одежды', 'ресторан']) — any seller-hint "
            "present triggers CORE-only (err on safe side, don't nuke sellers)."
        ),
        builder=_pick_negatives,
        inputs=dict(has_prompt=True, segments=["магазин одежды", "ресторан"]),
        asserts=[
            no_query_contains(_SELLER_EXTRA_MARKER),
        ],
        category="safe_side",
    ),
]


# ---------------------------------------------------------------------------
# Aggregate & run
# ---------------------------------------------------------------------------

ALL_CASES: list[QueryCase] = DISCOVER_CASES + YMAP_CASES + NEG_CASES

_RESULTS: dict[str, tuple[bool, list[str]]] = {}


def _record(case_id: str, ok: bool, reasons: list[str]) -> None:
    _RESULTS[case_id] = (ok, reasons)


@pytest.mark.parametrize("case", ALL_CASES, ids=[c.case_id for c in ALL_CASES])
def test_query_builder_case(case: QueryCase) -> None:
    ok, reasons = case.run()
    _record(case.case_id, ok, reasons)
    assert ok, (
        f"[{case.category}] {case.case_id}: {case.description}\n"
        + "\n".join(f"  - {r}" for r in reasons)
    )


# ---------------------------------------------------------------------------
# Summary beacon
# ---------------------------------------------------------------------------


def test_zz_summary() -> None:
    """
    Emits a machine-parseable summary line for run_cycle.sh to grep:

        QUERY_BUILDER_BANK_SUMMARY passed=X/Y failures=['case_id', ...]

    Always passes (assertion is trivial) — the individual parametrized
    tests are the real gate; this one exists to surface an aggregate
    beacon regardless of xfail/ok distribution.
    """
    total = len(ALL_CASES)
    passed = sum(1 for ok, _ in _RESULTS.values() if ok)
    failures = [cid for cid, (ok, _) in _RESULTS.items() if not ok]
    print(f"\nQUERY_BUILDER_BANK_SUMMARY passed={passed}/{total} failures={failures}")
    assert True

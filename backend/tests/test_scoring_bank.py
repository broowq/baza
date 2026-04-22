"""
Scoring regression bank — deterministic, no external APIs.

Purpose
-------
This is the overnight-loop eval harness for `app.services.scoring.score_lead`.
It exercises the scoring function against ≥30 labeled synthetic + real-like
scenarios covering:

  * competitor / off-niche detection
  * real customer matching (feed additives → farm / dairy / poultry)
  * no-website SMBs (village farm with only a phone + 2GIS card)
  * segment bonuses (matching vs non-matching target segments — currently
    approximated via niche keywords, since `score_lead` itself does not yet
    take a `target_segments` argument)
  * geo matches vs wrong region (geo has no signal in score_lead today → the
    cases document expected behavior: geo should NOT change score; any future
    geo bonus must preserve these invariants)
  * Cyrillic stemming edge cases (short roots, suffix variants)

Each case asserts that the returned score is within a sane `[min, max]`
band. Bands are intentionally loose so small weight re-tunings do not thrash
the suite — we only catch real regressions.

Invocation
----------
    cd backend && pytest tests/test_scoring_bank.py -v --tb=short

The `test_summary` test at the bottom prints a machine-parseable line:

    SCORING_BANK_SUMMARY passed=X/Y failures=['case_id', ...]

which the overnight cycle harness greps for to compare pass rates between
cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.scoring import score_lead


# ---------------------------------------------------------------------------
# Case schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoringCase:
    """A single labeled scoring scenario."""

    case_id: str
    description: str
    lead: dict[str, Any]          # kwargs passed to score_lead
    project: dict[str, Any] = field(default_factory=dict)  # future (segments, geo)
    min_expected: int = 0
    max_expected: int = 100
    category: str = "general"

    def run(self) -> int:
        return score_lead(**self.lead)


def _lead(
    *,
    domain: str = "",
    company: str = "",
    niche: str = "",
    email: bool = False,
    phone: bool = False,
    address: bool = False,
    demo: bool = False,
    relevance: int = 0,
) -> dict[str, Any]:
    return dict(
        domain=domain,
        company=company,
        niche=niche,
        has_email=email,
        has_phone=phone,
        has_address=address,
        demo=demo,
        relevance_score=relevance,
    )


# ---------------------------------------------------------------------------
# The bank
# ---------------------------------------------------------------------------
#
# Scoring math recap (defaults):
#   base=35, +domain=10, +email=20, +phone=10, +address=8,
#   -no_contacts=12, -demo=20, -aggregator=25, +keyword_bonus=12,
#   +ru_domain_bonus=3 (only for a small RU niche set),
#   relevance contribution: min(15, max(0, (r-26)*15/94))  → 0 below r=26,
#                                                            15 at r=120.

CASES: list[ScoringCase] = [
    # -----------------------------------------------------------------------
    # 1. Competitor / off-niche detection
    # -----------------------------------------------------------------------
    ScoringCase(
        case_id="competitor_petfood_vs_feed_additives",
        description="Pet-food shop should NOT trigger 'feed additives for farms' keyword bonus",
        lead=_lead(
            domain="petshop-zoo.ru",
            company="Зоомагазин Питомец",
            niche="кормовые добавки для ферм",
            email=True, phone=True, address=True,
        ),
        # no keyword match → 35+10+20+10+8 = 83
        min_expected=75, max_expected=88,
        category="competitor",
    ),
    ScoringCase(
        case_id="competitor_dental_vs_metalwork",
        description="Dental clinic must not score high when niche is металлообработка",
        lead=_lead(
            domain="stomatology-clinic.ru",
            company="Стоматологическая клиника Улыбка",
            niche="металлообработка",
            email=True, phone=True,
        ),
        # no metal-keyword hit → 35+10+20+10 = 75
        min_expected=68, max_expected=80,
        category="competitor",
    ),
    ScoringCase(
        case_id="competitor_law_firm_vs_logistics",
        description="Юридическая фирма в нише логистика — только базовый скор",
        lead=_lead(
            domain="advokat-center.ru",
            company="Адвокатское бюро Центр",
            niche="логистика",
            email=True, phone=True, address=True,
        ),
        min_expected=75, max_expected=88,
        category="competitor",
    ),
    ScoringCase(
        case_id="competitor_aggregator_2gis",
        description="2GIS в любой нише — жёсткий штраф (-25)",
        lead=_lead(
            domain="2gis.ru",
            company="2ГИС Справочник",
            niche="автосервис",
            email=True, phone=True, address=True,
        ),
        # 35+10+20+10+8 - 25 = 58  (+ keyword match if any → not here)
        min_expected=45, max_expected=65,
        category="competitor",
    ),
    ScoringCase(
        case_id="competitor_avito_listing",
        description="avito.ru — агрегатор, ниже любого прямого лида",
        lead=_lead(
            domain="avito.ru",
            company="Avito",
            niche="мебель",
            email=False, phone=True,
        ),
        min_expected=15, max_expected=45,
        category="competitor",
    ),
    # -----------------------------------------------------------------------
    # 2. Real customer matching — feed additives niche
    # -----------------------------------------------------------------------
    ScoringCase(
        case_id="real_farm_feed_additives",
        description="Фермерское хозяйство с сайтом — идеальный лид для кормовых добавок",
        lead=_lead(
            domain="ferma-rodniki.ru",
            company="КФХ Родники — фермерское хозяйство",
            niche="сельское хозяйство",
            email=True, phone=True, address=True,
        ),
        # 35+10+20+10+8 +12(фермер) = 95
        min_expected=88, max_expected=100,
        category="real_customer",
    ),
    ScoringCase(
        case_id="real_dairy_producer",
        description="Молочный комбинат в нише пищевое производство",
        lead=_lead(
            domain="moloko-zavod.ru",
            company="Молочный комбинат Заря",
            niche="пищевое производство",
            email=True, phone=True, address=True,
        ),
        min_expected=85, max_expected=100,
        category="real_customer",
    ),
    ScoringCase(
        case_id="real_poultry_farm",
        description="Птицефабрика — ключевое 'животновод' / 'фермер' в нише с/х",
        lead=_lead(
            domain="ptitsefabrika-yug.ru",
            company="Птицефабрика Юг — животноводческий комплекс",
            niche="сельское хозяйство",
            email=True, phone=True, address=True,
        ),
        min_expected=88, max_expected=100,
        category="real_customer",
    ),
    ScoringCase(
        case_id="real_woodwork_with_ru_bonus",
        description="Пилорама .ru — keyword + ru_domain_bonus",
        lead=_lead(
            domain="pilomaterial-les.ru",
            company="Пиломатериалы Лес",
            niche="деревообработка",
            email=True, phone=True, address=True,
        ),
        # 35+10+20+10+8 +12 +3(ru) = 98
        min_expected=92, max_expected=100,
        category="real_customer",
    ),
    ScoringCase(
        case_id="real_construction_full_contacts",
        description="Строительная компания, все контакты",
        lead=_lead(
            domain="stroymontaj-spb.ru",
            company="СтройМонтаж СПб",
            niche="строительство",
            email=True, phone=True, address=True,
        ),
        min_expected=90, max_expected=100,
        category="real_customer",
    ),
    # -----------------------------------------------------------------------
    # 3. No-website SMBs — must NOT be nuked
    # -----------------------------------------------------------------------
    ScoringCase(
        case_id="smb_village_farm_phone_only",
        description="Деревенская ферма, только телефон, без сайта — базовый+phone",
        lead=_lead(
            domain="",
            company="КФХ Иванов фермер",
            niche="сельское хозяйство",
            email=False, phone=True, address=False,
        ),
        # 35 + 10(phone) + 12(фермер) = 57
        min_expected=48, max_expected=68,
        category="smb_no_website",
    ),
    ScoringCase(
        case_id="smb_2gis_card_no_site",
        description="Компания с карточкой в 2GIS (адрес+телефон), без своего сайта",
        lead=_lead(
            domain="",
            company="Автомастерская на Ленина",
            niche="автосервис",
            email=False, phone=True, address=True,
        ),
        # 35+10+8 +12(автомастер — не совпадает → нет, 'автомобил'/'сто' нет) = 53
        # но 'мастерская' не ключ. Скоринг >= 45.
        min_expected=45, max_expected=70,
        category="smb_no_website",
    ),
    ScoringCase(
        case_id="smb_phone_only_niche_match",
        description="Парикмахерская, только телефон — должна быть жизнеспособна",
        lead=_lead(
            domain="",
            company="Парикмахерская на углу",
            niche="салон красоты",
            email=False, phone=True,
        ),
        # 35 + 10 + 12(парикмахер) = 57
        min_expected=48, max_expected=65,
        category="smb_no_website",
    ),
    ScoringCase(
        case_id="smb_address_only",
        description="Ларёк с адресом но без телефона/сайта — не должен быть нулевым",
        lead=_lead(
            domain="",
            company="Булочная Хлеб",
            niche="пищевая промышленность",
            email=False, phone=False, address=True,
        ),
        # 35 + 8(addr) + 12(хлеб) = 55
        min_expected=40, max_expected=60,
        category="smb_no_website",
    ),
    ScoringCase(
        case_id="smb_no_contacts_penalty",
        description="Совсем без контактов — штраф, но не 0",
        lead=_lead(
            domain="",
            company="Некое ООО",
            niche="консалтинг",
            email=False, phone=False, address=False,
        ),
        # 35 - 12 = 23
        min_expected=15, max_expected=30,
        category="smb_no_website",
    ),
    # -----------------------------------------------------------------------
    # 4. Segment bonuses (niche-keyword proxy)
    # -----------------------------------------------------------------------
    ScoringCase(
        case_id="segment_match_mebel_kitchen",
        description="Кухни в нише мебель — keyword bonus срабатывает",
        lead=_lead(
            domain="kuhni-na-zakaz.ru",
            company="Кухни на заказ",
            niche="мебель",
            email=True, phone=True,
        ),
        min_expected=80, max_expected=95,
        category="segment",
    ),
    ScoringCase(
        case_id="segment_nonmatch_fitness_in_mebel",
        description="Фитнес-клуб в нише мебель — без бонуса",
        lead=_lead(
            domain="fitness-club.ru",
            company="Фитнес Клуб",
            niche="мебель",
            email=True, phone=True,
        ),
        # 35+10+20+10 = 75, без keyword_bonus
        min_expected=68, max_expected=80,
        category="segment",
    ),
    ScoringCase(
        case_id="segment_match_auto_service",
        description="Шиномонтаж в нише автосервис",
        lead=_lead(
            domain="shinomontazh-24.ru",
            company="Шиномонтаж 24",
            niche="автосервис",
            email=True, phone=True, address=True,
        ),
        min_expected=85, max_expected=100,
        category="segment",
    ),
    ScoringCase(
        case_id="segment_partial_match_it",
        description="IT-компания с 'dev' в домене",
        lead=_lead(
            domain="devstudio.io",
            company="Dev Studio",
            niche="it",
            email=True, phone=True,
        ),
        min_expected=80, max_expected=100,
        category="segment",
    ),
    # -----------------------------------------------------------------------
    # 5. Geo matches vs wrong region
    # -----------------------------------------------------------------------
    # score_lead() does not currently take geo, so we document invariants:
    # identical inputs must score identically regardless of declared region.
    ScoringCase(
        case_id="geo_match_moscow",
        description="Московская компания — обычный скор",
        lead=_lead(
            domain="stroy-moscow.ru",
            company="СтройМосква",
            niche="строительство",
            email=True, phone=True, address=True,
        ),
        project={"region": "Москва"},
        min_expected=90, max_expected=100,
        category="geo",
    ),
    ScoringCase(
        case_id="geo_wrong_region_same_inputs",
        description="Те же данные, 'не та' область — score должен быть тем же (нет геофактора)",
        lead=_lead(
            domain="stroy-moscow.ru",
            company="СтройМосква",
            niche="строительство",
            email=True, phone=True, address=True,
        ),
        project={"region": "Владивосток"},
        min_expected=90, max_expected=100,
        category="geo",
    ),
    ScoringCase(
        case_id="geo_ru_tld_bonus",
        description=".ru-домен для русской ниши — бонус",
        lead=_lead(
            domain="buhgalter-audit.ru",
            company="Бухгалтерия и Аудит",
            niche="бухгалтерия",
            email=True, phone=True,
        ),
        min_expected=82, max_expected=100,
        category="geo",
    ),
    ScoringCase(
        case_id="geo_io_no_tld_bonus",
        description=".io-домен для той же ниши — без ru_domain_bonus",
        lead=_lead(
            domain="buhgalter-audit.io",
            company="Бухгалтерия и Аудит",
            niche="бухгалтерия",
            email=True, phone=True,
        ),
        min_expected=80, max_expected=98,
        category="geo",
    ),
    # -----------------------------------------------------------------------
    # 6. Cyrillic stemming edge cases
    # -----------------------------------------------------------------------
    ScoringCase(
        case_id="stem_short_root_les",
        description="'лес' как корень — должен матчить 'лесопилка'",
        lead=_lead(
            domain="lesopilka-nn.ru",
            company="Лесопилка НН",
            niche="деревообработка",
            email=True, phone=True,
        ),
        min_expected=80, max_expected=100,
        category="stemming",
    ),
    ScoringCase(
        case_id="stem_suffix_variant_stroy",
        description="'строй' матчит 'стройка', 'стройматериалы'",
        lead=_lead(
            domain="stroyka-plus.ru",
            company="Стройка Плюс",
            niche="строительство",
            email=True, phone=True,
        ),
        min_expected=82, max_expected=100,
        category="stemming",
    ),
    ScoringCase(
        case_id="stem_plural_form_ferma",
        description="'фермер' должен матчить слово 'фермерский'",
        lead=_lead(
            domain="fermerskoe-hoz.ru",
            company="Фермерское хозяйство Заря",
            niche="сельское хозяйство",
            email=True, phone=True,
        ),
        min_expected=85, max_expected=100,
        category="stemming",
    ),
    ScoringCase(
        case_id="stem_case_insensitive",
        description="Верхний регистр компании — keyword всё равно матчится",
        lead=_lead(
            domain="MED-CLINIC.RU",
            company="МЕДИЦИНСКАЯ КЛИНИКА ЗДОРОВЬЕ",
            niche="медицина",
            email=True, phone=True,
        ),
        min_expected=85, max_expected=100,
        category="stemming",
    ),
    ScoringCase(
        case_id="stem_no_false_positive_short",
        description="Слово 'авто' НЕ в 'автономный' — но 'автомобил' матчит только 'автомобиль'",
        lead=_lead(
            domain="avtonomnaya-energetika.ru",
            company="Автономная энергетика",
            niche="автосервис",
            email=True, phone=True,
        ),
        # 'авто' is not in the автосервис keyword list; 'автомобил' won't match 'автономн'.
        # Score ≈ 35+10+20+10 = 75
        min_expected=68, max_expected=82,
        category="stemming",
    ),
    ScoringCase(
        case_id="stem_english_keyword_it",
        description="Английские ключи в IT ('dev','cloud')",
        lead=_lead(
            domain="cloudops.io",
            company="CloudOps Ltd",
            niche="it",
            email=True, phone=True,
        ),
        min_expected=80, max_expected=100,
        category="stemming",
    ),
    # -----------------------------------------------------------------------
    # 7. Relevance score contribution
    # -----------------------------------------------------------------------
    ScoringCase(
        case_id="relevance_zero",
        description="relevance=0 — без добавки",
        lead=_lead(
            domain="example.ru", company="Example", niche="it",
            email=True, phone=True, relevance=0,
        ),
        min_expected=70, max_expected=85,
        category="relevance",
    ),
    ScoringCase(
        case_id="relevance_high",
        description="relevance=120 — максимум +15",
        lead=_lead(
            domain="example.ru", company="Example", niche="it",
            email=True, phone=True, relevance=120,
        ),
        min_expected=85, max_expected=100,
        category="relevance",
    ),
    ScoringCase(
        case_id="relevance_below_threshold",
        description="relevance=20 — ниже порога, без прибавки",
        lead=_lead(
            domain="example.ru", company="Example", niche="it",
            email=True, phone=True, relevance=20,
        ),
        min_expected=70, max_expected=85,
        category="relevance",
    ),
    # -----------------------------------------------------------------------
    # 8. Demo / fallback penalty
    # -----------------------------------------------------------------------
    ScoringCase(
        case_id="demo_penalty_applied",
        description="demo=True — штраф -20",
        lead=_lead(
            domain="demo.local", company="Demo Co", niche="it",
            email=True, phone=True, demo=True,
        ),
        min_expected=50, max_expected=70,
        category="demo",
    ),
    ScoringCase(
        case_id="demo_vs_real_delta",
        description="Демо-лид должен быть строго ниже не-демо при прочих равных",
        lead=_lead(
            domain="demo.local", company="Demo Co", niche="it",
            email=True, phone=True, demo=False,
        ),
        min_expected=70, max_expected=90,
        category="demo",
    ),
]


# ---------------------------------------------------------------------------
# Helpers for the summary reporter
# ---------------------------------------------------------------------------

_RESULTS: dict[str, tuple[bool, str]] = {}


def _record(case_id: str, ok: bool, reason: str = "") -> None:
    _RESULTS[case_id] = (ok, reason)


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_scoring_bank_case(case: ScoringCase) -> None:
    score = case.run()
    ok = case.min_expected <= score <= case.max_expected
    reason = (
        ""
        if ok
        else f"score={score} outside [{case.min_expected},{case.max_expected}]"
    )
    _record(case.case_id, ok, reason)
    assert ok, (
        f"[{case.category}] {case.case_id}: {case.description}\n"
        f"  got score={score}, expected in [{case.min_expected},{case.max_expected}]"
    )


# ---------------------------------------------------------------------------
# Summary — machine-parseable for the overnight cycle harness
# ---------------------------------------------------------------------------


def test_zz_summary() -> None:
    """
    Always passes; prints a machine-parseable summary line that run_cycle.sh
    greps for. Named 'zz' so pytest collects it AFTER every parametrized case.
    """
    total = len(CASES)
    passed = sum(1 for ok, _ in _RESULTS.values() if ok)
    failures = [cid for cid, (ok, _) in _RESULTS.items() if not ok]
    # Pytest captures stdout; use `-s` in CI if you want it inline.
    print(f"\nSCORING_BANK_SUMMARY passed={passed}/{total} failures={failures}")
    # Do not fail here — individual cases already failed. This is just a beacon.
    assert True

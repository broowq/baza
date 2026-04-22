"""
Candidate-relevance regression bank — deterministic, no external APIs.

Purpose
-------
This is the overnight-loop eval harness for
`app.services.lead_collection._candidate_relevance_score` — the PRE-FILTER
that runs on raw search-result items BEFORE enrichment. It's the gate that
decides which candidates survive to be scraped / called / saved.

This is a parallel bank to `test_scoring_bank.py` (which exercises the
post-enrichment `score_lead` function). Both banks are run by
`search_tuning/run_cycle.sh` and their pass rates are concatenated.

Coverage
--------
  * source-weight differences (yandex_maps / 2gis / searxng / bing / rusprofile)
  * website-present vs website-missing treatment, with maps/registry carve-outs
  * aggregator-domain instant rejection (-999)
  * geographic matching (right city bonus / wrong city penalty, map softening)
  * segment bonuses (+ up to +20)
  * niche full-phrase +28 and term-hit cumulative bonus (capped at +30)
  * negative title words (-35) and negative domain parts (-25)
  * synthetic / LLM-fabricated results (-160)
  * credibility-marker floor for searxng/bing (-24 when < 2 markers)
  * tiered competitor detection (1 marker → -12, 3 → -30, 5+ → -55; name
    hits weigh 3×)

Each case asserts the result is within a `[min, max]` band. Bands are loose
enough that small weight-tuning does not thrash the suite — only real
regressions fire.

Invocation
----------
    cd backend && .venv/bin/pytest tests/test_relevance_bank.py -v

The `test_zz_summary` test at the bottom prints a machine-parseable line:

    RELEVANCE_BANK_SUMMARY passed=X/Y failures=['case_id', ...]

which the overnight cycle harness greps for to compare pass rates between
cycles. The same line is also emitted as `SCORING_BANK_SUMMARY` so legacy
parsers that union both files keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.lead_collection import _candidate_relevance_score


# ---------------------------------------------------------------------------
# Case schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelevanceCase:
    """A single labeled pre-filter scenario."""

    case_id: str
    description: str
    item: dict[str, Any]
    niche: str
    geography: str = ""
    segments: list[str] | None = None
    min_expected: int = -1000
    max_expected: int = 1000
    category: str = "general"

    def run(self) -> int:
        return _candidate_relevance_score(
            self.item, self.niche, self.geography, self.segments
        )


def _item(**kw: Any) -> dict[str, Any]:
    """Small helper — accepts loose kwargs, drops None values."""
    return {k: v for k, v in kw.items() if v is not None}


# ---------------------------------------------------------------------------
# The bank
# ---------------------------------------------------------------------------

CASES: list[RelevanceCase] = [
    # -----------------------------------------------------------------------
    # 1. Aggregator / directory instant rejection
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="aggregator_sravni",
        description="sravni.ru — агрегатор, должен дать -999",
        item=_item(
            source="searxng", domain="sravni.ru", company="Сравни",
            website="https://sravni.ru",
        ),
        niche="страхование", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="aggregator",
    ),
    RelevanceCase(
        case_id="aggregator_e_ecolog",
        description="e-ecolog.ru — справочник, -999",
        item=_item(
            source="searxng", domain="e-ecolog.ru",
            company="ООО Ромашка (e-ecolog)",
            website="https://e-ecolog.ru/business/12345",
        ),
        niche="производство", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="aggregator",
    ),
    RelevanceCase(
        case_id="aggregator_yandex_directory",
        description="yandex.ru как домен-агрегатор → -999",
        item=_item(
            source="searxng", domain="yandex.ru",
            company="Яндекс каталог",
            website="https://yandex.ru/maps/org/12345",
        ),
        niche="автосервис", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="aggregator",
    ),
    RelevanceCase(
        case_id="aggregator_avito_listing",
        description="avito.ru — маркетплейс, -999 даже при полном профиле",
        item=_item(
            source="searxng", domain="avito.ru", company="Avito услуга",
            website="https://avito.ru/moscow/uslugi/123",
            snippet="телефон +7 999 001 02 03",
        ),
        niche="ремонт", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="aggregator",
    ),
    RelevanceCase(
        case_id="searxng_no_domain_rejected",
        description="SearXNG без домена/сайта — -999 (web источник требует домен)",
        item=_item(source="searxng", company="Некое ООО"),
        niche="it", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="aggregator",
    ),

    # -----------------------------------------------------------------------
    # 2. Maps source bonus — map items SHOULD survive even without a site
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="maps_2gis_no_website_ok",
        description="2GIS без сайта, но с адресом и категорией — выживает, не -999",
        item=_item(
            source="2gis", company="Автосервис на Ленина",
            address="Москва, ул. Ленина, 5",
            categories=["Автосервис", "Шиномонтаж"],
            city="Москва",
        ),
        niche="автосервис", geography="Москва",
        min_expected=90, max_expected=180,
        category="maps",
    ),
    RelevanceCase(
        case_id="maps_yandex_no_website_real_farm",
        description="Яндекс Карты: реальная ферма без сайта, есть адрес",
        item=_item(
            source="yandex_maps", company="КФХ Родники",
            address="Воронежская область, с. Родники",
            categories=["Сельское хозяйство"],
            city="Воронеж",
        ),
        niche="сельское хозяйство", geography="Воронеж",
        min_expected=90, max_expected=180,
        category="maps",
    ),
    RelevanceCase(
        case_id="maps_beats_dead_searxng",
        description="2GIS карточка без сайта должна обгонять searxng-лид с мертвым сайтом",
        item=_item(
            source="2gis", company="Пекарня Хлеб",
            address="Москва, ул. Пекарская, 1",
            categories=["Пекарня"],
            city="Москва",
        ),
        niche="пищевое производство", geography="Москва",
        # Must clear the dead-searxng baseline (~58) even with 0 niche hits —
        # the map bonus / address / categories / source weight should win.
        min_expected=60, max_expected=180,
        category="maps",
    ),
    RelevanceCase(
        case_id="maps_no_address_no_phone_rejected",
        description="Maps без адреса и телефона — -999 (нет ни одного контакта)",
        item=_item(
            source="yandex_maps", company="ООО Пусто", city="Москва",
        ),
        niche="it", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="maps",
    ),

    # -----------------------------------------------------------------------
    # 3. Registry (rusprofile) — company name alone is enough
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="rusprofile_company_only",
        description="rusprofile: только имя компании — достаточно, не -999",
        item=_item(
            source="rusprofile", company="ООО Ферма Родники",
            city="Воронеж",
        ),
        niche="сельское хозяйство", geography="Воронеж",
        min_expected=10, max_expected=120,
        category="registry",
    ),
    RelevanceCase(
        case_id="rusprofile_empty_name_rejected",
        description="rusprofile с пустым именем — -999",
        item=_item(source="rusprofile", company=""),
        niche="it", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="registry",
    ),

    # -----------------------------------------------------------------------
    # 4. Website presence — soft -8 penalty, not a killer
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="website_missing_soft_penalty",
        description="SearXNG с домом, но без website флага — -8 штраф, но всё еще живой",
        item=_item(
            source="searxng", domain="kfh-ivanov.ru",
            company="КФХ Иванов фермерское хозяйство",
            snippet="животноводство, Воронежская область, телефон +7 999 001 02 03",
            address="Воронежская область",
            city="Воронеж",
        ),
        niche="сельское хозяйство", geography="Воронеж",
        min_expected=20, max_expected=90,
        category="website",
    ),
    RelevanceCase(
        case_id="website_present_small_bonus",
        description="Тот же лид, но website=True → +8 вместо -8 (дельта ~16)",
        item=_item(
            source="searxng", domain="kfh-ivanov.ru",
            company="КФХ Иванов фермерское хозяйство",
            website="https://kfh-ivanov.ru",
            snippet="животноводство, Воронежская область, телефон +7 999 001 02 03",
            address="Воронежская область",
            city="Воронеж",
        ),
        niche="сельское хозяйство", geography="Воронеж",
        min_expected=35, max_expected=110,
        category="website",
    ),

    # -----------------------------------------------------------------------
    # 5. Geo matching — +14 max for multi-hits, -30 for wrong city searxng,
    #    -3 for wrong city maps
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="geo_right_city_searxng",
        description="SearXNG, город совпадает — бонус, нет -30",
        item=_item(
            source="searxng", domain="moscow-ferma.ru",
            company="Ферма Москва",
            website="https://moscow-ferma.ru",
            snippet="фермерское хозяйство Москва Московская область",
            address="Москва, ул. Сельская, 1",
            city="Москва",
        ),
        niche="сельское хозяйство", geography="Москва",
        min_expected=30, max_expected=110,
        category="geo",
    ),
    RelevanceCase(
        case_id="geo_wrong_city_searxng_minus30",
        description="SearXNG, город не совпадает — -30",
        item=_item(
            source="searxng", domain="vladivostok-ferma.ru",
            company="Ферма Владивосток",
            website="https://vladivostok-ferma.ru",
            snippet="фермерское хозяйство Владивосток Приморский край",
            address="Владивосток",
            city="Владивосток",
        ),
        niche="сельское хозяйство", geography="Москва",
        min_expected=-60, max_expected=30,
        category="geo",
    ),
    RelevanceCase(
        case_id="geo_wrong_city_maps_minus3_only",
        description="Maps, wrong city — только -3 (bbox уже ограничил географию)",
        item=_item(
            source="yandex_maps", company="Ферма Владивосток",
            address="Владивосток, ул. Морская, 5",
            categories=["Ферма"],
            city="Владивосток",
        ),
        niche="сельское хозяйство", geography="Москва",
        min_expected=50, max_expected=130,
        category="geo",
    ),

    # -----------------------------------------------------------------------
    # 6. Niche phrase & term hits
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="niche_phrase_full_match",
        description="Полная фраза ниши в тексте → +28 + term hits",
        item=_item(
            source="searxng", domain="metalloobrabotka.ru",
            company="Металлообработка Центр",
            website="https://metalloobrabotka.ru",
            snippet="металлообработка: токарные работы, фрезеровка, Москва",
            address="Москва, промзона",
            city="Москва",
        ),
        niche="металлообработка", geography="Москва",
        min_expected=60, max_expected=160,
        category="niche",
    ),
    RelevanceCase(
        case_id="niche_zero_hits_double_penalty",
        description="Нулевое пересечение с нишей → -24 (0 hits) но домен/сигналы ok",
        item=_item(
            source="searxng", domain="example-co.ru",
            company="Пример Компания",
            website="https://example-co.ru",
            snippet="Москва ООО бизнес компания сервис",
            city="Москва",
        ),
        niche="кормовые добавки", geography="Москва",
        min_expected=-40, max_expected=30,
        category="niche",
    ),
    RelevanceCase(
        case_id="niche_title_hit_no_context_minus8",
        description="Title matches ниши, snippet нет — только -8 (elif ветка)",
        item=_item(
            source="searxng", domain="metalloobr.ru",
            company="Металлообработка ООО",
            website="https://metalloobr.ru",
            snippet="Москва предприятие компания",
            city="Москва",
        ),
        niche="металлообработка", geography="Москва",
        min_expected=20, max_expected=120,
        category="niche",
    ),

    # -----------------------------------------------------------------------
    # 7. Negative title words / domain parts
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="negative_title_wikipedia",
        description="'википедия' в заголовке → -35 (плюс прочие пенальти)",
        item=_item(
            source="searxng", domain="wiki-info.ru",
            company="Википедия — статья рейтинг лучших",
            website="https://wiki-info.ru",
            snippet="обзор сравнение топ 10",
            city="Москва",
        ),
        niche="it", geography="Москва",
        min_expected=-999, max_expected=-50,
        category="negative",
    ),
    RelevanceCase(
        case_id="negative_domain_forum",
        description="forum в домене → -25",
        item=_item(
            source="searxng", domain="it-forum.ru",
            company="IT сообщество",
            website="https://it-forum.ru",
            snippet="обсуждения разработчиков Москва",
            city="Москва",
        ),
        niche="it", geography="Москва",
        min_expected=-60, max_expected=45,
        category="negative",
    ),
    RelevanceCase(
        case_id="negative_domain_blog",
        description="blog в домене → -25",
        item=_item(
            source="searxng", domain="devblog.ru",
            company="Dev Blog",
            website="https://devblog.ru",
            snippet="статьи Москва",
            city="Москва",
        ),
        niche="it", geography="Москва",
        min_expected=-60, max_expected=45,
        category="negative",
    ),

    # -----------------------------------------------------------------------
    # 8. Synthetic / LLM-fabricated results → -160
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="synthetic_latin_gibberish",
        description="LLM-хлам: много латиницы 5+ букв, нет кириллицы/контактов/бизнес-сигналов",
        item=_item(
            source="searxng", domain="acmewidget.ru",
            company="Acmewidget Global Solutions",
            website="https://acmewidget.ru",
            snippet="Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod",
        ),
        niche="кормовые добавки", geography="Москва",
        min_expected=-500, max_expected=-80,
        category="synthetic",
    ),

    # -----------------------------------------------------------------------
    # 9. Competitor tiering — code weighs name hits 3× vs snippet hits 1×
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="competitor_tier1_one_snippet_hit",
        description="1 snippet marker ('доставка') → tier 1 → -12",
        item=_item(
            source="searxng", domain="korma-plus.ru",
            company="Корма Плюс",
            website="https://korma-plus.ru",
            snippet="доставка по России, качественные корма",
            city="Москва",
        ),
        niche="кормовые добавки", geography="Москва",
        segments=None,
        min_expected=10, max_expected=80,
        category="competitor",
    ),
    RelevanceCase(
        case_id="competitor_tier2_name_hit_3x",
        description="'Магазин' в названии (name hit → 3) → tier 2 → -30",
        item=_item(
            source="searxng", domain="magazin-korma.ru",
            company="Магазин кормов",
            website="https://magazin-korma.ru",
            snippet="качественные корма для скота",
            city="Москва",
        ),
        niche="кормовые добавки", geography="Москва",
        min_expected=-20, max_expected=55,
        category="competitor",
    ),
    RelevanceCase(
        case_id="competitor_tier2_three_snippet_hits",
        description="3 snippet markers (опт, прайс, каталог) → tier 2 → -30",
        item=_item(
            source="searxng", domain="korma-shop.ru",
            company="Корма РФ",
            website="https://korma-shop.ru",
            snippet="оптом прайс каталог товаров доставка",
            city="Москва",
        ),
        niche="кормовые добавки", geography="Москва",
        min_expected=-20, max_expected=55,
        category="competitor",
    ),
    RelevanceCase(
        case_id="competitor_tier3_five_plus_hits",
        description="5+ markers → tier 3 → -55",
        item=_item(
            source="searxng", domain="korma-opt.ru",
            company="Корма Оптом",
            website="https://korma-opt.ru",
            snippet="купить заказать оптом прайс каталог товаров доставка скидка акция",
            city="Москва",
        ),
        niche="кормовые добавки", geography="Москва",
        min_expected=-50, max_expected=30,
        category="competitor",
    ),
    RelevanceCase(
        case_id="competitor_real_farm_vs_td_kormovye",
        description="'ТД Кормовые добавки' (магазин-синоним) штрафуется vs реальная ферма",
        item=_item(
            source="searxng", domain="td-korma.ru",
            company="ТД Кормовые добавки магазин оптом",
            website="https://td-korma.ru",
            snippet="купить оптом, прайс, доставка",
            city="Москва",
        ),
        niche="кормовые добавки", geography="Москва",
        # Strong seller signals → significant penalties.
        min_expected=-100, max_expected=30,
        category="competitor",
    ),
    RelevanceCase(
        case_id="competitor_real_farm_no_hits",
        description="Реальная ферма без competitor-сигналов — положительный score",
        item=_item(
            source="searxng", domain="ferma-rodniki.ru",
            company="КФХ Родники фермерское хозяйство",
            website="https://ferma-rodniki.ru",
            snippet="животноводство, Воронежская область, телефон +7 999 001 02 03",
            address="Воронежская область",
            city="Воронеж",
        ),
        niche="сельское хозяйство", geography="Воронеж",
        min_expected=25, max_expected=110,
        category="competitor",
    ),

    # -----------------------------------------------------------------------
    # 10. Segment bonus — +6 per hit, cap +20
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="segment_words_in_title_bonus",
        description="Сегмент 'молочная ферма' в компании — бонус +up to +20",
        item=_item(
            source="searxng", domain="moloko-ferma.ru",
            company="Молочная ферма Родник",
            website="https://moloko-ferma.ru",
            snippet="производство молока, Воронежская область",
            address="Воронежская область",
            city="Воронеж",
        ),
        niche="кормовые добавки", geography="Воронеж",
        segments=["молочная ферма"],
        # Stronger than the no-segment version because of the +6..+20 segment hits.
        min_expected=10, max_expected=130,
        category="segment",
    ),
    RelevanceCase(
        case_id="segment_no_match_vs_match_baseline",
        description="Сегмент не совпадает — никакого сегмент-бонуса",
        item=_item(
            source="searxng", domain="ferma-rodniki.ru",
            company="КФХ Родники",
            website="https://ferma-rodniki.ru",
            snippet="фермерское хозяйство Воронежская область",
            address="Воронежская область",
            city="Воронеж",
        ),
        niche="кормовые добавки", geography="Воронеж",
        segments=["автосервис"],
        min_expected=-50, max_expected=60,
        category="segment",
    ),

    # -----------------------------------------------------------------------
    # 11. Credibility-marker floor (< 2 markers on searxng/bing → -24)
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="credibility_low_searxng_penalized",
        description="SearXNG без маркеров (ни ниши, ни адреса, ни biz, ни гео) → -24",
        item=_item(
            source="searxng", domain="random-co.ru",
            company="Рэндом",
            website="https://random-co.ru",
            snippet="просто текст",
        ),
        niche="кормовые добавки", geography="Москва",
        min_expected=-80, max_expected=20,
        category="credibility",
    ),
    RelevanceCase(
        case_id="credibility_high_no_penalty",
        description="SearXNG с 3+ маркерами (niche hit + address + geo) — без -24",
        item=_item(
            source="searxng", domain="metalloobr-msk.ru",
            company="Металлообработка МСК ООО",
            website="https://metalloobr-msk.ru",
            snippet="токарные и фрезерные работы в Москве, звоните +7 495 123 45 67",
            address="Москва, Промзона 3",
            categories=["металлообработка"],
            city="Москва",
        ),
        niche="металлообработка", geography="Москва",
        min_expected=60, max_expected=180,
        category="credibility",
    ),

    # -----------------------------------------------------------------------
    # 12. Source-weight sanity: yandex_maps > 2gis > searxng > bing
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="source_bing_lowest_weight",
        description="Bing — базовый вес 20, ниже searxng",
        item=_item(
            source="bing", domain="ferma-rodniki.ru",
            company="КФХ Родники",
            website="https://ferma-rodniki.ru",
            snippet="фермерское хозяйство Воронеж",
            city="Воронеж",
        ),
        niche="сельское хозяйство", geography="Воронеж",
        min_expected=5, max_expected=110,
        category="source_weight",
    ),
    RelevanceCase(
        case_id="source_yandex_maps_top_weight",
        description="Yandex Maps — самый высокий source weight (64) + map bonus +18",
        item=_item(
            source="yandex_maps", company="КФХ Родники",
            address="Воронежская обл., с. Родники",
            categories=["Фермерское хозяйство"],
            city="Воронеж",
        ),
        niche="сельское хозяйство", geography="Воронеж",
        min_expected=100, max_expected=200,
        category="source_weight",
    ),

    # -----------------------------------------------------------------------
    # 13. Contact-pattern sniff in snippet (+4 phone, +4 email)
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="contact_phone_and_email_in_snippet",
        description="Телефон +7 и email в сниппете — +8 бонус",
        item=_item(
            source="searxng", domain="metalloobr.ru",
            company="Металлообработка МСК",
            website="https://metalloobr.ru",
            snippet="Москва, звоните +7 (495) 123-45-67, email: info@metalloobr.ru",
            address="Москва",
            city="Москва",
        ),
        niche="металлообработка", geography="Москва",
        min_expected=60, max_expected=180,
        category="contacts",
    ),

    # -----------------------------------------------------------------------
    # 14. Disallowed TLD → -999
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="disallowed_tld_xyz",
        description="Домен на экзотическом TLD .xyz — не в ALLOWED_TLDS → -999",
        item=_item(
            source="searxng", domain="ferma.xyz",
            company="Ферма",
            website="https://ferma.xyz",
            snippet="фермерское хозяйство Москва",
            city="Москва",
        ),
        niche="сельское хозяйство", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="tld",
    ),
    RelevanceCase(
        case_id="suspicious_tld_in_ru_market",
        description="TLD .mz (подозрительный) для русского geo → -999",
        item=_item(
            source="searxng", domain="ferma.mz",
            company="Ферма",
            website="https://ferma.mz",
            snippet="фермерское хозяйство Москва",
            city="Москва",
        ),
        niche="сельское хозяйство", geography="Москва",
        min_expected=-1000, max_expected=-999,
        category="tld",
    ),

    # -----------------------------------------------------------------------
    # 15. Long garbage company name → -10 penalty
    # -----------------------------------------------------------------------
    RelevanceCase(
        case_id="long_company_name_penalty",
        description="Компания с 13+ словами в названии — -10 (шум)",
        item=_item(
            source="searxng", domain="long-co.ru",
            company=(
                "ООО Компания с очень длинным названием из более чем "
                "двенадцати слов что явно похоже на заголовок статьи а не на лид"
            ),
            website="https://long-co.ru",
            snippet="Москва",
            city="Москва",
        ),
        niche="it", geography="Москва",
        # -10 long-name penalty alone is small; just check the score is
        # measurably below a short-name baseline — [<=60] catches future
        # tightening without being flaky today.
        min_expected=-200, max_expected=60,
        category="misc",
    ),
]


# ---------------------------------------------------------------------------
# Results tracker for the summary beacon
# ---------------------------------------------------------------------------

_RESULTS: dict[str, tuple[bool, str]] = {}


def _record(case_id: str, ok: bool, reason: str = "") -> None:
    _RESULTS[case_id] = (ok, reason)


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_relevance_bank_case(case: RelevanceCase) -> None:
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

    Emits both RELEVANCE_BANK_SUMMARY (the new, file-specific beacon) and
    SCORING_BANK_SUMMARY (legacy — so the overnight loop's existing parser
    picks this file up even if the shell harness wasn't yet updated).
    """
    total = len(CASES)
    passed = sum(1 for ok, _ in _RESULTS.values() if ok)
    failures = [cid for cid, (ok, _) in _RESULTS.items() if not ok]
    print(f"\nRELEVANCE_BANK_SUMMARY passed={passed}/{total} failures={failures}")
    print(f"SCORING_BANK_SUMMARY passed={passed}/{total} failures={failures}")
    assert True

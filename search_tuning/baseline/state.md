# Baseline state (cycle 0)

**Date:** 2026-04-22
**Branch:** `autonomous-search-tuning` off `main@14215f8`
**Prod:** HTTPS 502 (nginx→frontend upstream cache stale after healthcheck fix) — known, not blocker for offline work

## Code layout

Two scoring layers:

1. **`backend/app/services/lead_collection.py` `_candidate_relevance_score()`** (line 317)
   — pre-filter ranking used to DROP candidates before enrichment. Rich: geo/segment/competitor/source/negative signals. `_MIN_RELEVANCE_SCORE` (line 519) is the cutoff.
   — Weights: `_SOURCE_WEIGHTS` (yandex_maps=64, 2gis=52, searxng=26, etc.)
   — Penalties: no-website −8, aggregator −120, `_COMPETITOR_SIGNALS` hits (≥2) −30, wrong geo −30 or −3 (maps), etc.
   — Bonuses: niche-word hits, segment-word hits up to +20, geo-word hits up to +14, .ru domain +10, etc.

2. **`backend/app/services/scoring.py` `score_lead()`** (line 161)
   — final 0–100 stored on Lead row after enrichment. Simpler: base 35, +domain/email/phone/address, +keyword_bonus for niche word, −aggregator, relevance contribution up to +15. **Does NOT take `segments` or geography** → no segment or competitor penalty at this layer.

## Existing anti-seller infrastructure

- `_NEGATIVE_KEYWORDS` (line 163): already blocks `-продажа -купить -заказать -интернет-магазин -поставщик -дистрибьютор -оптовик -прайс-лист -каталог-товаров` + forum/wiki/job/bankruptcy filters. ~30 exclusions.
- `_COMPETITOR_SIGNALS` (line 175): 20 seller markers — triggers −30 if ≥2 hit.
- Stemming uses `lemma[:4]` char-based (Python str → correct).

## Known gaps (to verify with agents)

1. `scoring.py` doesn't consider `segments` — segment-match bonus only at pre-filter, never rewards the final stored score.
2. Yandex uses `segments[:3]` in some paths (plan file mentions line ~575).
3. No distinction between SMB-without-website and aggregator-without-website; same −8 for both.
4. Competitor penalty (−30) triggers on ≥2 hits — one hit (e.g. "скидк") goes unpunished.

## Test infrastructure

- `backend/tests/test_scoring.py` — unit tests for `score_lead`
- `backend/tests/test_lead_collection.py` — unit tests for pipeline
- `scripts/test_10_clients.py` — live stress test vs prod (expensive, burns quota)
- `scripts/analyze_leads.py` — post-hoc analyzer

## Cycle harness goals

1. FAST: <5s per iteration, no external APIs
2. DETERMINISTIC: seeded fixtures
3. COVERAGE: synthetic cases for every known gap + every fix proposed

## Active agents (launched this cycle)

- `a0975a4d668c96994` — ANALYST (fix list with line refs)
- `a472d2b567084f6c4` — TEST-HARNESS (new test_scoring_bank.py + run_cycle.sh)
- `a1e4bf3b1dbaca2c7` — QUERY-STRATEGY (query template audit + rewrites)

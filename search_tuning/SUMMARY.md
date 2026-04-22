# Overnight Search-Tuning Loop — Summary

**Branch:** `autonomous-search-tuning` (off `main@14215f8`)
**Cycles run:** 8 (baseline + 7 improvement cycles)
**Bank:** 123/123 (100%) on union of 3 test banks (34 scoring + 56 relevance + 33 query-builder)
**Full backend suite:** 166/166 (up from 108 at start).

## Pass-rate trajectory

| Cycle | Pass | Notes |
|-------|------|-------|
| 0 (baseline) | 31/34 (91%) | scoring bank only; env `keyword_bonus=5` override killed legit matches |
| 1 | 34/34 (100%) | keyword_bonus 5→12, segment bonus in `score_lead`, tiered competitor penalty, niche-gate on prompt |
| 2 | 73/73 (100%) | smart negative-keyword picker (CORE + SELLER_EXTRA), map bail on empty segments; bank extended +39 cases for `_candidate_relevance_score` |
| 3 | 73/73 | Yandex API `has_prompt` gate, LLM segment-echo filter (`_strip_product_echoes`) |
| 4 | 73/73 | ТД/Торговый Дом signals, niche-bonus suppress for sellers |
| 5 | 73/73 | Bing backup segment-aware with smart negatives |
| 6 | 90/90 (100%) | adversarial cases closed: article/how-to hints expanded, 5-char stem for long lemmas, bigger zero-niche-hit penalty on searxng/bing |
| 7 | 123/123 (100%) | query-builder regression tests (+33 cases), llm_filter empty-prompt bypass closed |

## Production-impact changes (by file)

### `backend/app/services/lead_collection.py`
- `_NEGATIVE_KEYWORDS` split into `_NEGATIVE_CORE` (always safe) + `_NEGATIVE_SELLER_EXTRA` (drop when target IS a seller category)
- `_pick_negatives()` — inspects segments, returns appropriate set
- Added marketplaces to CORE: `-avito.ru -ozon.ru -wildberries.ru -market.yandex.ru -yell.ru -zoon.ru -flamp.ru`
- `_COMPETITOR_SIGNALS` + `"тд "`, `"торговый дом"`, `"т/д"`, `"т.д."`
- Tiered competitor penalty: 1 hit → −12, 3 → −30, 5+ → −55 (with 3× weight for company-name hits)
- When `competitor_score ≥ 3`: niche-phrase bonus cut 28→6 and niche-term bonus divided by 4 (a seller's name naturally contains the niche — that's not a buyer signal)
- `_build_discover_queries`: `has_prompt=True` NEVER falls back to niche queries (even on empty segments)
- `_build_yandex_map_queries`: `has_prompt=True` → segment-only queries (no niche concatenation)
- `search_leads`: on `has_prompt + empty_segments` map_search_terms stays empty (no niche fallback to maps)
- Bing backup: segment-aware when prompt present; appends `_pick_negatives()`
- `_build_match_terms`: emits 4-char stem for lemmas ≥5 chars AND 5-char stem for lemmas ≥8 chars (tighter discrimination for long niche words, keeps short-root matching)
- `_ARTICLE_OR_DIRECTORY_HINTS` + how-to patterns: `как выбрать`, `советы по`, `руководство по`, `пошаговое`, `своими руками`, `основы`, `с чего начать`, `инструкция`
- Zero-niche-hit penalty: −32 for searxng/bing (was −24 flat); maps stay at −24

### `backend/app/services/scoring.py`
- `score_lead()` accepts `segments: list[str] | None = None`
- Segment match bonus: +8 per segment-word hit in domain/company, cap +16
- Docstring updated

### `backend/app/services/prompt_enhancer.py`
- `_strip_product_echoes()` post-LLM filter removes segments that echo the user's own product words (kills LLM suggestion `"кормовая добавка"` when prompt is "Продаю кормовые добавки")

### `backend/app/core/config.py` + `.env*`
- `keyword_bonus` restored from `5` → `12` (function's documented default)

### `backend/app/services/llm_filter.py`
- Closed empty-prompt bypass: when LLM fails AND prompt is empty BUT niche/segments are present, synthesize a minimal prompt so the rule-based competitor filter still runs. Previously a transient GigaChat outage meant every candidate passed unfiltered.

## New tests (108 → 166 backend total; 123 in union bank)

- `backend/tests/test_scoring_bank.py` (34 cases, existed) — `score_lead` final scoring
- `backend/tests/test_relevance_bank.py` (56 cases, new) — `_candidate_relevance_score` pre-filter + 17 adversarial
- `backend/tests/test_query_builders.py` (33 cases, new) — `_build_discover_queries`, `_build_yandex_map_queries`, `_pick_negatives` output strings
- `backend/tests/test_prompt_enhancer.py` (7 cases, new) — `_strip_product_echoes`, `_normalize_segments`
- + 95 existing tests kept passing

## Harness

- `search_tuning/run_cycle.sh` — bash-3-compatible cycle runner; parses any `*_BANK_SUMMARY` line, unions results, compares with prior cycle, exits on regression
- `search_tuning/baseline/` — analyst + query-strategy + echo-filter baseline reports
- `search_tuning/cycles/` — one .md + .log per cycle with pass rate, failures, git SHA

## Follow-up work (out of scope for this PR)

From the llm_filter audit report, 2 remaining issues:

- **#2 (CRITICAL):** `filter_candidates_llm` returns only an index list — no structured buyer/seller/noise labels. Downstream cannot distinguish "LLM saw competitor" from "LLM saw noise". Architectural change; separate PR.
- **#3 (HIGH, cost):** no caching on LLM classifications. Every collection run re-LLMs every candidate. Add LRU/disk cache keyed on (candidate_domain + project_config_hash) with 7-day TTL.

## Agents that contributed

1. `a0975a4d...` — ANALYST: produced `fix_list.md` with 15 ranked fixes
2. `a472d2b5...` — TEST-HARNESS: built initial 34-case scoring bank + cycle runner
3. `a1e4bf3b...` — QUERY-STRATEGY: query-template audit + `_NEGATIVE_CORE`/`_SELLER_EXTRA` split proposal
4. `acb378bb...` — BANK-EXTENSION: +39 cases for `_candidate_relevance_score`
5. `aebea712...` — ADVERSARIAL: +17 hard cases, found 2 real bugs (stem over-reach, article-hint gaps)
6. `a2204fdf...` — QUERY-STRING-TEST: +33 regression tests for builder output
7. `a4a2af9b...` — LLM-FILTER-AUDIT: 12 issues ranked by severity

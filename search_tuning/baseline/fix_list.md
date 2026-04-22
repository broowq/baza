# Baseline Fix List — БАЗА lead-search engine

Status of prior plan (`golden-waddling-cupcake.md`):
- Fix 1 (stemming byte vs char) — DONE (line 212: `stem = lemma[:4]`, Python `str[:N]` is already char-based; the original concern was a ghost bug). A **new** stemming/length issue remains (see F-03 below).
- Fix 2 (website penalty −25 → soft) — DONE in `lead_collection.py:360` (`score -= 8`). But the **−25 pain point still lives in `scoring.py`** via `aggregator_penalty` logic and via implicit cumulative `no_contacts_penalty` + missing-domain `+10` bonus not being given. See F-02.
- Fix 3 (Yandex segments `[:3]` → `[:8]`) — DONE (`lead_collection.py:689`). Verified. Pain point #4 is resolved.
- Fix 4 (more competitor tokens in `_NEGATIVE_KEYWORDS`) — PARTIALLY DONE (lines 169–172 include `-продажа -купить -интернет-магазин -поставщик -дистрибьютор -оптовик`). Missing: `-ассортимент -в наличии -акция -скидка -бесплатная доставка`, and the lemma forms of existing ones. See F-06.
- Fix 5 (segment bonus in scorer) — DONE (lines 390–393).
- Fix 6 (competitor penalty) — DONE (lines 396–398) BUT threshold `>= 2` is too lenient. See F-01.
- Fix 7 (maps geo penalty softened to −3) — DONE (line 409).
- Fix 8 (drop niche queries when prompt present) — DONE (`_build_discover_queries`, line 594) BUT only when `segments` also present. If segments come back empty (unknown niche), the niche queries leak back in. See F-07.

---

## Concrete fix table

| # | File:Line | What it is now | What it should become | Impact | Risk |
|---|---|---|---|---|---|
| F-01 | `lead_collection.py:396-398` | `if competitor_hits >= 2: score -= 30` | Tiered: `>=1` → −12, `>=2` → −30, `>=3` → −55. Crucially, **company-name-only hits should bypass threshold** (a name like "ТД Кормовые добавки" is 1 hit but clearly a seller). Split `combined` into `name_text` vs `context_text`, weight name hits 3×. | HIGH | LOW |
| F-02 | `scoring.py:196-201` + `lead_collection.py:357-360` | Website missing: `-8` in relevance scoring **and** a net −10 in final `score_lead` (no +10 `domain` bonus). Combined cost to a contactable SMB farm is ~18 pts, which knocks many real buyers below display threshold. | In `score_lead`: award the `domain`-absent lead a compensating `+6` if `has_phone` **and** source in `{2gis, yandex_maps}`. Also: only apply `no_contacts_penalty` if phone **and** address are both absent (address alone = real SMB). | HIGH | LOW |
| F-03 | `lead_collection.py:199, 211-215` | `_build_match_terms` skips tokens with `len(token) < 3`. For niches like "ИП", "СТО", "КФХ", "ЖБИ", "IT", the 2–3-char root is lost. Also lemmas of 4 chars (e.g. `ферма` → `ферма`, stem-skipped because `len(lemma) >= 5` gate). | Lower the min length: keep tokens `len >= 2` **when Cyrillic uppercase abbreviation** (regex check); keep stems for lemmas `len >= 4` (stem = `[:3]`). Ex: `ферма` → stems `ферм`, `фер`. | MED | MED (over-matching risk on 3-char stems like "лес") |
| F-04 | `prompt_enhancer.py:737` (LLM prompt) | LLM is told segments are customer types — but the system prompt never demands the LLM **exclude** keywords that mirror the user's product. Result: for "продаю IT-услуги", LLM returns `"интернет-магазин"` (a plausible buyer) but also `"IT-компания"` (a competitor). | Add an explicit rule: `"ЗАПРЕЩЕНО: segments не должны содержать слова из списка что пользователь ПРОДАЁТ. Если сомневаешься, исключи сегмент."` Plus a post-LLM filter in `_try_llm_enhance` that re-applies `_extract_prompt_product_words` to `result["segments"]` (already used in `_augment_with_2gis_categories`, just not on LLM seeds). | HIGH | LOW |
| F-05 | `lead_collection.py:942` (2GIS API) and `:1267` (2GIS scrape) | When `search_leads` is called with prompt, `map_search_terms` is correctly built from segments (line 1597–1601). **But** when segments come back empty from the enhancer, it falls back to `effective_niche` — which for a "sells feed additives" prompt is `"животноводство, птицеводство"` thanks to the mapping — OK — but for unknown niches it is the raw user prompt which will find sellers. | When `prompt and not segments`: skip 2GIS/Yandex scraping entirely OR run only a SearXNG query with heavy negatives. Never feed raw seller-prompt into the maps query. | HIGH | MED (may return empty for rare niches, but that's better than garbage) |
| F-06 | `lead_collection.py:163-172` (_NEGATIVE_KEYWORDS) | String-append of literal forms only. `-продажа` does not block pages titled "Продажи оптом". No lemma coverage; SearXNG's tokenization does not stem Russian. | Add all 3 grammatical forms of each negative root: e.g. `-продажа -продажи -продаём`. Add: `-ассортимент -скидка -акция -бесплатно -наличии -новинка`. Also: add `-вакансия -резюме -hh.ru` to `_REJECT_TITLE_WORDS` → actually ALREADY there (line 162), fine. | MED | LOW |
| F-07 | `lead_collection.py:594-600` | `if not has_prompt or not segments:` → niche queries still run when segments list is empty. When the user has a prompt but enhancer failed to yield segments, this floods SearXNG with seller-keywords. | Change to `if not has_prompt:` only. If `has_prompt and not segments`, log a warning and skip SearXNG entirely (maps-only path is cleaner). | HIGH | LOW |
| F-08 | `scoring.py:24-141` (NICHE_KEYWORDS) | Keywords are **product-side** (what sellers sell). For a user selling to farms, `niche="животноводство"` but `NICHE_KEYWORDS["животноводство"]` is undefined → falls through to `niche_lower.split()` which gives ["животноводство"], missing "ферма", "кфх", "агрохолдинг". | Add buyer-side keyword lists: `"животноводство": ["ферм", "кфх", "агрохолдинг", "птицефабрик", "свиновод"]`. More importantly: wire `segments` into `score_lead` so segment terms ARE the keyword bonus when the niche is a customer-type (already half-done in `lead_collection.py` but `scoring.py:score_lead` has no `segments` param). | HIGH | LOW |
| F-09 | `lead_collection.py:175-184` (`_COMPETITOR_SIGNALS`) | List contains literal roots like `"купить"`, `"продают"` — but not stems. A page with `"покупаем отходы"` (legit B2B) matches `"купить"` → false positive. Similarly `"произведено в"` hits `"производител"`. | Anchor competitor signals to word boundaries only, and require co-occurrence with `"от "` (оптом/от производителя) or `"цена"` to count as a hit. For single-token signals, require the `(company OR domain)` field specifically (it's a storefront if name says "Магазин Кормов"). | MED | MED |
| F-10 | `lead_collection.py:583-590` | SearXNG segment queries append `{seg} {geo} {neg}`. When `seg="бизнес-центр"` and geo="Томск", the query is reasonable. But when `seg` came from the LLM as Russian genitive (e.g. `"офисных центров"`) — it's already lemmatized in `prompt_enhancer._normalize_segments`, good. Problem: the `neg` string lives at the END, so engines like Yandex truncate queries > 400 chars and drop negatives. | Move `{neg}` to the front; truncate query at 300 chars BEFORE negatives; or split into two queries: `{seg} {geo}` plus a second `{seg} ООО` without negatives. | MED | LOW |
| F-11 | `llm_filter.py:304-309` (name-only core term) | `if name_core_matches >= 1 and len(core_terms) > 0: reject`. Rejects ANY company with **one** 6-char product stem in its name. "Кировский молочный комбинат" (legit dairy farm buyer for a packaging seller) gets rejected because `молоч` matches packaging seller's `молоко-тары` core term "молоко" ≠ 6-char ok, but still. Over-aggressive when user sells to that industry. | Only reject when core term is accompanied by a seller-signal token in snippet/domain. Otherwise → downgrade to a score deduction, not hard reject. | MED | MED |
| F-12 | `lead_collection.py:442` (searxng/bing credibility) | `credibility_markers < 2: score -= 24`. With maps exemption, OK. But rusprofile (`is_registry_source`) is NOT exempted from this clause — registry entries have no snippet, no phone, no address → always fail credibility gate → always −24 → usually below `_MIN_RELEVANCE_SCORE=26`. Rusprofile pipeline largely dead. | Add `source in {"searxng", "bing"}` guard → exclude rusprofile explicitly (it already falls through, but let's also give rusprofile a flat baseline bonus like +15 when `company` length ≥ 4). | LOW | LOW |
| F-13 | `llm_filter.py:344` (maps pass-through) | Maps entry is kept if it has `address OR phone OR firm_id`. But **2GIS scrape results (line 1344-1356) always have `firm_id`** even when it's an empty string (`firm_id = ""`). The truthy check `or c.get("firm_id")` → fine (empty string is falsy), but some scrape paths DO populate bogus firm_id from regex misses. Verify the real-world rejection rate — suspect it's artificially low. | Require `(address AND phone)` OR `(firm_id AND len(firm_id) >= 5)` for pass-through. | LOW | MED |
| F-14 | `scoring.py:215-217` (ru_niches hard-coded set) | Only 5 niches get the `.ru/.рф` bonus. 45+ new niches added since — none benefit. | Replace `ru_niches` set with `if _looks_russian_market_geo(...)` or just `if settings.russian_market: score += 3`. | LOW | LOW |
| F-15 | `lead_collection.py:1583` (`search_leads` segments) | When `segments` contain a compound like `"строительная компания"`, it's passed whole to `_search_2gis_scrape`. 2GIS query `строительная компания` returns legit results. **BUT** when segments contain a generic "компания" after mapping deduplication, we hit the `_STOPWORDS` filter in `llm_filter.py` but not in the scrape step. Wasted API budget on generic term. | In `search_leads` line 1597, drop segments that are single stopword (`компания`, `фирма`, `центр`) before constructing `map_search_terms`. | LOW | LOW |

### Example companies / queries illustrating the bugs

- **F-01**: User sells feed additives. Current: `"Компания 'Корма Плюс' — продажа и доставка"` has 2 competitor hits (`продажа`, `доставка`) → −30 (good). But `"Агроснаб, поставщик"` has 1 hit → no penalty, scores same as a real farm. `"Торговый Дом Комбикорм"` → name-only hit, no penalty.
- **F-02**: User searches dairy-farm buyers. "КФХ Иванова" has phone+address but no website → `score_lead` gives 35 + 0 (no domain) + 0 (no email) + 10 (phone) + 8 (address) = 53. Aggregator-looking farm with website: 35 + 10 + 10 + 8 = 63. 10-pt gap entirely from website presence.
- **F-04**: For prompt `"Продаю оборудование для кафе"`, we've seen enhancer return segments `["ресторан", "кафе", "оборудование для пиццерий"]`. The third segment mirrors user's product.
- **F-05**: For prompt `"Продаю мраморные подоконники в Екатеринбурге"` (no mapping hit), enhancer returns `segments=[]`. System then searches 2GIS for "мраморные подоконники Екатеринбург" → 40 stone-sellers (competitors).
- **F-06**: SearXNG query `кафе Москва -продажа` still returns `https://kafeoptom.ru/prodazhi` because `-продажа` doesn't match inflected `продажи`.
- **F-08**: Prompt "Продаю корма для ферм" → niche set to "животноводство", `NICHE_KEYWORDS` has no entry, so `_get_niche_keywords("животноводство")` returns just `["животноводство"]`. Keyword bonus fires only for companies whose name contains literal "животноводство" — almost none.
- **F-10**: Query example from logs: `"строительство дач и коттеджей Томск контакты телефон -wikipedia -википедия -погода -форум -блог -рецепт -словарь -реферат -скачать -рейтинг -лучшие -лучших -топ -обзор -отзывы -сравнение -список -вакансия ..."` = 320+ chars. Yandex SearXNG backend silently drops everything past byte 256.

---

## Fix priority order for cycles

Top 5, ranked by `impact × ease`:

1. **F-07** — Remove niche-query leak when prompt present. 2-line change, HIGH impact (eliminates the #1 source of seller results in SearXNG path).
2. **F-04** — Post-filter LLM segments against product words. ~20 lines, HIGH impact (most projects use the LLM path, this contaminates every one).
3. **F-05** — Bail out of maps when `prompt and not segments`. 5-line guard, HIGH impact (cuts the "unknown niche → seller flood" failure mode).
4. **F-01** — Tiered competitor penalty + name-field weighting. ~15 lines, HIGH impact (catches the "Торговый Дом X" single-hit case).
5. **F-08** — Add buyer-side keywords for customer-type niches + wire segments into `score_lead`. ~30 lines, HIGH impact on final score distribution.

F-02, F-06, F-11 would be the next tier.

---

## What I would test (scoring unit-test assertions)

Add `backend/tests/test_scoring_buyer_vs_seller.py` with cases:

```
# Format: (company, domain, snippet, niche, segments, prompt, expected)

# --- F-01: Name-only competitor detection ---
1. assert score("ТД Кормовые добавки", "tdkorma.ru", "прайс оптом", "животноводство", ["ферма","кфх"], "Продаю кормовые добавки") < 20
2. assert score("ООО Светлый Путь (птицефабрика)", "", "адрес: Томск ул...", "животноводство", ["птицефабрика"], "Продаю кормовые добавки") > 55

# --- F-02: Real SMB without website ---
3. assert score("КФХ Иванова", "", "+7 383 ... ул. Ленина 5", niche, segments, prompt, has_phone=True, has_address=True) > 50
4. assert abs(score(with_website) - score(without_website_but_with_phone_and_address)) <= 6  # not 25

# --- F-04: LLM-returned competitor segment filtered ---
5. enhanced = enhance_prompt("Продаю IT-услуги малому бизнесу Москва")
   assert not any("IT" in s or "айти" in s or "разработ" in s for s in enhanced["segments"])
   assert any(s in enhanced["segments"] for s in ["ресторан", "салон красоты", "магазин"])

# --- F-06: Inflected negative keyword ---
6. assert "prodazhi" not in [extract_domain(r) for r in searxng_results("кафе Москва")]

# --- F-08: Buyer-side keywords in scoring ---
7. assert score_lead(domain="ferma-ivanovo.ru", company="КФХ Иваново", niche="животноводство", ...) > score_lead(domain="ivanovo.ru", company="Иваново", niche="животноводство", ...)

# --- F-11: Dairy-farm buyer not rejected by packaging seller ---
8. passed = llm_filter([{"company": "Кировский молочный комбинат", ...}], niche="пищевое производство", prompt="Продаю упаковку")
   assert len(passed) == 1

# --- F-01 tiered penalty ---
9. assert relevance_score(1 competitor hit) - relevance_score(0 hits) == -12
10. assert relevance_score(2 competitor hits) - relevance_score(0 hits) == -30
11. assert relevance_score(3 competitor hits) - relevance_score(0 hits) == -55

# --- Regression: maps pass-through still works ---
12. assert score({"source": "2gis", "company": "DDX Fitness", "address": "ул...", "phone": "+7..."}, niche="спорт", segments=["фитнес-клуб"]) >= _MIN_RELEVANCE_SCORE
```

Each assertion has a named cycle that should be re-run after each fix lands.

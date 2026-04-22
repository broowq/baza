# Query Strategy Baseline Analysis

Files audited:
- `/Users/mark/lid/backend/app/services/lead_collection.py` (2049 lines)
- `/Users/mark/lid/backend/app/services/prompt_enhancer.py` (891 lines)

Entry point for all searching: `search_leads()` at `lead_collection.py:1583`. Inputs it receives: `query`, `niche`, `geography`, `segments`, `prompt`, `use_yandex`. `prompt_enhancer.enhance_prompt()` converts raw user text → `{niche, geography, segments[], target_customer_types[], search_queries_niche}` (see `prompt_enhancer.py:494`).

---

## 1. Current query anatomy

### 1a. 2GIS (scrape + API)

Inputs: a single `term` (segment name OR niche fallback) + `geo`. Built at `lead_collection.py:1596-1603`:

```python
map_search_terms = []
if effective_segments:
    for seg in effective_segments[:8]:
        if seg and len(seg) > 2:
            map_search_terms.append(seg)
if not map_search_terms:
    map_search_terms = [effective_niche]
```

Then for each term:

- **2GIS scrape** — URL: `f"https://2gis.ru/{slug}/search/{quote_plus(niche)}"` (`lead_collection.py:1267`). Geo is encoded as a city slug (`_city_to_slug`). The `niche` variable here is actually the `term` passed in — i.e. a segment. No niche, no negatives.
- **2GIS API fallback** — params `{"q": niche, "type": "branch", "city_id": ..., "page_size": ≤10}` (`lead_collection.py:941-951`). If no `city_id`, falls back to `params["q"] = f"{niche} {geo}"` (`:951`).

**No negative keywords used for 2GIS.** The map scrape cannot accept `-word` operators anyway (it's a facet search).

### 1b. Yandex Maps (API + scrape)

- **API** — built in `_build_yandex_map_queries()` (`lead_collection.py:682-699`):
  ```python
  base_queries = [
      f"{geo}, {niche}",
      f"{niche}, {geo}",
      f"{geo}, {niche} компания",
      f"{geo}, {niche} официальный сайт",
  ]
  for segment in segments[:8]:
      base_queries.append(f"{geo}, {niche} {segment}")
  ```
  This is the ONLY place segments are combined **with niche**. For a customer-search prompt, this is wrong: it asks Yandex for "Томск, кормовые добавки птицефабрика" — a contradictory query mixing sellers and buyers, which on Yandex resolves to sellers.

- **Yandex scrape** — URL: `f"https://yandex.ru/maps/67/{slug}/search/{quote_plus(niche)}"` (`lead_collection.py:1426`). The `niche` here is the per-iteration `term` from `search_leads`. Called once per segment term, like 2GIS.

**No negative keywords on Yandex** (map queries don't honor them).

### 1c. SearXNG (web search)

Built in `_build_discover_queries()` (`lead_collection.py:569-609`). The `has_prompt` flag is key:

```python
# When has_prompt=True, segments ARE customer types; search ONLY segments.
if segments:
    for seg in segments[:8]:
        queries.extend([
            f"{seg} {geo} контакты телефон {neg}",
            f"{seg} {geo} официальный сайт {neg}",
            f'"{seg}" "{geo}" ООО {neg}',
        ])

if not has_prompt or not segments:
    queries.extend([
        f"{niche} {geo} контакты телефон {neg}",
        f"{niche} {geo} о компании {neg}",
        f"{niche} {geo} предприятие {neg}",
        f'"{niche}" "{geo}" ООО {neg}',
    ])
```

URL: `f"{settings.searxng_url}/search?q={quote_plus(query)}&format=json&pageno={page}"` (`lead_collection.py:618`).

`neg` = `_NEGATIVE_KEYWORDS` (`lead_collection.py:163-172`):
```
-wikipedia -википедия -погода -форум -блог -рецепт -словарь
-реферат -скачать -рейтинг -лучшие -лучших -топ -обзор -отзывы -сравнение -список
-вакансия -вакансии -работа -резюме -hh.ru -superjob
-ликвидирован -ликвидация -банкрот -inn -огрн
-sravni.ru -e-ecolog.ru -rusprofile.ru -list-org.com
-продажа -купить -заказать -интернет-магазин
-поставщик -дистрибьютор -оптовик
-прайс-лист -каталог-товаров
```

Bing (backup) gets a separate one-shot `f"{effective_niche} компания {effective_geo}"` (`:1708`), with NO negative keywords and NO segment expansion — the weakest query in the pipeline.

---

## 2. Customer-vs-Seller problem — 3 worked examples

### Example A: "Кормовые добавки для животных в Томске"

`prompt_enhancer` maps this via the vet/feed rule (`prompt_enhancer.py:117-125`) to:
- `niche` = "животноводство, птицеводство, сельское хозяйство"
- `segments` = ["птицефабрика", "свиноферма", "животноводческая ферма", "агрохолдинг", "зоомагазин", "ветеринарная клиника", "конный клуб", "рыбоводство"]

**Queries produced TODAY:**

- 2GIS scrape (`/tomsk/search/<term>`), per segment: `птицефабрика`, `свиноферма`, `животноводческая ферма`, `агрохолдинг`, `зоомагазин`, `ветеринарная клиника`, `конный клуб`, `рыбоводство` → **correct, these are buyers.**
- Yandex Maps API: `"Томск, животноводство"`, `"животноводство, Томск"`, `"Томск, животноводство компания"`, `"Томск, животноводство официальный сайт"`, plus `"Томск, животноводство птицефабрика"` etc. → returns **mixed** (industry associations, holdings — some buyers, some media). The "животноводство" niche string floods results with info/review pages.
- SearXNG (has_prompt=True): `"птицефабрика Томск контакты телефон <neg>"`, etc. per segment → **correct.** Niche queries are skipped because `has_prompt=True`.
- Bing backup: `"животноводство, птицеводство, сельское хозяйство компания Томск"` → returns aggregator directories.

**Who actually lands in the bucket:** Segment-driven 2GIS scrape is clean. But the Yandex API query `Томск, животноводство компания` returns regional ag-ministry pages, news, and a handful of large holdings — not individual farms. Bing is noise.

**Ideal queries (literal):**
- 2GIS scrape: `https://2gis.ru/tomsk/search/птицефабрика`, `.../свиноферма`, `.../крестьянско-фермерское+хозяйство`, `.../молочная+ферма` — already close.
- Yandex Maps: `"птицефабрика Томск"`, `"свиноферма Томск"`, `"КФХ Томск"`, `"молочная ферма Томск"` — drop the niche.
- SearXNG: `"птицефабрика Томская область" сайт контакты -вакансии -wikipedia`, `"КФХ" Томск ИНН -ликвидирован` — current neg list is fine here.

### Example B: "Клининговые услуги в Екатеринбурге"

`prompt_enhancer` maps via the cleaning rule (`prompt_enhancer.py:105-115`):
- `niche` = "коммерческая недвижимость, HoReCa, торговые центры"
- `segments` = ["бизнес-центр", "торговый центр", "отель", "гостиница", "ресторан", "медицинский центр", "фитнес-клуб", "коворкинг", "офисный центр", "управляющая недвижимостью"]

**Queries produced TODAY:**
- 2GIS scrape per segment: `бизнес-центр`, `торговый центр`, `отель`, ... → **correct buyers.**
- Yandex API: `"Екатеринбург, коммерческая недвижимость, HoReCa, торговые центры"` — the comma-joined niche string is nonsensical to Yandex. It returns directory pages.
- Yandex API with segment: `"Екатеринбург, коммерческая недвижимость, HoReCa, торговые центры бизнес-центр"` — same problem.
- SearXNG: `"бизнес-центр Екатеринбург контакты телефон <neg>"` etc. → mostly clean but `-поставщик` may over-filter (BCs with "поставщик услуг" text).

**Ideal:**
- Yandex: `"бизнес-центр Екатеринбург"`, `"торговый центр Екатеринбург"`, `"отель Екатеринбург"` — pure segment + geo.
- SearXNG: `"бизнес-центр" Екатеринбург сайт контакты -вакансии -wikipedia` (no `-поставщик`).

### Example C: "Оборудование HoReCa в Ростове-на-Дону"

`prompt_enhancer` HoReCa rule (`prompt_enhancer.py:78-88`):
- `niche` = "рестораны, кафе, столовые, отели"
- `segments` = ["ресторан", "кафе", "столовая", "отель", "гостиница", "пекарня", "кондитерская", "бар", "пиццерия", "фастфуд"]

**Queries produced TODAY:**
- 2GIS scrape: `ресторан`, `кафе`, ... in Ростов-на-Дону → **correct.**
- Yandex API: `"Ростов-на-Дону, рестораны, кафе, столовые, отели"`, plus `... ресторан`, `... кафе` → the comma-joined `niche` is fine-ish here because its own words overlap with segments, but query is still awkward.
- SearXNG per segment with negatives → good, but `_NEGATIVE_KEYWORDS` includes `-оборудование`? No — it doesn't; however `-продажа -купить -интернет-магазин` correctly filters HoReCa-equipment sellers who might otherwise clutter results.

**Ideal:**
- Yandex: `"ресторан Ростов-на-Дону"`, `"кафе Ростов-на-Дону"`, `"пекарня Ростов-на-Дону"`.
- SearXNG: `"ресторан Ростов-на-Дону" сайт меню контакты -вакансии -отзывы` (add `-отзыв*` expansions; `-отзывы` already present).

**Common pattern across all three:** 2GIS & SearXNG do the right thing when `segments` exist and `has_prompt=True`. **Yandex Maps does NOT** — `_build_yandex_map_queries` still concatenates niche with every query, producing seller-biased queries for buyer-hunting projects.

---

## 3. Proposed rewrites

### Fix A (highest impact): `_build_yandex_map_queries` must respect prompt mode

File: `lead_collection.py:682-699`. Current signature is `(niche, geo, segments)` with no `has_prompt` flag. Change to:

```python
def _build_yandex_map_queries(niche, geo, segments, *, has_prompt: bool = False):
    queries = []
    if has_prompt and segments:
        # Segment-driven (buyer) mode — drop niche entirely
        for segment in segments[:8]:
            if segment:
                queries.append(f"{segment} {geo}".strip())
                queries.append(f"{geo}, {segment}".strip(", "))
    else:
        # Original niche-driven mode (direct niche search)
        queries.extend([
            f"{geo}, {niche}",
            f"{niche}, {geo}",
            f"{geo}, {niche} компания",
        ])
        for segment in segments[:8]:
            queries.append(f"{geo}, {segment}")
    # dedupe...
```

And propagate `has_prompt` through `_search_yandex_maps()` (`:763`) and the call site in `search_leads()` (`:1650`).

### Fix B: Bing backup query needs segment-awareness

`lead_collection.py:1708`:
```python
bing_query = f"{effective_niche} компания {effective_geo}".strip()
```

Replace with segment-driven loop when `prompt` is set:
```python
if prompt and effective_segments:
    for seg in effective_segments[:3]:
        bing_query = f"{seg} {effective_geo} контакты"
        bing_results = _search_bing(bing_query, remaining)
        collect_candidates(bing_results)
else:
    bing_query = f"{effective_niche} компания {effective_geo}"
    ...
```

### Fix C: 2GIS API fallback loses city when `city_id` resolution fails

`lead_collection.py:951`: `params["q"] = f"{niche} {geo}"`. When `niche` is already a multi-word segment ("животноводческая ферма") this becomes "животноводческая ферма Томск" — OK. No change needed, but ensure segments are the input (they already are, via the per-term loop in `search_leads`).

### Fix D: SearXNG prompt-mode — consider quoted-segment pinning

`lead_collection.py:586-590`: current template uses `f'"{seg}" "{geo}" ООО {neg}'` — the `"ООО"` token biases toward legal-entity landing pages. For some segments ("бизнес-центр") LLC is a dead-end (BCs are often owned by UK/АО or don't publish LLC on homepage). Consider removing the ООО-specific variant or making it optional.

### Priority order

1. **Fix A** — immediate win for buyer queries on Yandex (likely the biggest seller-contamination vector currently).
2. **Fix B** — Bing is weakest link; easy one-line change.
3. **Fix D** — marginal but worth testing against click-through lists.
4. **Fix C** — no change, just noting it's already fine.

---

## 4. Negative-keyword audit

Current list (`lead_collection.py:163-172`), plus `_COMPETITOR_SIGNALS` (`:175-184`) used for scoring penalty.

### Missing seller-signals to add

The current list targets generic noise (wiki/reviews/aggregators) + a few seller words. Competitor filter (in `_COMPETITOR_SIGNALS`) is richer but is post-hoc scoring only, not a query negative. Candidates to promote into `_NEGATIVE_KEYWORDS`:

| Missing term | Rationale |
|---|---|
| `-опт` / `-оптом` | "оптом" is a classic seller marker; currently in `_COMPETITOR_SIGNALS` but not negated at query time. |
| `-прайс` | Already have `-прайс-лист` but many sites use `прайс` alone. |
| `-ассортимент` | Seller signal in `_COMPETITOR_SIGNALS`, missing from negatives. |
| `-каталог` | Seller inventory; many sellers' sites are "каталог товаров". |
| `-скидка` / `-акция` / `-распродажа` | In competitor signals but not negated. |
| `-маркетплейс` / `-wildberries` / `-ozon.ru` | Marketplaces dilute B2B web results heavily. |
| `-отзыв` (lemma) | Have `-отзывы` but case variations slip past. |
| `-yell.ru` / `-zoon.ru` / `-flamp` | Directory aggregators not in the current list. |
| `-2gis.ru` / `-yandex.ru/maps` | We fetch these directly; stripping from SearXNG avoids duplicate low-scored results. |
| `-avito.ru` / `-youla.ru` | Classifieds dominate "купить X" style queries. |

### Currently present that may over-filter

| Term | Risk |
|---|---|
| `-купить` / `-заказать` / `-продажа` | When searching for **retail customers** (e.g. a B2B brand targeting shops), the target's homepage may legitimately say "купить в розницу". Removing is OK only when we are CERTAIN the project is a seller-hunt, i.e. when `has_prompt=True`. Recommend: make negatives conditional on mode. |
| `-поставщик` / `-дистрибьютор` / `-оптовик` | These over-filter in cases where the customer IS a distributor/wholesaler (e.g. selling packaging TO a wholesaler). Especially hits buyer lists that self-describe as "оптовая база". |
| `-прайс-лист` | Over-filters legit manufacturers with downloadable spec sheets. |
| `-rusprofile.ru` | We actively use rusprofile as a source (`_search_rusprofile`, `:1503`). Negating it in SearXNG is consistent (we dedupe elsewhere), but ensure rusprofile IS populated via its dedicated source. |
| `-интернет-магазин` | Over-filters when the BUYER is itself an online store (target customer types list includes "интернет-магазин" in many mappings — see prompt_enhancer.py:170, :180, :210). **This is an active contradiction.** If the segment list contains "интернет-магазин", this negative must be dropped for that project. |

### Recommendation

Make `_NEGATIVE_KEYWORDS` two-tiered:

```python
_NEGATIVE_CORE = "-wikipedia -wikipedia -погода -форум -рецепт -реферат -скачать " \
                 "-отзывы -отзыв -рейтинг -сравнение -топ -обзор " \
                 "-вакансия -вакансии -работа -резюме -hh.ru -superjob " \
                 "-ликвидирован -ликвидация -банкрот " \
                 "-sravni.ru -e-ecolog.ru -list-org.com " \
                 "-yell.ru -zoon.ru -flamp.ru -2gis.ru -avito.ru -youla.ru -wildberries -ozon.ru"

_NEGATIVE_SELLER_EXTRA = "-прайс -каталог -ассортимент -оптом -опт " \
                          "-скидка -акция -распродажа -маркетплейс"
```

Apply `_CORE + _SELLER_EXTRA` only when `has_prompt and segments` AND when no segment contains `магазин|интернет`. Else apply `_CORE` alone. Wire this into `_build_discover_queries` (`:577`).

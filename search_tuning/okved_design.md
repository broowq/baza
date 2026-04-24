# ОКВЭД Extraction — Design Doc

**Status:** Draft · **Author:** architect · **Date:** 2026-04-24
**Scope:** Phase 1 only — extraction + storage + UI display. Phase 2 (ФНС ЕГРЮЛ lookup) is out of scope.

---

## 1. Context

БАЗА takes a user prompt like `"Продаю кормовые добавки для животных в Томске"` and, via `prompt_enhancer.enhance_prompt()` (see `/Users/mark/lid/backend/app/services/prompt_enhancer.py`), derives `segments` (`["птицефабрика", "животноводческая ферма"]`). These segments drive SearXNG / 2GIS / Yandex probes.

We now want to additionally emit **ОКВЭД codes of the target customers** — not the seller — so Phase 2 can cross-check collected leads against the ФНС ЕГРЮЛ registry.

The same LLM call that produces `segments` should also produce `okved_codes`. The rule-based fallback (`_PRODUCT_TO_CUSTOMERS`, line 61) should be extended with an `okved` field so no new code path is created.

---

## 2. Schema Change

**Decision: add `okved_codes: list[dict]` (JSONB) directly on `Project`.**

```python
# backend/app/models/entities.py — Project
okved_codes: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
# Element shape: {"code": "01.47", "label": "Разведение с/х птицы", "confidence": 0.9, "source": "llm"}
```

### Why not a separate `ProjectOKVED` table

| Factor | JSONB column | Separate table |
|---|---|---|
| Typical count per project | 2–8 codes | 2–8 codes |
| Query pattern | Always read with Project | Always read with Project (→ extra JOIN) |
| Needs FK constraints? | No (ОКВЭД is an external code, not one of our entities) | No |
| Needs its own timestamps / audit? | Not yet | Only if Phase 2 edits individual codes |
| Mirrors `segments` (already JSONB) | Yes | No — inconsistent |
| Migration cost | One Alembic column | Table + FK + index + join model |

`segments` already uses JSONB on the same table with identical access patterns. Consistency wins. If Phase 2 grows per-code metadata (last ФНС-checked-at, matched-leads count), we can migrate to a table then — the data volume is low enough that a one-off backfill is trivial.

### Indexing

No index initially. If we later filter projects by ОКВЭД (e.g. "all projects targeting 01.*"), add `CREATE INDEX ON projects USING gin (okved_codes jsonb_path_ops);`.

### Migration

One Alembic revision: `add_okved_codes_to_projects` → `ALTER TABLE projects ADD COLUMN okved_codes JSONB NOT NULL DEFAULT '[]'::jsonb;`. Backfill existing rows via the rule-based fallback in a one-shot management command (`python -m app.cli backfill_okved`).

---

## 3. Extraction Logic

### 3.1 Where it plugs in

`_try_llm_enhance()` already asks GigaChat/Anthropic for segments. We **extend the same JSON response schema** with `okved_codes` — no extra LLM round-trip, no extra latency, no extra spend.

Add one key to the JSON contract in the system prompt and one post-validation step that:

1. Strips non-matching entries (regex `^\d{2}(\.\d{1,2})?$`).
2. Clamps confidence to `[0.0, 1.0]`.
3. De-dupes by `code` keeping max confidence.
4. Drops any code with confidence `< 0.4` (LLM guessing).

### 3.2 GigaChat system-prompt addendum

Append to the existing system prompt (after `"explanation"`):

```text
Дополнительно верни ОКВЭД-коды ПОТЕНЦИАЛЬНЫХ КЛИЕНТОВ (не продавца!) — это российский классификатор видов деятельности.

Формат: массив объектов {code, label, confidence}, где:
- code: строка вида "XX" (раздел), "XX.X" или "XX.XX" (подкласс). Примеры: "01", "01.4", "01.47".
- label: краткое русское название вида деятельности.
- confidence: число от 0.0 до 1.0 — насколько уверенно этот код описывает типичного покупателя.

Верни от 2 до 6 кодов, отсортированных по убыванию confidence. Только коды покупателей!
Неправильно: если пользователь продаёт корма, НЕ возвращай 46.21 (оптовая торговля зерном) — это продавец.
Правильно: 01.47 (птицеводство), 01.46 (свиноводство) — это покупатели кормов.

Добавь поле в JSON-ответ:
  "okved_codes": [
    {"code": "01.47", "label": "Разведение сельскохозяйственной птицы", "confidence": 0.9},
    {"code": "01.46", "label": "Разведение свиней", "confidence": 0.85}
  ]
```

### 3.3 Example prompts → expected outputs

| # | Prompt | Expected `okved_codes` |
|---|--------|-----------------------|
| 1 | `"Продаю кормовые добавки для животных в Томске"` | `[{"01.47",0.9},{"01.46",0.85},{"01.41",0.8},{"01.42",0.75}]` |
| 2 | `"Разрабатываю CRM для малого бизнеса"` | `[{"47.19",0.6},{"56.10",0.6},{"96.02",0.55},{"86.23",0.5}]` |
| 3 | `"Поставляем металлопрокат и арматуру по России"` | `[{"41.20",0.9},{"42.11",0.7},{"25.11",0.7},{"43.99",0.6}]` |
| 4 | `"Клининговая компания, убираем офисы и ТЦ"` | `[{"68.32",0.85},{"68.20",0.8},{"47.19",0.7},{"55.10",0.65}]` |
| 5 | `"Производим мебель для ресторанов и отелей"` | `[{"55.10",0.9},{"56.10",0.9},{"56.30",0.75},{"93.29",0.5}]` |

Codes reference the 2016 ОКВЭД-2 edition (ОК 029-2014).

---

## 4. Rule-Based Fallback

When `llm_client.is_configured()` is `False` or returns garbage, `_smart_fallback()` matches against `_PRODUCT_TO_CUSTOMERS`. **Add an `okved` key to each mapping**:

```python
{
    "keywords": ["кормов", "корм ", "комбикорм", ...],
    ...
    "okved": [
        {"code": "01.47", "label": "Разведение с/х птицы",       "confidence": 0.9},
        {"code": "01.46", "label": "Разведение свиней",           "confidence": 0.85},
        {"code": "01.41", "label": "Разведение молочного КРС",    "confidence": 0.8},
        {"code": "01.42", "label": "Разведение прочего КРС",      "confidence": 0.75},
    ],
},
```

When fallback fires, copy `best_match["okved"]` into the result dict with `source: "rule"`.

### Segments → OKVED lookup table (≥30 entries)

Derived by scanning current `_PRODUCT_TO_CUSTOMERS.segments`. Store as `_SEGMENT_TO_OKVED: dict[str, list[str]]` — used when a segment appears that isn't covered by its product mapping (e.g. LLM added a segment the rule table never saw).

| Segment | Primary OKVED codes |
|---|---|
| птицефабрика | 01.47 |
| свиноферма | 01.46 |
| животноводческая ферма | 01.41, 01.42, 01.45 |
| агрохолдинг | 01.11, 01.41, 01.47 |
| зоомагазин | 47.76 |
| ветеринарная клиника | 75.00 |
| конный клуб | 93.19, 01.43 |
| рыбоводство | 03.22 |
| тепличный комплекс | 01.13 |
| элеватор | 52.10, 10.61 |
| фермерское хозяйство | 01.11, 01.41 |
| кфх | 01.11, 01.41 |
| ресторан | 56.10 |
| кафе | 56.10 |
| столовая | 56.29 |
| пиццерия | 56.10 |
| пекарня | 10.71, 56.10 |
| кондитерская | 10.71, 10.72 |
| бар | 56.30 |
| отель | 55.10 |
| гостиница | 55.10 |
| коворкинг | 68.20, 82.99 |
| бизнес-центр | 68.20 |
| торговый центр | 68.20, 68.32 |
| продуктовый магазин | 47.11 |
| супермаркет | 47.11 |
| магазин одежды | 47.71 |
| аптека | 47.73 |
| автосервис | 45.20 |
| сто | 45.20 |
| автомойка | 45.20 |
| шиномонтаж | 45.20 |
| автодилер | 45.11, 45.19 |
| таксопарк | 49.32 |
| строительная компания | 41.20 |
| застройщик | 41.10, 41.20 |
| подрядчик | 43.99 |
| ремонтная бригада | 43.39 |
| дорожно-строительная компания | 42.11 |
| дсу | 42.11 |
| девелопер | 41.10 |
| кровельщик | 43.91 |
| завод | 25.62, 28.99 |
| фабрика | 13.20, 14.19 |
| производственная компания | 25.62, 28.99 |
| цех | 25.62 |
| горнодобывающая компания | 07.10, 08.99 |
| нефтегазовая компания | 06.10, 06.20 |
| молокозавод | 10.51 |
| пивоварня | 11.05 |
| пищевое производство | 10.89 |
| мебельная фабрика | 31.01, 31.09 |
| столярная мастерская | 16.23, 31.09 |
| стоматология | 86.23 |
| больница | 86.10 |
| клиника | 86.22 |
| медицинский центр | 86.22 |
| поликлиника | 86.21 |
| диагностический центр | 86.90 |
| школа | 85.14 |
| детский сад | 85.11 |
| салон красоты | 96.02 |
| фитнес-клуб | 93.13 |
| банк | 64.19 |
| интернет-магазин | 47.91 |
| it-компания | 62.01 |
| датацентр | 63.11 |
| интернет-провайдер | 61.10 |
| телекоммуникационная компания | 61.10 |
| логистическая компания | 49.41, 52.29 |
| склад | 52.10 |
| оптовая база | 46.90 |
| прачечная | 96.01 |
| клининговая компания | 81.21, 81.22 |
| охранное предприятие | 80.10 |

(75+ mappings; comfortably clears the 30-entry bar.)

### Merge rule

Output = union of (product-mapping `okved`) + (segment-lookup `okved` for every segment not already covered). Cap at 8 codes, sort by confidence desc. Tag all entries `"source": "rule"`.

---

## 5. API Endpoint

### `POST /projects/{id}/okved/extract`

**Purpose:** (Re)run ОКВЭД extraction for a project. Separate from `POST /projects` because:
- user may want to re-extract after editing the prompt
- Phase-2 ФНС step needs a standalone trigger
- keeps project-creation latency unchanged

**Request body:**

```json
{
  "force": false,
  "source": "auto"
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `force` | bool | `false` | If `false` and project already has codes, return existing. If `true`, always re-extract. |
| `source` | enum(`auto`\|`llm`\|`rule`) | `auto` | `auto` = LLM with fallback. `llm` = LLM only (422 if unavailable). `rule` = skip LLM, useful for tests. |

**Response 200:**

```json
{
  "project_id": "…",
  "okved_codes": [
    {"code": "01.47", "label": "Разведение с/х птицы", "confidence": 0.9, "source": "llm"}
  ],
  "source": "llm",
  "extracted_at": "2026-04-24T10:15:00Z",
  "cached": false
}
```

**Response 422:** prompt empty / project has no `prompt` or `niche`. **404:** project not found / org mismatch. **503:** `source=llm` requested but `llm_client.is_configured()` is false.

### Idempotency

- Without `force=true`: call is idempotent — returns cached codes (`cached: true`).
- With `force=true`: treated as a PUT-like replace. No `Idempotency-Key` header required — re-extraction is cheap and the last write wins. We do NOT append; we replace.
- Concurrent `force=true` calls are serialized via `SELECT … FOR UPDATE` on the project row to avoid last-writer races.

### Authz

Same as other `/projects/{id}/*` routes: user must belong to the project's organization.

---

## 6. Frontend Integration

**Where:** Project detail page (`/projects/:id`), right under the existing Segments chips block.

**Component:** `<OkvedChips>` — renders `project.okved_codes` as a row of pill-chips.

```
[ОКВЭД 01.47 · Разведение с/х птицы · 90%] [01.46 · Свиньи · 85%] ...
                                                            [↻ Пересчитать]
```

**Behaviour:**

- **Read-only** in Phase 1. Users can view, cannot edit individual codes. Rationale: codes are machine-generated; hand-editing them makes the later ФНС match unauditable. If a user disagrees, they edit the prompt and click **Пересчитать**, which calls `POST /projects/{id}/okved/extract?force=true`.
- **Confidence styling:** `≥0.8` solid, `0.6–0.8` outline, `<0.6` dashed border + muted text. Hover tooltip: `"Источник: LLM · 24 апреля 2026"`.
- **Empty state:** if `okved_codes == []` (old projects pre-migration), show `[Извлечь ОКВЭД]` CTA that triggers `POST .../extract` without `force`.
- **Loading state:** button shows spinner; chips greyed until 200 returns.
- **Error state:** toast `"Не удалось извлечь ОКВЭД — попробуйте позже"` on 5xx; inline message on 422.

**Project-creation flow:** extraction runs automatically inside the existing `enhance_prompt()` call (same LLM round-trip), so new projects land with chips already populated — no extra click.

**Future (Phase 2) hook:** each chip becomes clickable → drill-down to "N компаний с ОКВЭД 01.47 найдены в ЕГРЮЛ". Design the chip component with an optional `onClick` prop from day one so Phase 2 doesn't need to rewrite markup.

---

## 7. Open Questions (for Phase 2, not blocking)

1. Do we weight lead scoring by ОКВЭД match vs. segment match?
2. Should the cron collection job re-run ОКВЭД extraction when the prompt is edited?
3. Do we expose ОКВЭД as a project-filter in the lead list UI?

"""Tests for the per-candidate LLM-verdict cache + answer parsing in llm_filter.

The AI filter caches each LLM keep/drop decision (keyed on project-config hash +
candidate identity) so repeat candidates for the same niche skip the LLM. These
tests use a tiny in-memory fake Redis and a mocked llm_client to assert the LLM
is only called for uncached candidates, that drop-verdicts are cached ONLY from
well-formed JSON answers (truncation safety), that ambiguous answers fall back
to the rule-based filter, and that the rule-based fallback no longer rejects
the requested buyer segments as "competitors".
"""
from __future__ import annotations

from app.services import llm_filter, llm_client


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def mget(self, keys):
        return [self.store.get(k) for k in keys]

    def get(self, k):
        return self.store.get(k)

    def pipeline(self):
        store = self.store

        class _P:
            def __init__(self):
                self._ops = []

            def set(self, k, v, ex=None):
                self._ops.append((k, v))
                return self

            def execute(self):
                for k, v in self._ops:
                    store[k] = v

        return _P()


def _cands():
    return [
        {"company": "Альфа", "domain": "alpha.ru", "city": "Москва"},
        {"company": "Бета", "domain": "beta.ru", "city": "Москва"},
    ]


def _setup(monkeypatch, answer):
    fake = _FakeRedis()
    monkeypatch.setattr(llm_filter, "_get_filter_redis", lambda: fake)
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    calls = {"n": 0}

    def fake_chat(*a, **k):
        calls["n"] += 1
        return answer

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    return fake, calls


def test_llm_filter_caches_verdicts(monkeypatch):
    fake, calls = _setup(monkeypatch, '{"keep": [1]}')  # keep #1, drop the rest

    r1 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1, "first run classifies via the LLM"
    assert [c["domain"] for c in r1] == ["alpha.ru"]
    # JSON verdict is complete → keep AND drop are cached, under the llmf2: prefix.
    assert len(fake.store) == 2
    assert all(k.startswith("llmf2:") for k in fake.store)
    assert sorted(fake.store.values()) == ["0", "1"]

    # Both candidates' verdicts are now cached → second run must NOT call the LLM.
    r2 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1, "second run must hit the cache, not the LLM"
    assert [c["domain"] for c in r2] == ["alpha.ru"], "cached verdict preserves keep/drop + order"


def test_llm_filter_config_change_invalidates_cache(monkeypatch):
    fake, calls = _setup(monkeypatch, '{"keep": [1]}')

    llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1
    # Different niche → different config hash → cache miss → LLM runs again.
    llm_filter.filter_candidates_llm(_cands(), "ДРУГАЯ ниша", "Москва", ["сегмент"])
    assert calls["n"] == 2, "a config change must invalidate the cache"


def test_explicit_empty_keep_is_valid_all_rejected_verdict(monkeypatch):
    fake, calls = _setup(monkeypatch, '{"keep": []}')

    r1 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert r1 == []
    # Explicit {"keep": []} is a complete verdict → both drops are cached.
    assert sorted(fake.store.values()) == ["0", "0"]

    r2 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1, "all-rejected verdict must be served from cache"
    assert r2 == []


def test_refusal_mixed_answer_falls_back_to_rules(monkeypatch):
    # Digits mixed with refusal wording: the old parser grabbed ALL digits and
    # kept the listed competitors too. Now this is a parse failure → rule-based
    # fallback for the batch, and NOTHING gets cached.
    fake, calls = _setup(
        monkeypatch, "Подходят 1, 3. Кандидаты 2 и 4 — конкуренты"
    )
    cands = [
        {"company": "Фитнес Альфа", "domain": "alpha.ru", "snippet": "фитнес зал"},
        {"company": "Бета", "domain": "beta.ru", "snippet": "что-то другое"},
    ]
    result = llm_filter.filter_candidates_llm(cands, "фитнес", "Москва", ["фитнес"])
    assert calls["n"] == 1
    # Rule-based fallback: segment match keeps "Фитнес Альфа", drops "Бета".
    assert [c["domain"] for c in result] == ["alpha.ru"]
    assert fake.store == {}, "rule-based verdicts must never be cached"


def test_zero_iz_answer_falls_back_to_rules(monkeypatch):
    # «Подходящих: 0 из 30» used to break the all-rejected heuristic and KEEP
    # candidate #30. Now «0 из» + digits = ambiguous → rule-based fallback.
    fake, calls = _setup(monkeypatch, "Подходящих: 0 из 30")
    result = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1
    assert result == [], "no segment match → strict rule fallback rejects both"
    assert fake.store == {}


def test_omitted_candidates_not_cached_as_drop_on_possible_truncation(monkeypatch):
    # A non-JSON (possibly truncated) answer lists #1 only. The listed keep is
    # explicit and cacheable; the omitted candidate must NOT be cached as drop —
    # it gets re-classified on the next run.
    fake, calls = _setup(monkeypatch, "ПОДХОДЯЩИЕ: 1")

    r1 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1
    assert [c["domain"] for c in r1] == ["alpha.ru"]
    assert list(fake.store.values()) == ["1"], "only the explicit keep is cached"

    # Second run: the omitted candidate is uncached → LLM is called again, and
    # beta (now #1 of the re-classification batch) is kept by the mock answer —
    # proof it was re-classified instead of being served a poisoned cached drop.
    r2 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 2, "omitted candidate must be re-classified, not dropped from cache"
    assert [c["domain"] for c in r2] == ["alpha.ru", "beta.ru"]


def test_numeric_range_answer_expands(monkeypatch):
    fake, calls = _setup(monkeypatch, "Подходят 1-2")
    r1 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert [c["domain"] for c in r1] == ["alpha.ru", "beta.ru"]
    # Keeps are explicit → cached even from the text fallback.
    assert sorted(fake.store.values()) == ["1", "1"]


# ── _parse_keep_answer unit cases ────────────────────────────────────────────

def test_parse_keep_answer_json_variants():
    p = llm_filter._parse_keep_answer
    assert p('{"keep": [1, 3]}', 5) == ({0, 2}, True)
    assert p('Вот ответ: {"keep": [2]}', 5) == ({1}, True)
    assert p('{"keep": []}', 5) == (set(), True)
    # Out-of-range index → verdict not complete (drops must not be cached).
    assert p('{"keep": [1, 99]}', 5) == ({0}, False)
    # Truncated JSON → text fallback: listed digits = explicit keeps, incomplete.
    kept, complete = p('{"keep": [1, 2', 5)
    assert kept == {0, 1} and complete is False
    # Pure garbage → parse failure.
    assert p("ничего не разобрать", 5) is None


def test_parse_keep_answer_text_fallback():
    p = llm_filter._parse_keep_answer
    # Digits after the last «ПОДХОДЯЩИЕ» marker only.
    assert p("Всего 30 кандидатов. ПОДХОДЯЩИЕ: 1, 3", 5) == ({0, 2}, False)
    # Refusal tokens + digits = ambiguous.
    assert p("Подходят 1, 3. Кандидаты 2 и 4 — конкуренты", 5) is None
    assert p("Подходящих: 0 из 30", 30) is None
    # Lone zero / textual refusal = all rejected (but not cacheable as JSON).
    assert p("0", 5) == (set(), False)
    assert p("Нет подходящих", 5) == (set(), False)
    # Range expansion; invalid range fails the batch.
    assert p("ПОДХОДЯЩИЕ: 1-3", 5) == ({0, 1, 2}, False)
    assert p("ПОДХОДЯЩИЕ: 1-9", 5) is None


# ── Rule-based fallback: buyer segments must survive (audit P0 #3) ──────────

def test_rule_fallback_keeps_buyer_segment_drops_competitor():
    # «Продаю овощи для ресторанов»: рестораны — это ПОКУПАТЕЛИ. Раньше корень
    # «рестор» попадал в core_terms и «Ресторан Пушкин» отбраковывался как
    # конкурент (имя + вездесущие маркеры «заказать»/«доставка»).
    candidates = [
        {"company": "Ресторан Пушкин", "domain": "pushkin.ru",
         "snippet": "Заказать столик, доставка блюд"},
        {"company": "Овощная база Опт", "domain": "ovoshbaza.ru",
         "snippet": "Купить овощи оптом со склада, продажа"},
    ]
    kept = llm_filter._rule_based_competitor_filter(
        candidates, "Продаю овощи для ресторанов", "рестораны", ["ресторан", "кафе"]
    )
    names = [c["company"] for c in kept]
    assert "Ресторан Пушкин" in names, "buyer segment must be kept"
    assert "Овощная база Опт" not in names, "obvious competitor must still be dropped"


def test_rule_fallback_synthesized_prompt_skips_competitor_step(monkeypatch):
    # LLM unavailable + empty prompt → filter_candidates_llm synthesizes
    # «{ниша} для {сегменты}» (pure audience text) and must skip Step 1.
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    candidates = [
        {"company": "Ресторан Пушкин", "domain": "pushkin.ru",
         "snippet": "Заказать столик, доставка блюд"},
    ]
    kept = llm_filter.filter_candidates_llm(
        candidates, "рестораны", "Москва", ["ресторан"], prompt=""
    )
    assert [c["company"] for c in kept] == ["Ресторан Пушкин"]


def test_product_keywords_exclude_function_words_and_audience():
    # FIX P1 #4: «для» и прочие служебные слова не должны считаться продуктовыми
    # (иначе порог «2 продуктовых слова» схлопывается в 1); часть после «для» —
    # аудитория; лексика сегментов/ниши вычитается.
    kws = llm_filter._extract_product_keywords(
        "Продаю свежие овощи для ресторанов и кафе", ["ресторан", "кафе"], "рестораны"
    )
    assert "для" not in kws
    assert all(len(w) >= 4 for w in kws)
    assert "овощи" in kws
    assert not any("рестор" in w or w == "кафе" for w in kws)
    assert len(kws) == len(set(kws)), "keywords must be distinct"

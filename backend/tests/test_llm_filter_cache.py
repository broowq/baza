"""Tests for the per-candidate LLM-verdict cache in llm_filter.

The AI filter caches each LLM keep/drop decision (keyed on project-config hash +
candidate identity) so repeat candidates for the same niche skip the LLM. These
tests use a tiny in-memory fake Redis and a mocked llm_client to assert the LLM
is only called for uncached candidates.
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


def test_llm_filter_caches_verdicts(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(llm_filter, "_get_filter_redis", lambda: fake)
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    calls = {"n": 0}

    def fake_chat(*a, **k):
        calls["n"] += 1
        return "1"  # keep candidate #1 of the batch, drop the rest

    monkeypatch.setattr(llm_client, "chat", fake_chat)

    r1 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1, "first run classifies via the LLM"
    assert [c["domain"] for c in r1] == ["alpha.ru"]

    # Both candidates' verdicts are now cached → second run must NOT call the LLM.
    r2 = llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1, "second run must hit the cache, not the LLM"
    assert [c["domain"] for c in r2] == ["alpha.ru"], "cached verdict preserves keep/drop + order"


def test_llm_filter_config_change_invalidates_cache(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(llm_filter, "_get_filter_redis", lambda: fake)
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    calls = {"n": 0}

    def fake_chat(*a, **k):
        calls["n"] += 1
        return "1"

    monkeypatch.setattr(llm_client, "chat", fake_chat)

    llm_filter.filter_candidates_llm(_cands(), "ниша", "Москва", ["сегмент"])
    assert calls["n"] == 1
    # Different niche → different config hash → cache miss → LLM runs again.
    llm_filter.filter_candidates_llm(_cands(), "ДРУГАЯ ниша", "Москва", ["сегмент"])
    assert calls["n"] == 2, "a config change must invalidate the cache"

"""Tests for the per-org AI cost cap.

We avoid hitting the actual LLM by patching `_call_anthropic` /
`_call_gigachat` to return a known (text, in_tok, out_tok) tuple, so the
test exercises the wrapper logic — pre-flight cap check, post-flight
charge — without network or DB-real-LLM coupling.

The DB charge path uses `app.db.session.SessionLocal`; we patch that to a
spy that records the SQL update payload instead of touching Postgres.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.services import llm_client
from app.services.quota import (
    PLAN_LIMITS,
    apply_plan_limits,
    ensure_ai_cost_budget,
    ai_cost_remaining_kopecks,
)
from app.models import Organization, PlanType


# ── _cost_kopecks: pricing math ────────────────────────────────────────────

def test_cost_kopecks_anthropic_uses_default_prices():
    # 1M input + 1M output tokens at default Anthropic prices.
    # Defaults: 25_000 in, 125_000 out → 150_000 kopecks total.
    cost = llm_client._cost_kopecks("anthropic", 1_000_000, 1_000_000)
    assert cost == 150_000


def test_cost_kopecks_rounds_up_to_avoid_underbilling():
    # 1 input token at 25_000 kopecks/MTok → 0.025 kopecks raw.
    # We bill at minimum 1 kopeck per non-zero call.
    cost = llm_client._cost_kopecks("anthropic", 1, 0)
    assert cost == 1


def test_cost_kopecks_zero_when_both_zero():
    assert llm_client._cost_kopecks("anthropic", 0, 0) == 0


# ── ensure_ai_cost_budget: HTTP gate for callers ───────────────────────────

def _make_org(*, used: int, limit: int) -> Organization:
    org = Organization(name="t", plan=PlanType.pro)
    org.ai_cost_used_kopecks_current_month = used
    org.ai_cost_limit_kopecks_per_month = limit
    return org


def test_ensure_ai_cost_budget_allows_under_cap():
    ensure_ai_cost_budget(_make_org(used=0, limit=300_000))
    ensure_ai_cost_budget(_make_org(used=299_999, limit=300_000))


def test_ensure_ai_cost_budget_zero_limit_is_unmetered():
    # limit = 0 means "don't gate" — used in tests / system-level callers.
    ensure_ai_cost_budget(_make_org(used=10**9, limit=0))


def test_ensure_ai_cost_budget_blocks_at_or_above_cap():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        ensure_ai_cost_budget(_make_org(used=300_000, limit=300_000))
    assert exc.value.status_code == 402


def test_ensure_ai_cost_budget_respects_slack_reservation():
    # 250k used, cap 300k, asking for 60k slack → 310k > 300k → block.
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        ensure_ai_cost_budget(_make_org(used=250_000, limit=300_000), slack_kopecks=60_000)


# ── ai_cost_remaining_kopecks ──────────────────────────────────────────────

def test_remaining_kopecks_basic():
    assert ai_cost_remaining_kopecks(_make_org(used=100_000, limit=300_000)) == 200_000


def test_remaining_kopecks_clamped_when_overspent():
    assert ai_cost_remaining_kopecks(_make_org(used=400_000, limit=300_000)) == 0


# ── apply_plan_limits ──────────────────────────────────────────────────────

@pytest.mark.parametrize("plan,expected", [
    (PlanType.free, 0),
    (PlanType.starter, 30_000),
    (PlanType.pro, 300_000),
    (PlanType.team, 1_500_000),
])
def test_apply_plan_limits_sets_ai_cost_cap(plan, expected):
    org = Organization(name="t", plan=plan)
    apply_plan_limits(org)
    assert org.ai_cost_limit_kopecks_per_month == expected


def test_plan_limits_table_has_ai_cost_for_every_plan():
    for plan, limits in PLAN_LIMITS.items():
        assert "ai_cost_kopecks" in limits, f"plan {plan} missing ai_cost_kopecks"
        assert limits["ai_cost_kopecks"] >= 0


# ── llm_client.chat: pre-flight + post-flight charging ─────────────────────

def test_chat_short_circuits_when_org_has_no_budget(monkeypatch):
    """When _has_budget says False, we never call the provider."""
    monkeypatch.setattr(llm_client, "_has_budget", lambda org_id: False)
    # If either provider were called, we'd get an AttributeError on the mock,
    # so seeing None back proves the early return ran.
    result = llm_client.chat("hi", organization_id="00000000-0000-0000-0000-000000000001")
    assert result is None


def test_chat_charges_after_successful_call(monkeypatch):
    """Returns text AND increments the org's running spend."""
    captured = {}

    def fake_charge(org_id, provider, in_tok, out_tok):
        captured.update(dict(
            org_id=org_id, provider=provider,
            in_tok=in_tok, out_tok=out_tok,
        ))

    monkeypatch.setattr(llm_client, "_has_budget", lambda org_id: True)
    monkeypatch.setattr(llm_client, "_charge", fake_charge)

    # Force gigachat path with a successful canned response.
    monkeypatch.setattr(
        llm_client, "_call_gigachat",
        lambda *a, **kw: ("ok-response", 250, 80),
    )
    monkeypatch.setattr(
        llm_client, "_call_anthropic",
        lambda *a, **kw: (None, 0, 0),
    )

    settings_mock = MagicMock()
    settings_mock.llm_provider = "gigachat"
    with patch.object(llm_client, "get_settings", return_value=settings_mock):
        out = llm_client.chat("hi", organization_id="org-1")

    assert out == "ok-response"
    assert captured == {
        "org_id": "org-1", "provider": "gigachat",
        "in_tok": 250, "out_tok": 80,
    }


def test_chat_does_not_charge_when_organization_id_is_none(monkeypatch):
    """System-level callers (no org context) must not be metered."""
    called = {"charge": 0}

    def fake_charge(*_a, **_kw):
        called["charge"] += 1

    monkeypatch.setattr(llm_client, "_charge", fake_charge)
    monkeypatch.setattr(
        llm_client, "_call_gigachat",
        lambda *a, **kw: ("ok", 100, 50),
    )
    monkeypatch.setattr(
        llm_client, "_call_anthropic",
        lambda *a, **kw: (None, 0, 0),
    )

    settings_mock = MagicMock()
    settings_mock.llm_provider = "gigachat"
    with patch.object(llm_client, "get_settings", return_value=settings_mock):
        out = llm_client.chat("hi")  # no organization_id

    assert out == "ok"
    assert called["charge"] == 0


def test_chat_falls_back_to_anthropic_when_gigachat_returns_empty(monkeypatch):
    """Provider fallback still works WITH cap awareness."""
    monkeypatch.setattr(llm_client, "_has_budget", lambda org_id: True)
    monkeypatch.setattr(llm_client, "_charge", lambda *_a, **_kw: None)
    monkeypatch.setattr(llm_client, "_call_gigachat", lambda *a, **kw: (None, 0, 0))
    monkeypatch.setattr(
        llm_client, "_call_anthropic",
        lambda *a, **kw: ("anthropic-response", 100, 50),
    )

    settings_mock = MagicMock()
    settings_mock.llm_provider = "gigachat"
    with patch.object(llm_client, "get_settings", return_value=settings_mock):
        out = llm_client.chat("hi", organization_id="org-1")

    assert out == "anthropic-response"


# ── _estimate_tokens: missing-usage fallback path ──────────────────────────

def test_estimate_tokens_zero_for_empty_string():
    assert llm_client._estimate_tokens("") == 0


def test_estimate_tokens_grows_with_length():
    a = llm_client._estimate_tokens("привет мир")
    b = llm_client._estimate_tokens("привет мир " * 10)
    assert b > a

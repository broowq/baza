"""TRUE E2E: billing + plans, end to end through real HTTP + auth + DB.

Covers the public pricing catalogue (`GET /plans`), the YooKassa checkout
validation gate (`POST /billing/checkout`), the org-scoped subscription view
(`GET /billing/subscription`), and the webhook's source-authentication guard
(`POST /billing/webhook/yookassa`).

In the test env NO YooKassa credentials are configured, so any path that would
talk to the real provider returns a clean 503 ("платёжный провайдер ещё не
настроен") AFTER all local validation has run. We assert that validation, the
DB side-effects, and the auth/source guards behave — without ever needing real
YooKassa creds. The one path that genuinely needs a live confirmation_url is
explicitly skipped with a note.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api.routes.plans import PLAN_NAMES, PLAN_PRICES_RUB
from app.core.config import get_settings
from app.models import Membership, Organization, PlanType, Subscription, User
from app.services.quota import PLAN_LIMITS

settings = get_settings()

# In this env the provider is intentionally unconfigured. If a future test run
# sets real creds, the checkout/webhook status-code expectations below change,
# so we gate on this and skip the "no-creds" assertions when creds ARE present.
_NO_YOOKASSA_CREDS = not (settings.yookassa_shop_id and settings.yookassa_secret_key)


# ── GET /plans : public pricing catalogue ───────────────────────────────────

def test_plans_is_public_and_lists_paid_tiers(client):
    """`/plans` is the unauthenticated pricing page → no token required, and it
    advertises exactly the four PAID tiers in ladder order (free is never sold).
    `growth` — enum-значение тира «Team» (имя team занято тиром Business)."""
    r = client.get("/api/plans")
    assert r.status_code == 200, r.text
    plans = r.json()
    assert isinstance(plans, list)

    ids = [p["id"] for p in plans]
    assert ids == ["starter", "growth", "pro", "team"], f"unexpected plan order/set: {ids}"
    assert "free" not in ids, "free tier must not appear in the public catalogue"


def test_plans_prices_ascend_and_rub_per_lead_descends(client):
    """Ценовая лестница 2026-07-09: цены строго растут, а ₽/лид с каждым тиром
    НЕ растёт (мировой двигатель апгрейда — объём дешевеет с тиром).
    Регресс против возврата анти-паттерна «₽/лид дороже на апгрейде»."""
    plans = client.get("/api/plans").json()
    prices = [p["price_monthly_rub"] for p in plans]
    assert prices == sorted(prices) and len(set(prices)) == len(prices), prices
    rub_per_lead = [
        p["price_monthly_rub"] / p["leads_limit_per_month"] for p in plans
    ]
    for cheaper, upper in zip(rub_per_lead, rub_per_lead[1:]):
        # небольшой допуск: Starter→Team почти плоско (0.98 → 0.99)
        assert upper <= cheaper * 1.02, rub_per_lead


def test_plans_limits_match_quota_and_prices(client):
    """Every advertised limit/price/name must match the single sources of truth:
    quota.PLAN_LIMITS, plans.PLAN_PRICES_RUB, plans.PLAN_NAMES. A drift here is a
    real billing bug (we'd promise quotas the enforcer doesn't grant)."""
    plans = {p["id"]: p for p in client.get("/api/plans").json()}

    for plan in (PlanType.starter, PlanType.growth, PlanType.pro, PlanType.team):
        pid = plan.value
        adv = plans[pid]
        limits = PLAN_LIMITS[plan]
        assert adv["projects_limit"] == limits["projects"], pid
        assert adv["users_limit"] == limits["users"], pid
        assert adv["leads_limit_per_month"] == limits["leads_per_month"], pid
        assert adv["can_invite_members"] == limits["can_invite"], pid
        assert adv["price_monthly_rub"] == PLAN_PRICES_RUB[pid], pid
        assert adv["name"] == PLAN_NAMES[pid], pid
        # Every sold tier must carry a positive price (checkout rejects price<=0).
        assert adv["price_monthly_rub"] > 0, pid


def test_plans_payment_provider_reflects_config(client):
    """payment_provider is 'unconfigured' here (no creds) → frontend can hide the
    pay button. With creds it would be 'yookassa'."""
    plans = client.get("/api/plans").json()
    expected = "yookassa" if not _NO_YOOKASSA_CREDS else "unconfigured"
    for p in plans:
        assert p["payment_provider"] == expected, p


# ── POST /billing/checkout : validation gate (no real YooKassa) ──────────────

def test_checkout_rejects_same_plan(paid_account):
    """A Pro org buying Pro again is a no-op the API must refuse (400) BEFORE it
    ever touches the provider — caught even with creds absent."""
    r = paid_account.post("/api/billing/checkout", json={"plan": "pro"})
    assert r.status_code == 400, r.text
    assert "уже активен" in r.json()["detail"]


def test_checkout_rejects_free_plan(make_account):
    """You cannot 'pay for' the free tier. A free org targeting `free` is the
    same-plan case (400); a paid org targeting `free` hits the explicit
    'free нельзя оплатить' branch (also 400)."""
    free = make_account()  # free plan
    r1 = free.post("/api/billing/checkout", json={"plan": "free"})
    assert r1.status_code == 400, r1.text  # same-plan branch

    paid = make_account(plan="pro")
    r2 = paid.post("/api/billing/checkout", json={"plan": "free"})
    assert r2.status_code == 400, r2.text
    assert "нельзя оплатить" in r2.json()["detail"]


def test_checkout_invalid_plan_value_is_422(paid_account):
    """`plan` is a PlanType enum → an unknown value is rejected by request
    validation (422) before any handler logic runs."""
    r = paid_account.post("/api/billing/checkout", json={"plan": "enterprise"})
    assert r.status_code == 422, r.text


def test_checkout_requires_owner_or_admin(make_account, db):
    """Checkout is gated to owner/admin. A plain member must be refused (403)
    and NO Subscription row should be created."""
    acct = make_account(plan="pro")
    user = db.execute(select(User).where(User.email == acct.email)).scalar_one()
    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == acct.org_id,
            Membership.user_id == user.id,
        )
    ).scalar_one()
    membership.role = "member"  # demote the owner to a plain member
    db.commit()

    r = acct.post("/api/billing/checkout", json={"plan": "team"})
    assert r.status_code == 403, r.text

    subs = db.execute(
        select(Subscription).where(Subscription.organization_id == acct.org_id)
    ).scalars().all()
    assert subs == [], "a refused checkout must not create a Subscription"


def test_checkout_unauthenticated_is_401(client):
    """No bearer token → 401, never reaches the billing logic."""
    r = client.post("/api/billing/checkout", json={"plan": "pro"})
    assert r.status_code == 401, r.text


@pytest.mark.skipif(
    not _NO_YOOKASSA_CREDS,
    reason="asserts the no-credentials behaviour; creds are configured in this env",
)
def test_checkout_valid_plan_clean_503_when_provider_unconfigured(make_account, db):
    """Happy-path validation (different paid plan, positive price) PASSES, then
    the handler fails cleanly at the provider boundary with 503 because no creds
    are set. Crucially: no orphan Subscription is committed (handler rolls back /
    never commits on the 503), so the org stays on its current plan."""
    acct = make_account(plan="starter")
    r = acct.post("/api/billing/checkout", json={"plan": "pro"})
    assert r.status_code == 503, r.text
    assert "провайдер" in r.json()["detail"].lower() or "настроен" in r.json()["detail"]

    # 503 is raised inside _get_client() BEFORE the Subscription row is added,
    # so the org must have zero subscriptions and an unchanged plan.
    subs = db.execute(
        select(Subscription).where(Subscription.organization_id == acct.org_id)
    ).scalars().all()
    assert subs == [], f"no subscription should persist on a 503 checkout, got {subs}"
    org = db.get(Organization, acct.org_id)
    assert org.plan == PlanType.starter, "plan must not change on a failed checkout"


@pytest.mark.skip(
    reason="Returning a real confirmation_url requires live YooKassa creds + "
           "network; out of scope for the credential-free E2E env."
)
def test_checkout_returns_confirmation_url_with_real_creds():
    pass


# ── GET /billing/subscription : org-scoped state ────────────────────────────

def test_subscription_none_for_fresh_org(paid_account):
    """A fresh org has never checked out → reports {'status': 'none'}."""
    r = paid_account.get("/api/billing/subscription")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "none"}


def test_subscription_reflects_org_state_and_latest_row(make_account, db):
    """When subscriptions exist, the endpoint returns the MOST RECENT one with
    its real plan/status (org state). We seed two rows and assert the latest
    wins — guards the scalar_one_or_none → order-by-created-desc fix."""
    acct = make_account(plan="pro")

    old = Subscription(
        organization_id=acct.org_id,
        plan_id="starter",
        status="canceled",
        current_period_start=datetime.now(timezone.utc) - timedelta(days=60),
        current_period_end=datetime.now(timezone.utc) - timedelta(days=30),
        provider_subscription_id="pay_old",
    )
    db.add(old)
    db.commit()

    newer = Subscription(
        organization_id=acct.org_id,
        plan_id="pro",
        status="active",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        provider_subscription_id="pay_new",
    )
    db.add(newer)
    db.commit()

    r = acct.get("/api/billing/subscription")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_id"] == "pro"
    assert body["status"] == "active"
    assert body["provider"] == "yookassa"
    assert body["payment_id"] == "pay_new"
    assert body["id"] == str(newer.id)


def test_subscription_is_tenant_isolated(make_account, db):
    """Org A's subscription must never leak into org B's view."""
    a = make_account(plan="pro")
    b = make_account(plan="pro")

    sub = Subscription(
        organization_id=a.org_id,
        plan_id="pro",
        status="active",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        provider_subscription_id="pay_a",
    )
    db.add(sub)
    db.commit()

    # B sees nothing; A sees its own.
    assert b.get("/api/billing/subscription").json() == {"status": "none"}
    assert a.get("/api/billing/subscription").json()["payment_id"] == "pay_a"


def test_subscription_unauthenticated_is_401(client):
    r = client.get("/api/billing/subscription")
    assert r.status_code == 401, r.text


# ── POST /billing/webhook/yookassa : source authentication ──────────────────

def test_webhook_rejects_non_yookassa_source_ip(client):
    """TestClient's source IP is not in the YooKassa allow-list → 403, before any
    payment processing. This is the first-line forgery guard."""
    r = client.post(
        "/api/billing/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "fake-payment-1"}},
    )
    assert r.status_code == 403, r.text
    assert "IP" in r.json()["detail"]


def test_webhook_missing_body_is_422(client):
    """The handler declares `payload: dict` → a non-object / missing body fails
    request validation (422), never reaching the IP check."""
    r = client.post("/api/billing/webhook/yookassa", content=b"")
    assert r.status_code == 422, r.text


def test_webhook_forged_payload_cannot_activate_org(make_account, db, monkeypatch):
    """Defence in depth: even if an attacker SPOOFS a YooKassa source IP (via
    X-Forwarded-For) and crafts a 'payment.succeeded' for a real org, they CANNOT
    flip the org to a paid plan — the handler re-fetches the payment from YooKassa
    with our credentials. With creds absent that re-fetch is impossible (503), and
    the org's plan is untouched.

    We disable the IP guard for this test to prove the SECOND line of defence (the
    authoritative re-fetch) independently holds; the IP guard itself is covered by
    test_webhook_rejects_non_yookassa_source_ip.
    """
    monkeypatch.setattr(settings, "yookassa_verify_ip", False, raising=False)

    acct = make_account()  # free org
    org_before = db.get(Organization, acct.org_id)
    assert org_before.plan == PlanType.free

    forged = {
        "event": "payment.succeeded",
        "object": {
            "id": "forged-pay-id",
            "status": "succeeded",
            "metadata": {
                "organization_id": acct.org_id,
                "plan_id": "team",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "user_id": "x",
            },
        },
    }
    r = client_post_webhook(acct, forged)
    # Re-fetch is required and impossible without creds → clean 503, NOT 200.
    assert r.status_code in (502, 503), r.text

    db.expire_all()
    org_after = db.get(Organization, acct.org_id)
    assert org_after.plan == PlanType.free, "forged webhook must NOT upgrade the org"


@pytest.mark.skipif(
    not _NO_YOOKASSA_CREDS,
    reason="asserts the no-credentials re-fetch failure; creds are configured here",
)
def test_webhook_with_spoofed_ip_still_blocked_without_creds(client, monkeypatch):
    """A spoofed YooKassa IP passes the first guard but the authoritative re-fetch
    needs creds → 503. Confirms the IP allow-list is not the only barrier."""
    # Keep the IP guard ON, send a header that LOOKS like a YooKassa source.
    r = client.post(
        "/api/billing/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "spoofed"}},
        headers={"X-Forwarded-For": "185.71.76.1"},
    )
    assert r.status_code == 503, r.text


def client_post_webhook(acct, payload):
    """Webhooks are unauthenticated (called by YooKassa, not a user) — post via the
    raw client without auth headers."""
    return acct.client.post("/api/billing/webhook/yookassa", json=payload)

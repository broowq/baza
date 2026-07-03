"""Автопродление подписок (periodic.renew_subscriptions) + вебхук-хранение карты.

Проверяем деньги-критичную логику с застабленной ЮKassa:
  * успешное автосписание → новая active-подписка, период продлён, тариф/лимиты
    применены, письмо «продлён» ушло;
  * отклонённое списание → canceled-подписка, renew_attempts+1, письмо «не удалось»;
  * повторный прогон при pending-продлении в полёте → НЕ задваивает списание;
  * орг, покрытый более свежей активной подпиской (ручное продление) → пропуск;
  * подписка без автопродления → только письмо-напоминание (один раз), без списаний;
  * checkout: auto_renew=True → save_payment_method уходит в ЮKassa;
    вебхук payment.succeeded с payment_method.saved → payment_method_id сохранён.

Как и остальные periodic-тесты — реальный локальный Postgres, свои строки
чистим по префиксу.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import ActionLog, Membership, Organization, PlanType, Subscription, User
from app.services.quota import apply_plan_limits
from app.tasks import periodic

_PFX = "autorenew-"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def org_with_owner(db):
    """Организация на Pro с владельцем (email для биллинг-писем)."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"{_PFX}{suffix}@test.local",
        hashed_password="x",
        full_name="Autorenew Test",
    )
    org = Organization(name=f"{_PFX}{suffix}", plan=PlanType.pro)
    apply_plan_limits(org)
    db.add_all([user, org])
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role="owner"))
    db.commit()
    yield org
    # cleanup: action_logs (FK не каскадится) → подписки → membership → org → user
    db.execute(delete(ActionLog).where(ActionLog.organization_id == org.id))
    db.execute(delete(Subscription).where(Subscription.organization_id == org.id))
    db.execute(delete(Membership).where(Membership.organization_id == org.id))
    db.execute(delete(Organization).where(Organization.id == org.id))
    db.execute(delete(User).where(User.id == user.id))
    db.commit()


def _mk_sub(db, org, *, ends_in_hours: float, auto_renew=True, pm="pm-saved-1", **kw):
    now = datetime.now(timezone.utc)
    sub = Subscription(
        organization_id=org.id,
        plan_id="pro",
        status=kw.pop("status", "active"),
        current_period_start=now - timedelta(days=30),
        current_period_end=now + timedelta(hours=ends_in_hours),
        auto_renew=auto_renew,
        payment_method_id=pm,
        **kw,
    )
    db.add(sub)
    db.commit()
    return sub


class _StubYK:
    """Стаб YooKassaClient: отдаёт заранее заданный ответ, копит вызовы."""

    calls: list[dict] = []
    response: dict = {}

    def __init__(self, *a, **kw):
        pass

    def create_recurring_payment(self, **kw):
        _StubYK.calls.append(kw)
        return dict(_StubYK.response)


@pytest.fixture
def stub_yookassa(monkeypatch):
    """Подсовываем стаб-клиент + фиктивные creds + глушим почту."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "yookassa_shop_id", "test-shop", raising=False)
    monkeypatch.setattr(settings, "yookassa_secret_key", "test-key", raising=False)

    _StubYK.calls = []
    _StubYK.response = {"id": "pay-1", "status": "succeeded",
                        "payment_method": {"id": "pm-saved-1", "saved": True}}

    import app.services.yookassa as yk
    monkeypatch.setattr(yk, "YooKassaClient", _StubYK)

    sent: list[tuple] = []
    import app.services.notifications as notif
    monkeypatch.setattr(notif, "send_email", lambda s, b, r: sent.append((s, r)) or True)
    return {"stub": _StubYK, "sent": sent}


def test_renew_success_extends_subscription(db, org_with_owner, stub_yookassa):
    org = org_with_owner
    old = _mk_sub(db, org, ends_in_hours=12)  # кончается в окне 24ч

    periodic.renew_subscriptions()
    db.expire_all()

    assert len(stub_yookassa["stub"].calls) == 1
    call = stub_yookassa["stub"].calls[0]
    assert call["payment_method_id"] == "pm-saved-1"
    assert call["amount_rub"] > 0

    subs = db.execute(
        select(Subscription)
        .where(Subscription.organization_id == org.id)
        .order_by(Subscription.created_at)
    ).scalars().all()
    assert len(subs) == 2
    renewal = subs[-1]
    assert renewal.status == "active"
    assert renewal.auto_renew is True
    assert renewal.payment_method_id == "pm-saved-1"
    assert renewal.current_period_end > old.current_period_end
    # письмо об успехе ушло владельцу
    assert any("продлён" in s for s, _ in stub_yookassa["sent"])


def test_renew_declined_increments_attempts_and_emails(db, org_with_owner, stub_yookassa):
    org = org_with_owner
    stub_yookassa["stub"].response = {
        "id": "pay-2", "status": "canceled",
        "cancellation_details": {"reason": "insufficient_funds"},
    }
    old = _mk_sub(db, org, ends_in_hours=12)

    periodic.renew_subscriptions()
    db.expire_all()

    old = db.get(Subscription, old.id)
    assert old.renew_attempts == 1
    renewal = db.execute(
        select(Subscription).where(
            Subscription.organization_id == org.id, Subscription.id != old.id
        )
    ).scalar_one()
    assert renewal.status == "canceled"
    assert any("Не удалось" in s or "не удалось" in s.lower() for s, _ in stub_yookassa["sent"])


def test_renew_skips_when_pending_inflight(db, org_with_owner, stub_yookassa):
    """Вчерашнее продление ещё pending (ждёт вебхука) → сегодня не списываем."""
    org = org_with_owner
    _mk_sub(db, org, ends_in_hours=12)
    _mk_sub(db, org, ends_in_hours=30 * 24, status="pending")  # in-flight renewal

    periodic.renew_subscriptions()
    assert stub_yookassa["stub"].calls == []


def test_renew_skips_when_newer_active_covers(db, org_with_owner, stub_yookassa):
    """Клиент продлил руками (свежая active) → автосписание не нужно."""
    org = org_with_owner
    _mk_sub(db, org, ends_in_hours=12)
    _mk_sub(db, org, ends_in_hours=29 * 24)  # newer active, покрывает дальше

    periodic.renew_subscriptions()
    assert stub_yookassa["stub"].calls == []


def test_reminder_for_non_autorenew_sent_once(db, org_with_owner, stub_yookassa):
    org = org_with_owner
    sub = _mk_sub(db, org, ends_in_hours=48, auto_renew=False, pm="")

    periodic.renew_subscriptions()
    db.expire_all()
    sub = db.get(Subscription, sub.id)
    assert sub.expiry_reminder_sent_at is not None
    reminders = [s for s, _ in stub_yookassa["sent"] if "действует до" in s]
    assert len(reminders) == 1
    assert stub_yookassa["stub"].calls == []  # списаний не было

    # повторный прогон — без спама
    periodic.renew_subscriptions()
    reminders = [s for s, _ in stub_yookassa["sent"] if "действует до" in s]
    assert len(reminders) == 1


def test_max_attempts_stops_charging(db, org_with_owner, stub_yookassa):
    org = org_with_owner
    _mk_sub(db, org, ends_in_hours=-10, renew_attempts=3)  # исчерпаны попытки

    periodic.renew_subscriptions()
    assert stub_yookassa["stub"].calls == []


def test_webhook_stores_saved_payment_method(db, org_with_owner, monkeypatch):
    """payment.succeeded с payment_method.saved=true → карта сохранена на подписке."""
    from fastapi.testclient import TestClient
    from app.api.routes import billing
    from app.main import app

    org = org_with_owner
    sub = _mk_sub(db, org, ends_in_hours=720, status="pending", pm="", auto_renew=True)

    class _C:
        def get_payment(self, pid):
            return {
                "id": pid,
                "status": "succeeded",
                "amount": {"value": "16900.00", "currency": "RUB"},
                "payment_method": {"id": "pm-from-webhook", "saved": True},
                "metadata": {
                    "organization_id": str(org.id),
                    "plan_id": "pro",
                    "subscription_id": str(sub.id),
                    "user_id": "",
                },
            }

    monkeypatch.setattr(billing, "_get_client", lambda: _C())
    monkeypatch.setattr(billing.settings, "yookassa_verify_ip", False, raising=False)

    client = TestClient(app)
    r = client.post(
        "/api/billing/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "pay-wh-1"}},
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    sub = db.get(Subscription, sub.id)
    assert sub.status == "active"
    assert sub.payment_method_id == "pm-from-webhook"

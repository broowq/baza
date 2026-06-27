"""TRUE end-to-end tests for the lead-card communication surface.

Covers the "work a lead from the lead card" routes that land on top of the
existing outreach plumbing:

  * POST /api/leads/{id}/email   — reply to a lead by email through the org SMTP
  * POST /api/leads/{id}/touch   — log a one-click call/WhatsApp/Telegram touch
  * GET  /api/crm/leads/{id}/activities — unified timeline incl. sent email +
                                           inbound reply

Drives the real FastAPI app via the e2e harness (real auth → DB), with lead
collection stubbed at the jobs.py seam and the SMTP sender monkeypatched so no
real mail leaves the box. Leads' email / opt-out / company are set directly via
the db fixture for determinism.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models import (
    Lead,
    LeadActivity,
    LeadStatus,
    OutreachMessage,
    OutreachReply,
)


# ── helpers (mirrored from test_e2e_outreach.py) ─────────────────────────────

def _niche() -> str:
    """A niche unique to this collect so the shared warehouse stays isolated."""
    return f"commнiша{uuid.uuid4().hex[:8]}"


def _now_naive() -> datetime:
    """Naive-UTC 'now' to match the DateTime (no-tz) columns the models use."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _collect_leads(acct, new_project, *, niche, n=1):
    """Create a project under a unique niche and collect a dose of leads.

    Returns (project_id, [lead_row_dict, ...]) from the table endpoint.
    """
    project = new_project(acct, niche=niche)
    pid = project["id"]
    r = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": max(n + 2, 10)})
    assert r.status_code in (200, 201), r.text
    table = acct.get(f"/api/leads/project/{pid}/table?per_page=50")
    assert table.status_code == 200, table.text
    items = table.json()["items"]
    assert len(items) >= n, f"collect delivered too few leads ({len(items)}): {table.json()}"
    return pid, items


def _set_lead_fields(db, lead_id, **fields):
    """Set raw columns on a Lead (email / email_opt_out / company / status)."""
    lead = db.get(Lead, uuid.UUID(str(lead_id)))
    assert lead is not None, f"lead {lead_id} not found"
    for k, v in fields.items():
        setattr(lead, k, v)
    db.commit()


def _configure_settings(acct, *, host="example.com"):
    """PUT a fully-configured OrgEmailSettings for the account's org (sets the
    smtp_host the /email route checks for)."""
    payload = {
        "from_name": "Отдел продаж БАЗА",
        "from_email": f"sales@{host}",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": f"sales@{host}",
        "smtp_password": "s3cr3t-smtp-pw",
        "smtp_use_tls": True,
        "daily_limit": 200,
    }
    r = acct.request("PUT", "/api/outreach/settings", json=payload)
    assert r.status_code == 200, f"settings PUT failed: {r.status_code} {r.text}"
    return payload


@pytest.fixture
def fake_smtp(monkeypatch):
    """Record calls to the SMTP sender; never touch the network.

    The /leads/{id}/email route does `from app.services import outreach` then
    `outreach.send_via_smtp(...)` — an attribute lookup on the module object, so
    patching the name on app.services.outreach is picked up at call time."""
    calls: list[dict] = []

    def _send(s, *, to_email, subject, html_body, text_body, unsub_url=None):
        calls.append({
            "to_email": to_email,
            "subject": subject,
            "html_body": html_body,
            "text_body": text_body,
            "unsub_url": unsub_url,
        })
        return "<fake-lead-msgid>"

    import app.services.outreach as outreach_svc
    monkeypatch.setattr(outreach_svc, "send_via_smtp", _send, raising=True)
    return calls


# ─────────────────────────────────────────────────────────────────────────────
# 1) Email send happy path: row created, lead bumped new→contacted
# ─────────────────────────────────────────────────────────────────────────────

def test_email_send_creates_message_and_bumps_lead(
    paid_account, stub_sources, new_project, db, fake_smtp
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(
        db, lead_id, email="lead@example.com", email_opt_out=False, status=LeadStatus.new
    )

    r = acct.post(
        f"/api/leads/{lead_id}/email",
        json={"subject": "Здравствуйте", "body": "Предлагаем сотрудничество."},
    )
    assert r.status_code in (200, 201), f"email send failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("status") == "sent", body

    # The fake sender was called once, to the lead's address.
    assert len(fake_smtp) == 1, fake_smtp
    assert fake_smtp[0]["to_email"] == "lead@example.com"
    assert fake_smtp[0]["subject"] == "Здравствуйте"

    # An OutreachMessage row exists: lead_id set, enrollment_id None, status sent,
    # non-empty track_token.
    db.expire_all()
    msgs = (
        db.query(OutreachMessage)
        .filter(OutreachMessage.lead_id == uuid.UUID(str(lead_id)))
        .all()
    )
    assert len(msgs) == 1, msgs
    msg = msgs[0]
    assert msg.enrollment_id is None
    assert msg.status == "sent"
    assert msg.track_token, "track_token must be set for open/click tracking"
    assert msg.to_email == "lead@example.com"

    # Lead bumped: last_contacted_at set, status new → contacted.
    lead = db.get(Lead, uuid.UUID(str(lead_id)))
    assert lead.last_contacted_at is not None
    assert lead.status == LeadStatus.contacted, lead.status


# ─────────────────────────────────────────────────────────────────────────────
# 2) Email send guards: opted-out → 409, no email → 422, no settings → 409
# ─────────────────────────────────────────────────────────────────────────────

def test_email_send_opted_out_returns_409(
    paid_account, stub_sources, new_project, db, fake_smtp
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(db, lead_id, email="opt@example.com", email_opt_out=True)

    r = acct.post(
        f"/api/leads/{lead_id}/email",
        json={"subject": "Привет", "body": "Тело"},
    )
    assert r.status_code == 409, f"opted-out must 409, got {r.status_code}: {r.text}"
    assert len(fake_smtp) == 0, "no mail must be sent to an opted-out lead"


def test_email_send_no_email_returns_422(
    paid_account, stub_sources, new_project, db, fake_smtp
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(db, lead_id, email="", email_opt_out=False)

    r = acct.post(
        f"/api/leads/{lead_id}/email",
        json={"subject": "Привет", "body": "Тело"},
    )
    assert r.status_code == 422, f"no-email must 422, got {r.status_code}: {r.text}"
    assert len(fake_smtp) == 0


def test_email_send_unconfigured_org_returns_409(
    paid_account, stub_sources, new_project, db, fake_smtp
):
    # NOTE: no _configure_settings() — the org has no OrgEmailSettings row.
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(db, lead_id, email="lead@example.com", email_opt_out=False)

    r = acct.post(
        f"/api/leads/{lead_id}/email",
        json={"subject": "Привет", "body": "Тело"},
    )
    assert r.status_code == 409, f"unconfigured org must 409, got {r.status_code}: {r.text}"
    assert len(fake_smtp) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3) Touch: logs a kind="touch" activity with meta.channel; bad channel → 422
# ─────────────────────────────────────────────────────────────────────────────

def test_touch_logs_activity_with_channel(
    paid_account, stub_sources, new_project, db
):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(db, lead_id, status=LeadStatus.new)

    r = acct.post(
        f"/api/leads/{lead_id}/touch",
        json={"channel": "whatsapp", "note": "Написал в WhatsApp"},
    )
    assert r.status_code in (200, 201), f"touch failed: {r.status_code} {r.text}"
    assert r.json().get("ok") is True, r.json()

    # A LeadActivity kind="touch" with meta.channel == "whatsapp" exists.
    db.expire_all()
    acts = (
        db.query(LeadActivity)
        .filter(
            LeadActivity.lead_id == uuid.UUID(str(lead_id)),
            LeadActivity.kind == "touch",
        )
        .all()
    )
    assert len(acts) == 1, acts
    assert (acts[0].meta or {}).get("channel") == "whatsapp", acts[0].meta

    # Side effects: last_contacted_at set, status new → contacted.
    lead = db.get(Lead, uuid.UUID(str(lead_id)))
    assert lead.last_contacted_at is not None
    assert lead.status == LeadStatus.contacted, lead.status


def test_touch_bad_channel_returns_422(
    paid_account, stub_sources, new_project, db
):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]

    r = acct.post(
        f"/api/leads/{lead_id}/touch",
        json={"channel": "carrier-pigeon"},
    )
    assert r.status_code == 422, f"bad channel must 422, got {r.status_code}: {r.text}"

    # Nothing was logged for this lead.
    db.expire_all()
    acts = (
        db.query(LeadActivity)
        .filter(
            LeadActivity.lead_id == uuid.UUID(str(lead_id)),
            LeadActivity.kind == "touch",
        )
        .all()
    )
    assert acts == [], acts


# ─────────────────────────────────────────────────────────────────────────────
# 4) Unified timeline: sent email surfaces as email_sent; reply as email_in
# ─────────────────────────────────────────────────────────────────────────────

def test_activities_timeline_includes_email_sent_and_email_in(
    paid_account, stub_sources, new_project, db, fake_smtp
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(
        db, lead_id, email="lead@example.com", email_opt_out=False, status=LeadStatus.new
    )

    # Send an email from the lead card → produces an OutreachMessage.
    r = acct.post(
        f"/api/leads/{lead_id}/email",
        json={"subject": "Коммерческое предложение", "body": "Текст письма."},
    )
    assert r.status_code in (200, 201), r.text

    # Seed an inbound reply for the same lead (as the IMAP poller would).
    reply = OutreachReply(
        organization_id=uuid.UUID(str(acct.org_id)),
        lead_id=uuid.UUID(str(lead_id)),
        from_email="lead@example.com",
        subject="Re: Коммерческое предложение",
        snippet="Спасибо, интересно — давайте созвонимся.",
        received_at=_now_naive(),
    )
    db.add(reply)
    db.commit()

    # The unified timeline carries both, with the right kinds.
    tl = acct.get(f"/api/crm/leads/{lead_id}/activities")
    assert tl.status_code == 200, tl.text
    rows = tl.json()
    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)

    sent = by_kind.get("email_sent", [])
    assert len(sent) == 1, f"expected one email_sent, got {by_kind}"
    assert sent[0]["text"] == "Коммерческое предложение", sent[0]
    assert sent[0]["meta"].get("status") == "sent", sent[0]

    inbound = by_kind.get("email_in", [])
    assert len(inbound) == 1, f"expected one email_in, got {by_kind}"
    assert inbound[0]["user_name"] == "lead@example.com", inbound[0]
    assert "созвонимся" in inbound[0]["text"], inbound[0]

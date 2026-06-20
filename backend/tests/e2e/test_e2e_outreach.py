"""TRUE end-to-end tests for the email-outreach feature.

Drives the real FastAPI app via the e2e harness (real auth → DB), with lead
collection stubbed at the jobs.py seam. Routes (/api/outreach/*) and the Celery
tasks (app/tasks/outreach_tasks.py) are landed in parallel by sibling agents;
these tests are written strictly to the spec and go green once they exist.

NEVER sends real email: the SMTP sender + the IMAP test are monkeypatched, and
within_send_window is forced True so the worker always runs regardless of the
wall clock. Leads' emails are set directly via the db fixture for determinism.

Spec covered (each its own test):
  1) Settings PUT/GET — password encrypted at rest, never echoed, keep-on-reput
  2) Settings test endpoint → verified=True
  3) Sequence CRUD (2 steps, list, PATCH replaces steps, DELETE)
  4) Enroll — emailable counted, no-email/opted-out skipped, dup skipped, 400 unconfigured
  5) Worker send — template render, unsubscribe URL, message row, cursor advance, sent_today
  6) Opt-out skip — active enrollment on an opted-out lead → unsubscribed, no send
  7) Unsubscribe route (unauth) — opts the lead out; unknown token → 200, no leak
  8) Daily limit — limit reached → 0 new sends this cycle
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Lead,
    OrgEmailSettings,
    OutreachMessage,
    SequenceEnrollment,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _niche() -> str:
    """A niche unique to this collect so the shared warehouse stays isolated."""
    return f"outнiша{uuid.uuid4().hex[:8]}"


def _now_naive() -> datetime:
    """Naive-UTC 'now' to match the DateTime (no-tz) columns the models use."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _collect_leads(acct, new_project, *, niche, n=3):
    """Create a project under a unique niche and collect a dose of leads.

    Returns (project_id, [lead_row_dict, ...]) score-sorted from the table.
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
    """Set raw columns on a Lead (email / email_opt_out) for determinism."""
    lead = db.get(Lead, uuid.UUID(str(lead_id)))
    assert lead is not None, f"lead {lead_id} not found"
    for k, v in fields.items():
        setattr(lead, k, v)
    db.commit()


def _configure_settings(acct, *, to_email_host="example.com"):
    """PUT a fully-configured OrgEmailSettings for the account's org."""
    payload = {
        "from_name": "Отдел продаж БАЗА",
        "from_email": f"sales@{to_email_host}",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": f"sales@{to_email_host}",
        "smtp_password": "s3cr3t-smtp-pw",
        "smtp_use_tls": True,
        "daily_limit": 200,
    }
    # Account exposes a generic .request(); settings use PUT (no .put helper).
    r = acct.request("PUT", "/api/outreach/settings", json=payload)
    assert r.status_code == 200, f"settings PUT failed: {r.status_code} {r.text}"
    return payload


def _make_sequence(acct, *, company_subject=True):
    """Create a 2-step sequence (step0 delay 0, step1 delay 3). Step0 subject
    references {{company}} so the worker test can assert template rendering."""
    subject0 = "Привет, {{company}}!" if company_subject else "Привет!"
    payload = {
        "name": f"Drip {uuid.uuid4().hex[:6]}",
        "steps": [
            {"delay_days": 0, "subject": subject0, "body": "Здравствуйте, {{company}}. Предлагаем сотрудничество."},
            {"delay_days": 3, "subject": "Напоминание", "body": "Напоминаем о нашем предложении."},
        ],
    }
    r = acct.post("/api/outreach/sequences", json=payload)
    assert r.status_code in (200, 201), f"sequence create failed: {r.status_code} {r.text}"
    return r.json()


def _org_settings(db, org_id) -> OrgEmailSettings | None:
    return (
        db.query(OrgEmailSettings)
        .filter(OrgEmailSettings.organization_id == uuid.UUID(str(org_id)))
        .one_or_none()
    )


@pytest.fixture
def fake_smtp(monkeypatch):
    """Record calls to the SMTP sender; never touch the network.

    The worker does `from app.services.outreach import send_via_smtp`, so once
    app.tasks.outreach_tasks is imported it holds its OWN bound name — patching
    only the service module would miss it (and the worker would hit the real
    network → gaierror). So patch BOTH bindings; order-independent that way."""
    calls: list[dict] = []

    def _send(s, *, to_email, subject, html_body, text_body, unsub_url=None):
        calls.append({
            "to_email": to_email,
            "subject": subject,
            "html_body": html_body,
            "text_body": text_body,
            "unsub_url": unsub_url,
        })
        return "<fake-msgid>"

    import app.services.outreach as outreach_svc
    import app.tasks.outreach_tasks as tasks
    monkeypatch.setattr(outreach_svc, "send_via_smtp", _send, raising=True)
    monkeypatch.setattr(tasks, "send_via_smtp", _send, raising=False)
    # The settings "test" endpoint goes through smtp_test → force a clean pass.
    monkeypatch.setattr(outreach_svc, "smtp_test", lambda s, to_email: (True, ""), raising=True)
    return calls


@pytest.fixture
def force_send_window(monkeypatch):
    """Force the worker's wall-clock send-window check open."""
    import app.tasks.outreach_tasks as tasks
    monkeypatch.setattr(tasks, "within_send_window", lambda *a, **k: True, raising=False)


def _process():
    """Run the send worker directly (Celery is eager in this harness)."""
    from app.tasks.outreach_tasks import process_email_sequences
    return process_email_sequences()


# ─────────────────────────────────────────────────────────────────────────────
# 1) Settings: PUT/GET, password encrypted at rest, never echoed, keep-on-reput
# ─────────────────────────────────────────────────────────────────────────────

def test_settings_put_get_encrypts_and_never_leaks_password(paid_account, db):
    acct = paid_account
    payload = _configure_settings(acct)

    r = acct.get("/api/outreach/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["smtp_password_set"] is True
    assert body["from_email"] == payload["from_email"]
    assert body["smtp_host"] == payload["smtp_host"]
    # The raw password must NEVER appear anywhere in the JSON.
    assert payload["smtp_password"] not in r.text
    assert "smtp_password" not in body, "raw password key must not be returned"

    # Persisted, encrypted (not plaintext) at rest.
    settings = _org_settings(db, acct.org_id)
    assert settings is not None
    assert settings.smtp_password_enc, "encrypted password must be stored"
    assert settings.smtp_password_enc != payload["smtp_password"], "must be encrypted, not plaintext"
    # And it round-trips back to the plaintext via the app's crypto.
    from app.services.crypto import decrypt_secret
    assert decrypt_secret(settings.smtp_password_enc) == payload["smtp_password"]

    # Re-PUT WITHOUT smtp_password keeps the stored one.
    keep = dict(payload)
    keep.pop("smtp_password")
    keep["from_name"] = "Изменённое имя"
    r = acct.request("PUT", "/api/outreach/settings", json=keep)
    assert r.status_code == 200, r.text
    again = acct.get("/api/outreach/settings").json()
    assert again["smtp_password_set"] is True
    assert again["from_name"] == "Изменённое имя"
    db.expire_all()
    settings2 = _org_settings(db, acct.org_id)
    from app.services.crypto import decrypt_secret as _dec
    assert _dec(settings2.smtp_password_enc) == payload["smtp_password"], "password must survive re-PUT"


# ─────────────────────────────────────────────────────────────────────────────
# 2) Test endpoint → {ok:true} and verified == True
# ─────────────────────────────────────────────────────────────────────────────

def test_settings_test_endpoint_marks_verified(paid_account, db, fake_smtp):
    acct = paid_account
    _configure_settings(acct)

    r = acct.post("/api/outreach/settings/test", json={"to_email": "me@example.com"})
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.json()

    db.expire_all()
    settings = _org_settings(db, acct.org_id)
    assert settings is not None and settings.verified is True


# ─────────────────────────────────────────────────────────────────────────────
# 3) Sequence CRUD
# ─────────────────────────────────────────────────────────────────────────────

def test_sequence_crud(paid_account):
    acct = paid_account
    seq = _make_sequence(acct)
    seq_id = seq["id"]
    assert len(seq["steps"]) == 2
    delays = sorted(s["delay_days"] for s in seq["steps"])
    assert delays == [0, 3]

    # GET list shows it.
    listed = acct.get("/api/outreach/sequences")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    rows = rows["items"] if isinstance(rows, dict) and "items" in rows else rows
    assert seq_id in [s["id"] for s in rows]

    # PATCH replaces the steps (now a single step).
    r = acct.patch(f"/api/outreach/sequences/{seq_id}", json={
        "steps": [{"delay_days": 1, "subject": "Только один шаг", "body": "Тело письма"}],
    })
    assert r.status_code == 200, r.text
    after = acct.get(f"/api/outreach/sequences/{seq_id}")
    assert after.status_code == 200, after.text
    steps = after.json()["steps"]
    assert len(steps) == 1, steps
    assert steps[0]["subject"] == "Только один шаг"
    assert steps[0]["delay_days"] == 1

    # DELETE removes it.
    d = acct.delete(f"/api/outreach/sequences/{seq_id}")
    assert d.status_code in (200, 204), d.text
    gone = acct.get(f"/api/outreach/sequences/{seq_id}")
    assert gone.status_code == 404, gone.text


# ─────────────────────────────────────────────────────────────────────────────
# 4) Enroll: emailable counted; no-email + opted-out skipped; dup skipped;
#    unconfigured org → 400
# ─────────────────────────────────────────────────────────────────────────────

def test_enroll_counts_and_skips_and_dup_and_unconfigured(
    paid_account, make_account, stub_sources, new_project, db
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=3)
    emailable, no_email, opted_out = leads[0]["id"], leads[1]["id"], leads[2]["id"]

    _set_lead_fields(db, emailable, email="lead@example.com", email_opt_out=False)
    _set_lead_fields(db, no_email, email="", email_opt_out=False)
    _set_lead_fields(db, opted_out, email="opt@example.com", email_opt_out=True)

    seq = _make_sequence(acct)
    seq_id = seq["id"]

    r = acct.post(f"/api/outreach/sequences/{seq_id}/enroll",
                  json={"lead_ids": [emailable, no_email, opted_out]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enrolled"] == 1, body
    assert body["skipped"] == 2, body

    # Enrolling the same lead again → skipped (dup), nothing new enrolled.
    r2 = acct.post(f"/api/outreach/sequences/{seq_id}/enroll",
                   json={"lead_ids": [emailable]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["enrolled"] == 0, r2.json()
    assert r2.json()["skipped"] == 1, r2.json()

    # Exactly one active enrollment for the emailable lead in DB.
    enrs = (
        db.query(SequenceEnrollment)
        .filter(SequenceEnrollment.sequence_id == uuid.UUID(seq_id))
        .all()
    )
    assert len(enrs) == 1, enrs
    assert str(enrs[0].lead_id) == str(emailable)

    # A fresh org with NO settings → enroll is 400.
    other = make_account(plan="pro")
    pid2, leads2 = _collect_leads(other, new_project, niche=_niche(), n=1)
    _set_lead_fields(db, leads2[0]["id"], email="x@example.com")
    seq2 = _make_sequence(other)
    r3 = other.post(f"/api/outreach/sequences/{seq2['id']}/enroll",
                    json={"lead_ids": [leads2[0]["id"]]})
    assert r3.status_code == 400, f"unconfigured enroll must 400, got {r3.status_code}: {r3.text}"


# ─────────────────────────────────────────────────────────────────────────────
# 5) Worker send
# ─────────────────────────────────────────────────────────────────────────────

def test_worker_sends_step0_renders_template_and_advances(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    # Deterministic company name so we can assert the rendered subject.
    _set_lead_fields(db, lead_id, email="lead@example.com", company="Рога и Копыта", email_opt_out=False)

    seq = _make_sequence(acct)  # step0 subject "Привет, {{company}}!"
    r = acct.post(f"/api/outreach/sequences/{seq['id']}/enroll", json={"lead_ids": [lead_id]})
    assert r.status_code == 200 and r.json()["enrolled"] == 1, r.text

    # step0 delay 0 → due ~now; make it unambiguously due.
    enr = (
        db.query(SequenceEnrollment)
        .filter(SequenceEnrollment.sequence_id == uuid.UUID(seq["id"]))
        .one()
    )
    enr.next_send_at = _now_naive() - timedelta(minutes=1)
    db.commit()

    _process()

    # The fake sender was called exactly once for the emailable lead.
    assert len(fake_smtp) == 1, fake_smtp
    sent = fake_smtp[0]
    assert sent["to_email"] == "lead@example.com"
    # Subject rendered from the template ({{company}} substituted).
    assert "Рога и Копыта" in sent["subject"], sent["subject"]
    assert "{{company}}" not in sent["subject"]
    # Body carries an unsubscribe URL (either in the html/text body or unsub_url).
    blob = (sent.get("html_body") or "") + (sent.get("text_body") or "") + (sent.get("unsub_url") or "")
    assert "/api/outreach/u/" in blob, sent

    # An OutreachMessage row status='sent' exists.
    db.expire_all()
    msgs = (
        db.query(OutreachMessage)
        .filter(OutreachMessage.lead_id == uuid.UUID(str(lead_id)))
        .all()
    )
    assert any(m.status == "sent" for m in msgs), [m.status for m in msgs]

    # Enrollment advanced: current_step == 1, next_send_at ~ now + 3 days.
    db.refresh(enr)
    assert enr.current_step == 1, enr.current_step
    assert enr.next_send_at is not None
    delta = enr.next_send_at - _now_naive()
    assert timedelta(days=2, hours=12) <= delta <= timedelta(days=3, hours=12), delta

    # sent_today rolled to 1.
    settings = _org_settings(db, acct.org_id)
    assert settings.sent_today == 1, settings.sent_today


# ─────────────────────────────────────────────────────────────────────────────
# 6) Opt-out skip: an active enrollment on an opted-out lead → unsubscribed,
#    no send
# ─────────────────────────────────────────────────────────────────────────────

def test_worker_skips_opted_out_lead_marks_unsubscribed(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    # Lead has an email so it can be enrolled, but is opted out.
    _set_lead_fields(db, lead_id, email="optout@example.com", email_opt_out=False)

    seq = _make_sequence(acct)
    r = acct.post(f"/api/outreach/sequences/{seq['id']}/enroll", json={"lead_ids": [lead_id]})
    assert r.status_code == 200 and r.json()["enrolled"] == 1, r.text

    enr = (
        db.query(SequenceEnrollment)
        .filter(SequenceEnrollment.sequence_id == uuid.UUID(seq["id"]))
        .one()
    )
    enr.next_send_at = _now_naive() - timedelta(minutes=1)
    db.commit()

    # Flip the lead to opted-out AFTER enrollment (the active enrollment lingers).
    _set_lead_fields(db, lead_id, email_opt_out=True)

    _process()

    # Nothing sent.
    assert len(fake_smtp) == 0, fake_smtp
    # Enrollment marked unsubscribed.
    db.refresh(enr)
    assert enr.status == "unsubscribed", enr.status
    # No 'sent' message row.
    db.expire_all()
    msgs = (
        db.query(OutreachMessage)
        .filter(OutreachMessage.lead_id == uuid.UUID(str(lead_id)),
                OutreachMessage.status == "sent")
        .all()
    )
    assert msgs == [], msgs


# ─────────────────────────────────────────────────────────────────────────────
# 7) Unsubscribe route (unauthenticated)
# ─────────────────────────────────────────────────────────────────────────────

def test_unsubscribe_route_opts_out_and_unknown_token_no_leak(
    paid_account, stub_sources, new_project, db, client
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(db, lead_id, email="lead@example.com", email_opt_out=False)

    seq = _make_sequence(acct)
    r = acct.post(f"/api/outreach/sequences/{seq['id']}/enroll", json={"lead_ids": [lead_id]})
    assert r.status_code == 200 and r.json()["enrolled"] == 1, r.text

    enr = (
        db.query(SequenceEnrollment)
        .filter(SequenceEnrollment.sequence_id == uuid.UUID(seq["id"]))
        .one()
    )
    token = enr.unsubscribe_token
    assert token, "enrollment must carry an unsubscribe token"

    # Unauthenticated GET (raw client, no auth headers) → 200 HTML.
    resp = client.get(f"/api/outreach/u/{token}")
    assert resp.status_code == 200, resp.text
    assert "html" in resp.headers.get("content-type", "").lower(), resp.headers

    # Enrollment is now unsubscribed and the Lead is opted out.
    db.expire_all()
    db.refresh(enr)
    assert enr.status == "unsubscribed", enr.status
    lead = db.get(Lead, uuid.UUID(str(lead_id)))
    assert lead.email_opt_out is True

    # Unknown token → still 200 (no leak), no error.
    bad = client.get(f"/api/outreach/u/{uuid.uuid4().hex}")
    assert bad.status_code == 200, bad.text


# ─────────────────────────────────────────────────────────────────────────────
# 8) Daily limit reached → 0 new sends this cycle
# ─────────────────────────────────────────────────────────────────────────────

def test_daily_limit_blocks_sends_this_cycle(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window
):
    acct = paid_account
    _configure_settings(acct)
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=2)
    a, b = leads[0]["id"], leads[1]["id"]
    _set_lead_fields(db, a, email="a@example.com", email_opt_out=False)
    _set_lead_fields(db, b, email="b@example.com", email_opt_out=False)

    seq = _make_sequence(acct)
    r = acct.post(f"/api/outreach/sequences/{seq['id']}/enroll", json={"lead_ids": [a, b]})
    assert r.status_code == 200 and r.json()["enrolled"] == 2, r.text

    # Make both enrollments due.
    enrs = (
        db.query(SequenceEnrollment)
        .filter(SequenceEnrollment.sequence_id == uuid.UUID(seq["id"]))
        .all()
    )
    for e in enrs:
        e.next_send_at = _now_naive() - timedelta(minutes=1)

    # Daily limit reached for today.
    settings = _org_settings(db, acct.org_id)
    settings.daily_limit = 1
    settings.sent_today = 1
    settings.sent_today_date = _now_naive()
    db.commit()

    _process()

    # No new sends this cycle (limit already reached).
    assert len(fake_smtp) == 0, fake_smtp
    db.expire_all()
    sent_rows = (
        db.query(OutreachMessage)
        .filter(OutreachMessage.organization_id == uuid.UUID(str(acct.org_id)),
                OutreachMessage.status == "sent")
        .all()
    )
    assert sent_rows == [], [(str(m.lead_id), m.status) for m in sent_rows]

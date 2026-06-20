"""TRUE end-to-end tests for the outreach TRACKING extensions.

Builds on the same e2e harness as test_e2e_outreach.py (real auth → real DB,
Celery eager, lead-collection stubbed at the jobs.py seam) and exercises the
three features layered on top of the drip engine:

  • open/click tracking  — the public pixel + click-redirect endpoints, plus the
    worker injecting tracking into the sent HTML (open pixel + wrapped links).
  • replies inbox        — poll_email_replies() captures inbound mail into
    OutreachReply rows, flips the matching enrollment to "replied", dedupes on a
    second run, and surfaces via GET /api/outreach/replies with lead_company.
  • AI email generation  — POST /api/outreach/ai/generate-email (owner only).

NEVER touches the network. SMTP send, the send-window clock, the IMAP
fetch_replies poll and the LLM generate call are all monkeypatched to canned,
deterministic fakes. Leads' emails are set directly via the db fixture.

Spec covered (each its own test):
  1) Open pixel — worker-created message carries a track_token; GET the .gif
     (raw client, no auth) → 200 image/gif; opened_at stamped, opens_count
     increments per hit; an unknown token is still 200 (no leak/no error).
  2) Click — GET /t/c/{token}?u=<b64url https://example.com> → 302 to the
     target; clicked_at stamped, clicks_count == 1 (and an implied open).
  3) Worker injects tracking — after a real eager send, the fake SMTP got an
     html_body containing the open-pixel path "/api/outreach/t/o/", and the
     persisted message has a non-empty track_token.
  4) AI generate — owner POSTs niche/step_number → 200 {subject, body}.
  5) Replies — one fake reply from an enrolled lead → an OutreachReply row,
     enrollment status "replied"; re-running does NOT duplicate; GET /replies
     shows it with lead_company.
  6) Stats — GET /api/outreach/sequences/{id} stats reflect opened/clicked/
     replies from the above.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Lead,
    OrgEmailSettings,
    OutreachMessage,
    OutreachReply,
    SequenceEnrollment,
)


# ── helpers (mirrors test_e2e_outreach.py) ───────────────────────────────────

def _niche() -> str:
    """A niche unique to this collect so the shared warehouse stays isolated."""
    return f"trkнiша{uuid.uuid4().hex[:8]}"


def _now_naive() -> datetime:
    """Naive-UTC 'now' to match the DateTime (no-tz) columns the models use."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


def _collect_leads(acct, new_project, *, niche, n=3):
    """Create a project under a unique niche and collect a dose of leads."""
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
    """Set raw columns on a Lead (email / company / email_opt_out) for determinism."""
    lead = db.get(Lead, uuid.UUID(str(lead_id)))
    assert lead is not None, f"lead {lead_id} not found"
    for k, v in fields.items():
        setattr(lead, k, v)
    db.commit()


def _configure_settings(acct, *, to_email_host="example.com"):
    """PUT a fully-configured OrgEmailSettings for the account's org (SMTP)."""
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
    r = acct.request("PUT", "/api/outreach/settings", json=payload)
    assert r.status_code == 200, f"settings PUT failed: {r.status_code} {r.text}"
    return payload


def _org_settings(db, org_id) -> OrgEmailSettings | None:
    return (
        db.query(OrgEmailSettings)
        .filter(OrgEmailSettings.organization_id == uuid.UUID(str(org_id)))
        .one_or_none()
    )


def _configure_imap(db, org_id):
    """Settings PUT exposes IMAP fields but the encrypted IMAP password is what
    the poll gates on; set host + an encrypted password directly so
    poll_email_replies() reaches our (faked) fetch_replies."""
    from app.services.crypto import encrypt_secret

    s = _org_settings(db, org_id)
    assert s is not None, "configure SMTP settings before IMAP"
    s.imap_host = "imap.example.com"
    s.imap_port = 993
    s.imap_user = "sales@example.com"
    s.imap_password_enc = encrypt_secret("imap-pw")
    db.commit()
    return s


def _make_sequence(acct):
    """Create a 2-step sequence (step0 delay 0, step1 delay 3). step0 subject
    references {{company}} so we can assert template rendering on the way in.

    The step body carries an http link so inject_tracking has something to wrap
    (the open pixel is appended regardless)."""
    payload = {
        "name": f"Drip {uuid.uuid4().hex[:6]}",
        "steps": [
            {
                "delay_days": 0,
                "subject": "Привет, {{company}}!",
                "body": 'Здравствуйте! Подробнее тут: <a href="https://example.com/info">сайт</a>.',
            },
            {"delay_days": 3, "subject": "Напоминание", "body": "Напоминаем о предложении."},
        ],
    }
    r = acct.post("/api/outreach/sequences", json=payload)
    assert r.status_code in (200, 201), f"sequence create failed: {r.status_code} {r.text}"
    return r.json()


# ── fixtures (local — these are not in conftest) ─────────────────────────────

@pytest.fixture
def fake_smtp(monkeypatch):
    """Record calls to the SMTP sender; never touch the network. Patch BOTH the
    service module and the worker's bound name so the worker always hits the
    fake regardless of import order."""
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
    monkeypatch.setattr(outreach_svc, "smtp_test", lambda s, to_email: (True, ""), raising=True)
    return calls


@pytest.fixture
def force_send_window(monkeypatch):
    """Force the worker's wall-clock send-window check open."""
    import app.tasks.outreach_tasks as tasks
    monkeypatch.setattr(tasks, "within_send_window", lambda *a, **k: True, raising=False)


@pytest.fixture
def fake_generate(monkeypatch):
    """Stub the LLM email generator (route calls it as outreach.generate_email)."""
    def _gen(**kwargs):
        return {"subject": "Тест {{company}}", "body": "Текст"}

    import app.services.outreach as outreach_svc
    monkeypatch.setattr(outreach_svc, "generate_email", _gen, raising=True)
    return _gen


def _patch_fetch_replies(monkeypatch, replies: list[dict]):
    """Make the IMAP poll return a chosen list (patch both bindings)."""
    def _fetch(s, since, addresses):
        return list(replies)

    import app.services.outreach as outreach_svc
    import app.tasks.outreach_tasks as tasks
    monkeypatch.setattr(outreach_svc, "fetch_replies", _fetch, raising=True)
    monkeypatch.setattr(tasks, "fetch_replies", _fetch, raising=False)


def _process():
    """Run the send worker directly (Celery is eager in this harness)."""
    from app.tasks.outreach_tasks import process_email_sequences
    return process_email_sequences()


def _poll_replies():
    from app.tasks.outreach_tasks import poll_email_replies
    return poll_email_replies()


def _enroll_one_and_send(acct, new_project, db, fake_smtp, niche):
    """Collect → emailable lead → 2-step sequence → enroll → make due → send.

    Returns (lead_id, seq_id, enrollment_row). After this the lead has exactly
    one OutreachMessage status='sent' carrying a track_token."""
    pid, leads = _collect_leads(acct, new_project, niche=niche, n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(db, lead_id, email="lead@example.com", company="Рога и Копыта", email_opt_out=False)

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

    _process()
    assert len(fake_smtp) == 1, fake_smtp
    return lead_id, seq["id"], enr


def _sent_message(db, lead_id) -> OutreachMessage:
    db.expire_all()
    msg = (
        db.query(OutreachMessage)
        .filter(OutreachMessage.lead_id == uuid.UUID(str(lead_id)),
                OutreachMessage.status == "sent")
        .one()
    )
    return msg


# ─────────────────────────────────────────────────────────────────────────────
# 1) Open pixel
# ─────────────────────────────────────────────────────────────────────────────

def test_open_pixel_records_opens_and_unknown_token_is_safe(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window, client
):
    acct = paid_account
    _configure_settings(acct)
    lead_id, _seq_id, _enr = _enroll_one_and_send(acct, new_project, db, fake_smtp, _niche())

    msg = _sent_message(db, lead_id)
    assert msg.track_token, "worker must stamp a non-empty track_token on the sent message"
    assert msg.opened_at is None and msg.opens_count == 0, "no open before the pixel is hit"
    token = msg.track_token

    # First hit (raw client, NO auth) — the pixel URL ends in .gif.
    r = client.get(f"/api/outreach/t/o/{token}.gif")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").lower().startswith("image/gif"), r.headers
    assert r.content, "pixel must return image bytes"

    db.expire_all()
    db.refresh(msg)
    assert msg.opened_at is not None, "first open must stamp opened_at"
    assert msg.opens_count == 1, msg.opens_count

    # Second hit → opens_count increments, opened_at stays (first-touch).
    first_opened_at = msg.opened_at
    r2 = client.get(f"/api/outreach/t/o/{token}.gif")
    assert r2.status_code == 200
    db.expire_all()
    db.refresh(msg)
    assert msg.opens_count == 2, msg.opens_count
    assert msg.opened_at == first_opened_at, "opened_at is first-touch, must not move"

    # Unknown token → still a 200 GIF, no error, no leak.
    bad = client.get(f"/api/outreach/t/o/{uuid.uuid4().hex}.gif")
    assert bad.status_code == 200, bad.text
    assert bad.headers.get("content-type", "").lower().startswith("image/gif"), bad.headers


# ─────────────────────────────────────────────────────────────────────────────
# 2) Click tracking
# ─────────────────────────────────────────────────────────────────────────────

def test_click_redirects_and_records_click(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window, client
):
    acct = paid_account
    _configure_settings(acct)
    lead_id, _seq_id, _enr = _enroll_one_and_send(acct, new_project, db, fake_smtp, _niche())

    msg = _sent_message(db, lead_id)
    token = msg.track_token
    target = "https://example.com"

    # Raw client, no auth; do NOT follow the redirect so we can inspect the 302.
    r = client.get(
        f"/api/outreach/t/c/{token}?u={_b64url(target)}",
        follow_redirects=False,
    )
    assert r.status_code == 302, f"{r.status_code} {r.text}"
    assert r.headers.get("location") == target, r.headers.get("location")

    db.expire_all()
    db.refresh(msg)
    assert msg.clicked_at is not None, "click must stamp clicked_at"
    assert msg.clicks_count == 1, msg.clicks_count
    # A click implies an open even if the pixel never loaded.
    assert msg.opened_at is not None, "a click implies an open"


# ─────────────────────────────────────────────────────────────────────────────
# 3) Worker injects tracking into the sent HTML
# ─────────────────────────────────────────────────────────────────────────────

def test_worker_injects_open_pixel_into_sent_html(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window
):
    acct = paid_account
    _configure_settings(acct)
    lead_id, _seq_id, _enr = _enroll_one_and_send(acct, new_project, db, fake_smtp, _niche())

    sent = fake_smtp[0]
    html = sent.get("html_body") or ""
    # Open pixel path injected by the worker (inject_tracking appends it).
    assert "/api/outreach/t/o/" in html, html[:500]
    # The pixel URL must NOT end in ".gif": prod nginx has a static-asset regex
    # location (\.(...|gif|...)$) that intercepts any *.gif before it can be
    # proxied to the backend → the pixel would 404. Keep it extensionless.
    assert ".gif" not in html, "tracking pixel must be extensionless (nginx static-gif trap)"
    # The http link in the step body is rewritten through the click-tracker.
    assert "/api/outreach/t/c/" in html, html[:500]

    # And the persisted message carries a non-empty track_token tying it back.
    msg = _sent_message(db, lead_id)
    assert msg.track_token, "sent message must carry a track_token"
    assert msg.track_token in html, "the injected URLs must use the message's token"


# ─────────────────────────────────────────────────────────────────────────────
# 4) AI email generation (owner)
# ─────────────────────────────────────────────────────────────────────────────

def test_ai_generate_email_returns_subject_and_body(paid_account, fake_generate):
    acct = paid_account
    r = acct.post(
        "/api/outreach/ai/generate-email",
        json={"niche": "станки", "step_number": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject"] == "Тест {{company}}", body
    assert body["body"] == "Текст", body


# ─────────────────────────────────────────────────────────────────────────────
# 5) Replies inbox: capture, flip enrollment, dedupe, list with lead_company
# ─────────────────────────────────────────────────────────────────────────────

def test_poll_replies_captures_flips_enrollment_dedupes_and_lists(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window, monkeypatch
):
    acct = paid_account
    _configure_settings(acct)
    _configure_imap(db, acct.org_id)

    # Enroll an emailable lead (active enrollment is what the poll scans).
    pid, leads = _collect_leads(acct, new_project, niche=_niche(), n=1)
    lead_id = leads[0]["id"]
    _set_lead_fields(db, lead_id, email="prospect@example.com", company="ООО Ответчик", email_opt_out=False)

    seq = _make_sequence(acct)
    r = acct.post(f"/api/outreach/sequences/{seq['id']}/enroll", json={"lead_ids": [lead_id]})
    assert r.status_code == 200 and r.json()["enrolled"] == 1, r.text

    enr = (
        db.query(SequenceEnrollment)
        .filter(SequenceEnrollment.sequence_id == uuid.UUID(seq["id"]))
        .one()
    )
    assert enr.status == "active"

    # One fake reply from the enrolled lead's address.
    received = _now_naive().replace(microsecond=0)
    reply = {
        "from_email": "prospect@example.com",
        "subject": "Re: Привет",
        "snippet": "Да, давайте обсудим, перезвоните завтра.",
        "received_at": received,
    }
    _patch_fetch_replies(monkeypatch, [reply])

    _poll_replies()

    # A reply row was captured for this org.
    db.expire_all()
    rows = (
        db.query(OutreachReply)
        .filter(OutreachReply.organization_id == uuid.UUID(str(acct.org_id)))
        .all()
    )
    assert len(rows) == 1, [(r.from_email, r.subject) for r in rows]
    rrow = rows[0]
    assert rrow.from_email == "prospect@example.com"
    assert rrow.subject == "Re: Привет"
    assert str(rrow.lead_id) == str(lead_id), "reply linked to the matched lead"
    assert str(rrow.enrollment_id) == str(enr.id), "reply linked to the matched enrollment"

    # The enrollment was auto-stopped as 'replied'.
    db.refresh(enr)
    assert enr.status == "replied", enr.status

    # Re-running the poll does NOT duplicate the reply (dedupe on org+from+subj+date).
    # The enrollment is no longer active; re-activate so the poll still scans the
    # address (proves dedupe, not just "no active enrollment → skip").
    enr.status = "active"
    db.commit()
    _patch_fetch_replies(monkeypatch, [reply])
    _poll_replies()
    db.expire_all()
    rows2 = (
        db.query(OutreachReply)
        .filter(OutreachReply.organization_id == uuid.UUID(str(acct.org_id)))
        .all()
    )
    assert len(rows2) == 1, f"reply must not be duplicated, got {len(rows2)}"

    # GET /replies surfaces it with the lead's company joined in.
    listed = acct.get("/api/outreach/replies")
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert isinstance(payload, list) and len(payload) == 1, payload
    item = payload[0]
    assert item["from_email"] == "prospect@example.com"
    assert item["subject"] == "Re: Привет"
    assert item["lead_company"] == "ООО Ответчик", item
    assert item["snippet"].startswith("Да, давайте"), item


# ─────────────────────────────────────────────────────────────────────────────
# 6) Stats reflect opened / clicked / replies
# ─────────────────────────────────────────────────────────────────────────────

def test_sequence_stats_reflect_open_click_and_reply(
    paid_account, stub_sources, new_project, db, fake_smtp, force_send_window, client, monkeypatch
):
    acct = paid_account
    _configure_settings(acct)
    _configure_imap(db, acct.org_id)
    lead_id, seq_id, enr = _enroll_one_and_send(acct, new_project, db, fake_smtp, _niche())

    # Drive one open + one click via the public endpoints.
    msg = _sent_message(db, lead_id)
    token = msg.track_token
    assert client.get(f"/api/outreach/t/o/{token}.gif").status_code == 200
    assert client.get(
        f"/api/outreach/t/c/{token}?u={_b64url('https://example.com')}",
        follow_redirects=False,
    ).status_code == 302

    # Capture a reply for the same lead/enrollment (re-activate so the poll scans).
    db.refresh(enr)
    enr.status = "active"
    db.commit()
    reply = {
        "from_email": "lead@example.com",
        "subject": "Re: Привет",
        "snippet": "Интересно.",
        "received_at": _now_naive().replace(microsecond=0),
    }
    _patch_fetch_replies(monkeypatch, [reply])
    _poll_replies()

    # Stats on the sequence now show the engagement.
    r = acct.get(f"/api/outreach/sequences/{seq_id}")
    assert r.status_code == 200, r.text
    stats = r.json()["stats"]
    assert stats["sent_messages"] == 1, stats
    assert stats["opened"] == 1, stats
    assert stats["clicked"] == 1, stats
    assert stats["replies"] == 1, stats
    assert stats["replied"] == 1, f"the enrollment must show replied: {stats}"

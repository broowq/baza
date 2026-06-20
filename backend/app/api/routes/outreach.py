"""Email-outreach API: per-org SMTP/IMAP settings, sequences + steps,
enrollment, and a public unsubscribe endpoint.

Org-scoping follows the same pattern as leads.py: a row is only visible/editable
when its organization_id matches the caller's org, otherwise 404 (we don't leak
existence across tenants). The encrypted SMTP/IMAP secrets are never returned;
the schemas expose only *_set booleans.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, get_current_user, require_org_roles
from app.db.session import get_db
from app.models import (
    EmailSequence,
    Lead,
    Organization,
    OrgEmailSettings,
    OutreachMessage,
    OutreachReply,
    Project,
    SequenceEnrollment,
    SequenceStep,
    User,
)
from app.schemas.outreach import (
    AiGenerateRequest,
    AiGenerateResponse,
    EmailSettingsIn,
    EmailSettingsOut,
    EnrollRequest,
    EnrollResult,
    EnrollmentOut,
    ReplyOut,
    SequenceIn,
    SequenceOut,
    SequenceStatsOut,
    SequenceStepOut,
    SequenceUpdate,
    TestEmailRequest,
)
from app.services import outreach
from app.services.crypto import encrypt_secret
from app.services.outreach import new_unsubscribe_token, smtp_test

router = APIRouter(prefix="/outreach", tags=["outreach"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Settings ─────────────────────────────────────────────────────────────────

def _settings_to_out(row: OrgEmailSettings | None) -> EmailSettingsOut:
    """Project a settings row to the safe output schema (never the secrets)."""
    if row is None:
        return EmailSettingsOut(configured=False)
    return EmailSettingsOut(
        configured=bool(row.smtp_host),
        from_name=row.from_name or "",
        from_email=row.from_email or "",
        smtp_host=row.smtp_host or "",
        smtp_port=row.smtp_port,
        smtp_user=row.smtp_user or "",
        smtp_password_set=bool(row.smtp_password_enc),
        smtp_use_tls=row.smtp_use_tls,
        imap_host=row.imap_host or "",
        imap_port=row.imap_port,
        imap_user=row.imap_user or "",
        imap_password_set=bool(row.imap_password_enc),
        daily_limit=row.daily_limit,
        sent_today=row.sent_today,
        verified=row.verified,
    )


def _get_settings_row(db: Session, organization_id) -> OrgEmailSettings | None:
    return db.execute(
        select(OrgEmailSettings).where(
            OrgEmailSettings.organization_id == organization_id
        )
    ).scalar_one_or_none()


@router.get("/settings", response_model=EmailSettingsOut)
def get_settings_route(
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    return _settings_to_out(_get_settings_row(db, organization.id))


@router.put("/settings", response_model=EmailSettingsOut)
def upsert_settings(
    payload: EmailSettingsIn,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    row = _get_settings_row(db, organization.id)
    if row is None:
        row = OrgEmailSettings(organization_id=organization.id)
        db.add(row)

    # Whenever any SMTP connection field changes, the saved verification is no
    # longer trustworthy — force a re-test before the next send.
    smtp_changed = (
        row.smtp_host != payload.smtp_host
        or row.smtp_port != payload.smtp_port
        or row.smtp_user != payload.smtp_user
        or row.smtp_use_tls != payload.smtp_use_tls
        or (isinstance(payload.smtp_password, str) and payload.smtp_password != "")
    )

    row.from_name = payload.from_name
    row.from_email = payload.from_email
    row.smtp_host = payload.smtp_host
    row.smtp_port = payload.smtp_port
    row.smtp_user = payload.smtp_user
    row.smtp_use_tls = payload.smtp_use_tls
    row.imap_host = payload.imap_host
    row.imap_port = payload.imap_port
    row.imap_user = payload.imap_user
    row.daily_limit = payload.daily_limit

    # Encrypt + store a password ONLY when a non-empty string was supplied.
    # Omitted / None / "" → keep whatever is already stored.
    if isinstance(payload.smtp_password, str) and payload.smtp_password != "":
        row.smtp_password_enc = encrypt_secret(payload.smtp_password)
    if isinstance(payload.imap_password, str) and payload.imap_password != "":
        row.imap_password_enc = encrypt_secret(payload.imap_password)

    if smtp_changed:
        row.verified = False

    db.commit()
    db.refresh(row)
    return _settings_to_out(row)


@router.post("/settings/test")
def test_settings(
    payload: TestEmailRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    row = _get_settings_row(db, organization.id)
    if row is None or not row.smtp_host:
        raise HTTPException(status_code=400, detail="Почта не настроена")
    ok, err = smtp_test(row, payload.to_email)
    if ok:
        row.verified = True
        db.commit()
    return {"ok": ok, "error": err}


# ── Sequences ────────────────────────────────────────────────────────────────

# Enrollment statuses other than these are "terminal" — the lead is no longer
# being mailed. "active" is the only non-terminal state.
ACTIVE_ENROLLMENT_STATUS = "active"


def _steps_for(db: Session, sequence_id) -> list[SequenceStep]:
    return list(
        db.execute(
            select(SequenceStep)
            .where(SequenceStep.sequence_id == sequence_id)
            .order_by(SequenceStep.step_order)
        ).scalars()
    )


def _stats_for_sequences(db: Session, sequence_ids: list) -> dict:
    """Compute per-sequence stats with two grouped queries (no N+1).

    Returns {sequence_id: SequenceStatsOut}. Sequences with no enrollments and
    no messages still get a zeroed stats block from the caller's defaultdict.
    """
    stats: dict = {sid: SequenceStatsOut() for sid in sequence_ids}
    if not sequence_ids:
        return stats

    # Enrollments grouped by (sequence, status).
    rows = db.execute(
        select(
            SequenceEnrollment.sequence_id,
            SequenceEnrollment.status,
            func.count(SequenceEnrollment.id),
        )
        .where(SequenceEnrollment.sequence_id.in_(sequence_ids))
        .group_by(SequenceEnrollment.sequence_id, SequenceEnrollment.status)
    ).all()
    # status → SequenceStatsOut attribute name
    field_for_status = {
        "active": "active",
        "completed": "completed",
        "replied": "replied",
        "unsubscribed": "unsubscribed",
        "bounced": "bounced",
        "stopped": "stopped",
        # 'failed' has no dedicated field; it still counts toward `enrolled`.
    }
    for sid, status, count in rows:
        st = stats[sid]
        st.enrolled += count
        attr = field_for_status.get(status)
        if attr is not None:
            setattr(st, attr, getattr(st, attr) + count)

    # Sent-message counts + open/click engagement grouped by sequence (via the
    # enrollment join). One pass over outreach_messages yields all three so we
    # stay free of N+1 / extra round-trips.
    msg_rows = db.execute(
        select(
            SequenceEnrollment.sequence_id,
            func.count(OutreachMessage.id).filter(
                OutreachMessage.status == "sent"
            ),
            func.count(OutreachMessage.id).filter(
                OutreachMessage.opened_at.isnot(None)
            ),
            func.count(OutreachMessage.id).filter(
                OutreachMessage.clicked_at.isnot(None)
            ),
        )
        .join(OutreachMessage, OutreachMessage.enrollment_id == SequenceEnrollment.id)
        .where(SequenceEnrollment.sequence_id.in_(sequence_ids))
        .group_by(SequenceEnrollment.sequence_id)
    ).all()
    for sid, sent, opened, clicked in msg_rows:
        st = stats[sid]
        st.sent_messages = sent
        st.opened = opened
        st.clicked = clicked

    # Captured inbound replies grouped by sequence (via the enrollment join).
    reply_rows = db.execute(
        select(
            SequenceEnrollment.sequence_id,
            func.count(OutreachReply.id),
        )
        .join(OutreachReply, OutreachReply.enrollment_id == SequenceEnrollment.id)
        .where(SequenceEnrollment.sequence_id.in_(sequence_ids))
        .group_by(SequenceEnrollment.sequence_id)
    ).all()
    for sid, count in reply_rows:
        stats[sid].replies = count

    return stats


def _sequence_to_out(
    seq: EmailSequence,
    steps: list[SequenceStep],
    stats: SequenceStatsOut,
) -> SequenceOut:
    return SequenceOut(
        id=seq.id,
        name=seq.name,
        status=seq.status,
        project_id=seq.project_id,
        created_at=seq.created_at,
        steps=[SequenceStepOut.model_validate(s) for s in steps],
        stats=stats,
    )


def _get_org_sequence_or_404(
    db: Session, sequence_id: UUID, organization: Organization
) -> EmailSequence:
    seq = db.get(EmailSequence, sequence_id)
    if not seq or seq.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Последовательность не найдена")
    return seq


@router.get("/sequences", response_model=list[SequenceOut])
def list_sequences(
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    sequences = list(
        db.execute(
            select(EmailSequence)
            .where(EmailSequence.organization_id == organization.id)
            .order_by(EmailSequence.created_at.desc())
        ).scalars()
    )
    if not sequences:
        return []

    seq_ids = [s.id for s in sequences]
    stats = _stats_for_sequences(db, seq_ids)

    # All steps for these sequences in one query, then bucket by sequence_id.
    all_steps = list(
        db.execute(
            select(SequenceStep)
            .where(SequenceStep.sequence_id.in_(seq_ids))
            .order_by(SequenceStep.sequence_id, SequenceStep.step_order)
        ).scalars()
    )
    steps_by_seq: dict = {sid: [] for sid in seq_ids}
    for step in all_steps:
        steps_by_seq[step.sequence_id].append(step)

    return [
        _sequence_to_out(s, steps_by_seq[s.id], stats[s.id]) for s in sequences
    ]


@router.post("/sequences", response_model=SequenceOut)
def create_sequence(
    payload: SequenceIn,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if (
            not project
            or project.organization_id != organization.id
            or project.deleted_at is not None
        ):
            raise HTTPException(status_code=404, detail="Проект не найден")

    seq = EmailSequence(
        organization_id=organization.id,
        project_id=payload.project_id,
        name=payload.name,
        status="active",
        created_by_user_id=user.id,
    )
    db.add(seq)
    db.flush()

    steps: list[SequenceStep] = []
    for idx, step_in in enumerate(payload.steps):
        step = SequenceStep(
            sequence_id=seq.id,
            organization_id=organization.id,
            step_order=idx,
            delay_days=step_in.delay_days,
            subject=step_in.subject,
            body=step_in.body,
        )
        db.add(step)
        steps.append(step)

    db.commit()
    db.refresh(seq)
    steps = _steps_for(db, seq.id)
    return _sequence_to_out(seq, steps, SequenceStatsOut())


@router.get("/sequences/{sequence_id}", response_model=SequenceOut)
def get_sequence(
    sequence_id: UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    seq = _get_org_sequence_or_404(db, sequence_id, organization)
    steps = _steps_for(db, seq.id)
    stats = _stats_for_sequences(db, [seq.id])[seq.id]
    return _sequence_to_out(seq, steps, stats)


@router.patch("/sequences/{sequence_id}", response_model=SequenceOut)
def update_sequence(
    sequence_id: UUID,
    payload: SequenceUpdate,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    seq = _get_org_sequence_or_404(db, sequence_id, organization)

    if payload.name is not None:
        seq.name = payload.name
    if payload.status is not None:
        if payload.status not in ("active", "paused", "archived"):
            raise HTTPException(
                status_code=422,
                detail="Недопустимый статус. Допустимые значения: active, paused, archived",
            )
        seq.status = payload.status

    # Steps provided → REPLACE all of them (delete existing, recreate fresh).
    if payload.steps is not None:
        db.execute(
            SequenceStep.__table__.delete().where(
                SequenceStep.sequence_id == seq.id
            )
        )
        for idx, step_in in enumerate(payload.steps):
            db.add(
                SequenceStep(
                    sequence_id=seq.id,
                    organization_id=organization.id,
                    step_order=idx,
                    delay_days=step_in.delay_days,
                    subject=step_in.subject,
                    body=step_in.body,
                )
            )

    db.commit()
    db.refresh(seq)
    steps = _steps_for(db, seq.id)
    stats = _stats_for_sequences(db, [seq.id])[seq.id]
    return _sequence_to_out(seq, steps, stats)


@router.delete("/sequences/{sequence_id}", status_code=204)
def delete_sequence(
    sequence_id: UUID,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    seq = _get_org_sequence_or_404(db, sequence_id, organization)
    db.delete(seq)  # FK ON DELETE CASCADE removes steps + enrollments
    db.commit()
    return Response(status_code=204)


# ── Enrollment ───────────────────────────────────────────────────────────────

@router.post("/sequences/{sequence_id}/enroll", response_model=EnrollResult)
def enroll_leads(
    sequence_id: UUID,
    payload: EnrollRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    seq = _get_org_sequence_or_404(db, sequence_id, organization)

    settings_row = _get_settings_row(db, organization.id)
    if settings_row is None or not settings_row.smtp_host:
        raise HTTPException(
            status_code=400, detail="Сначала подключите почту в настройках"
        )

    steps = _steps_for(db, seq.id)
    if not steps:
        raise HTTPException(
            status_code=400, detail="В последовательности нет ни одного шага"
        )
    step0 = steps[0]

    # Leads that belong to this org (any outside the org are silently ignored).
    leads = list(
        db.execute(
            select(Lead).where(
                Lead.organization_id == organization.id,
                Lead.id.in_(payload.lead_ids),
            )
        ).scalars()
    )

    # Lead ids that already have an ACTIVE enrollment in THIS sequence.
    already_active = set(
        db.execute(
            select(SequenceEnrollment.lead_id).where(
                SequenceEnrollment.sequence_id == seq.id,
                SequenceEnrollment.status == ACTIVE_ENROLLMENT_STATUS,
            )
        ).scalars()
    )

    requested = len(payload.lead_ids)
    enrolled = 0
    next_send_at = _now_utc() + timedelta(days=step0.delay_days)

    found_ids = set()
    for lead in leads:
        found_ids.add(lead.id)
        if not lead.email or lead.email_opt_out or lead.id in already_active:
            continue
        db.add(
            SequenceEnrollment(
                organization_id=organization.id,
                sequence_id=seq.id,
                lead_id=lead.id,
                status="active",
                current_step=0,
                next_send_at=next_send_at,
                unsubscribe_token=new_unsubscribe_token(),
            )
        )
        enrolled += 1

    db.commit()
    # Everything we couldn't enroll (no email / opted-out / already enrolled /
    # not in this org) counts as skipped.
    skipped = requested - enrolled
    return EnrollResult(enrolled=enrolled, skipped=skipped)


@router.get("/sequences/{sequence_id}/enrollments", response_model=list[EnrollmentOut])
def list_enrollments(
    sequence_id: UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    seq = _get_org_sequence_or_404(db, sequence_id, organization)
    rows = db.execute(
        select(SequenceEnrollment, Lead.company, Lead.email)
        .join(Lead, Lead.id == SequenceEnrollment.lead_id)
        .where(SequenceEnrollment.sequence_id == seq.id)
        .order_by(SequenceEnrollment.enrolled_at.desc())
        .limit(500)
    ).all()
    return [
        EnrollmentOut(
            id=enr.id,
            lead_id=enr.lead_id,
            lead_company=company or "",
            to_email=email or "",
            status=enr.status,
            current_step=enr.current_step,
            next_send_at=enr.next_send_at,
            last_sent_at=enr.last_sent_at,
        )
        for enr, company, email in rows
    ]


@router.post("/enrollments/{enrollment_id}/stop")
def stop_enrollment(
    enrollment_id: UUID,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    enr = db.get(SequenceEnrollment, enrollment_id)
    if not enr or enr.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    enr.status = "stopped"
    enr.stop_reason = "manual"
    db.commit()
    return {"ok": True}


# ── Public unsubscribe (NO auth) ─────────────────────────────────────────────

_UNSUB_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отписка</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         background:#f6f7f9; color:#1f2937; margin:0;
         display:flex; min-height:100vh; align-items:center; justify-content:center; }}
  .card {{ background:#fff; padding:40px 48px; border-radius:14px;
          box-shadow:0 6px 24px rgba(0,0,0,.06); text-align:center; max-width:440px; }}
  h1 {{ font-size:20px; margin:0 0 8px; }}
  p {{ font-size:15px; color:#6b7280; margin:0; }}
</style></head>
<body><div class="card">
  <h1>{title}</h1>
  <p>{body}</p>
</div></body></html>"""


@router.get("/u/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """Public one-click unsubscribe. The token IS the secret, so we look it up
    across all orgs (no auth). Always returns a friendly page — even for an
    unknown token — so we never leak whether a token is valid."""
    enr = db.execute(
        select(SequenceEnrollment).where(
            SequenceEnrollment.unsubscribe_token == token
        )
    ).scalar_one_or_none()

    if enr is not None:
        enr.status = "unsubscribed"
        enr.stop_reason = "unsubscribe"
        lead = db.get(Lead, enr.lead_id)
        if lead is not None:
            lead.email_opt_out = True
        db.commit()

    html = _UNSUB_PAGE.format(
        title="Вы отписались от рассылки.",
        body="Больше писем от этой компании на ваш адрес не придёт.",
    )
    return HTMLResponse(content=html, status_code=200)


# ── Public open/click tracking (NO auth) ─────────────────────────────────────

# A 1×1 transparent GIF, always returned by the open-pixel endpoint regardless
# of whether the token resolved — so we never reveal token validity and never
# break the recipient's email client.
_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


def _find_message_by_token(db: Session, token: str) -> OutreachMessage | None:
    if not token:
        return None
    return db.execute(
        select(OutreachMessage).where(OutreachMessage.track_token == token)
    ).scalar_one_or_none()


@router.get("/t/o/{token}")
def track_open(token: str, db: Session = Depends(get_db)):
    """Public open-pixel. The pixel URL ends in `.gif`; strip it to get the raw
    token. Records the open (first one stamps opened_at) then ALWAYS returns the
    1×1 GIF — unknown/invalid tokens are a silent no-op, never an error."""
    if token.endswith(".gif"):
        token = token[: -len(".gif")]
    msg = _find_message_by_token(db, token)
    if msg is not None:
        if msg.opened_at is None:
            msg.opened_at = _now_utc()
        msg.opens_count = (msg.opens_count or 0) + 1
        db.commit()
    return Response(
        content=_PIXEL_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/t/c/{token}")
def track_click(token: str, u: str = "", db: Session = Depends(get_db)):
    """Public click-tracker. Records the click (and implicitly an open) then
    redirects to the decoded target. Unknown tokens / bad targets fall back to
    the site base; never errors."""
    msg = _find_message_by_token(db, token)
    if msg is not None:
        now = _now_utc()
        if msg.clicked_at is None:
            msg.clicked_at = now
        msg.clicks_count = (msg.clicks_count or 0) + 1
        # A click implies the email was opened, even if the pixel never loaded.
        if msg.opened_at is None:
            msg.opened_at = now
        db.commit()
    target = outreach.decode_click_target(u) or outreach._base_url()
    return RedirectResponse(url=target, status_code=302)


# ── Replies inbox ────────────────────────────────────────────────────────────

@router.get("/replies", response_model=list[ReplyOut])
def list_replies(
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Captured inbound replies for the org, newest first (nulls last), with the
    lead's company joined in."""
    rows = db.execute(
        select(OutreachReply, Lead.company)
        .outerjoin(Lead, Lead.id == OutreachReply.lead_id)
        .where(OutreachReply.organization_id == organization.id)
        .order_by(
            OutreachReply.received_at.desc().nullslast(),
            OutreachReply.created_at.desc(),
        )
        .limit(200)
    ).all()
    return [
        ReplyOut(
            id=reply.id,
            lead_id=reply.lead_id,
            lead_company=company or "",
            from_email=reply.from_email or "",
            subject=reply.subject or "",
            snippet=reply.snippet or "",
            received_at=reply.received_at,
        )
        for reply, company in rows
    ]


# ── AI email generation ──────────────────────────────────────────────────────

@router.post("/ai/generate-email", response_model=AiGenerateResponse)
def ai_generate_email(
    payload: AiGenerateRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    """Draft a subject + body via the LLM. When a project of this org is given,
    derive niche/segments from it; otherwise use the request fields."""
    niche = payload.niche
    segments = payload.segments

    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if (
            project is not None
            and project.organization_id == organization.id
            and project.deleted_at is None
        ):
            niche = project.niche or niche
            segments = project.segments or segments

    result = outreach.generate_email(
        niche=niche,
        segments=segments,
        goal=payload.goal,
        tone=payload.tone,
        step_number=payload.step_number,
        organization_id=str(organization.id),
    )
    if result is None:
        raise HTTPException(
            status_code=503, detail="AI недоступен, попробуйте позже"
        )
    return AiGenerateResponse(subject=result["subject"], body=result["body"])

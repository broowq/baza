"""Background sender for БАЗА's email-outreach drip sequences.

Two Celery-beat tasks:
  • outreach.process_sequences — walks due enrollments and sends the next step
    via the org's own SMTP, advancing the send cursor (OrgEmailSettings).
  • outreach.poll_replies — polls each org's IMAP for replies and auto-stops the
    matching active enrollments so we never keep emailing someone who answered.

Sending is gated by a send-window (off-hours guard) + per-org daily limits, and
every send/failure is logged to OutreachMessage. Guards stop dead enrollments
(no email, opted-out, lead won/rejected) without burning sends.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    EmailSequence,
    Lead,
    LeadStatus,
    OrgEmailSettings,
    OutreachMessage,
    SequenceEnrollment,
    SequenceStep,
)
from app.services.outreach import (
    _to_html,
    append_unsubscribe,
    render_template,
    send_via_smtp,
    unsubscribe_url,
)
from app.services.outreach import poll_replies as imap_poll_replies
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


def within_send_window(now: datetime | None = None) -> bool:
    """Avoid off-hours sends. Default: Mon–Fri, 06:00–17:00 UTC (~09:00–20:00 MSK).

    Module-level so tests can monkeypatch it to always-True.
    """
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return 6 <= now.hour < 17


@celery.task(name="outreach.process_sequences")
def process_email_sequences() -> None:
    """Send the next due step for active enrollments via each org's own SMTP."""
    if not within_send_window():
        logger.debug("process_email_sequences: outside send window, skipping")
        return

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        enrollments = db.execute(
            select(SequenceEnrollment)
            .where(SequenceEnrollment.status == "active")
            .where(SequenceEnrollment.next_send_at.is_not(None))
            .where(SequenceEnrollment.next_send_at <= now)
            .order_by(SequenceEnrollment.next_send_at)
            .limit(500)
        ).scalars().all()
        if not enrollments:
            return

        settings_cache: dict = {}      # org_id -> OrgEmailSettings | None
        org_limit_hit: set = set()     # orgs that hit their daily cap this cycle
        sequence_cache: dict = {}      # sequence_id -> EmailSequence | None
        sent_count = 0

        for enr in enrollments:
            if enr.organization_id in org_limit_hit:
                continue
            try:
                # ── org sending identity ──────────────────────────────────
                if enr.organization_id in settings_cache:
                    settings = settings_cache[enr.organization_id]
                else:
                    settings = db.execute(
                        select(OrgEmailSettings).where(
                            OrgEmailSettings.organization_id == enr.organization_id
                        )
                    ).scalar_one_or_none()
                    settings_cache[enr.organization_id] = settings
                if not settings or not settings.smtp_host:
                    continue  # leave enrollment due until SMTP is configured

                # ── daily limit (per-org, UTC day) ────────────────────────
                today = now.date()
                sent_today_date = (
                    settings.sent_today_date.date()
                    if settings.sent_today_date else None
                )
                if sent_today_date != today:
                    settings.sent_today = 0
                    settings.sent_today_date = now
                if settings.sent_today >= settings.daily_limit:
                    org_limit_hit.add(enr.organization_id)
                    db.commit()  # persist the date-reset above
                    continue

                # ── lead guards (terminal states) ─────────────────────────
                lead = db.get(Lead, enr.lead_id)
                if lead is None:
                    enr.status = "failed"
                    enr.stop_reason = "lead_gone"
                    db.commit()
                    continue
                if not lead.email:
                    enr.status = "failed"
                    enr.stop_reason = "no_email"
                    db.commit()
                    continue
                if lead.email_opt_out:
                    enr.status = "unsubscribed"
                    enr.stop_reason = "opted_out"
                    db.commit()
                    continue
                if lead.status in (LeadStatus.won, LeadStatus.rejected):
                    enr.status = "stopped"
                    enr.stop_reason = "stage"
                    db.commit()
                    continue

                # ── sequence paused/archived → leave active, skip ─────────
                if enr.sequence_id in sequence_cache:
                    seq = sequence_cache[enr.sequence_id]
                else:
                    seq = db.get(EmailSequence, enr.sequence_id)
                    sequence_cache[enr.sequence_id] = seq
                if seq is None or seq.status != "active":
                    continue

                # ── current step ──────────────────────────────────────────
                step = db.execute(
                    select(SequenceStep)
                    .where(SequenceStep.sequence_id == enr.sequence_id)
                    .where(SequenceStep.step_order == enr.current_step)
                ).scalar_one_or_none()
                if step is None:
                    enr.status = "completed"
                    db.commit()
                    continue

                # ── render ────────────────────────────────────────────────
                subject = render_template(step.subject, lead)
                body_text = render_template(step.body, lead)
                body_html = _to_html(body_text)
                unsub = unsubscribe_url(enr.unsubscribe_token)
                body_html, body_text = append_unsubscribe(body_html, body_text, unsub)

                # ── send ──────────────────────────────────────────────────
                try:
                    send_via_smtp(
                        settings,
                        to_email=lead.email,
                        subject=subject,
                        html_body=body_html,
                        text_body=body_text,
                        unsub_url=unsub,
                    )
                except Exception as exc:  # noqa: BLE001
                    db.add(OutreachMessage(
                        organization_id=enr.organization_id,
                        enrollment_id=enr.id,
                        lead_id=lead.id,
                        step_order=enr.current_step,
                        to_email=lead.email,
                        subject=subject,
                        status="failed",
                        error=str(exc)[:300],
                    ))
                    # Simple retry: try again in 2h, do NOT advance the cursor.
                    enr.next_send_at = now + timedelta(hours=2)
                    db.commit()
                    logger.warning(
                        "outreach send failed enr=%s step=%s: %s",
                        enr.id, enr.current_step, type(exc).__name__,
                    )
                    continue

                # ── success: log + count + advance cursor ─────────────────
                db.add(OutreachMessage(
                    organization_id=enr.organization_id,
                    enrollment_id=enr.id,
                    lead_id=lead.id,
                    step_order=enr.current_step,
                    to_email=lead.email,
                    subject=subject,
                    status="sent",
                ))
                settings.sent_today += 1
                enr.last_sent_at = now
                enr.current_step += 1

                next_step = db.execute(
                    select(SequenceStep)
                    .where(SequenceStep.sequence_id == enr.sequence_id)
                    .where(SequenceStep.step_order == enr.current_step)
                ).scalar_one_or_none()
                if next_step is not None:
                    enr.next_send_at = now + timedelta(days=int(next_step.delay_days or 0))
                else:
                    enr.status = "completed"
                    enr.next_send_at = None

                # Best-effort CRM timeline entry.
                try:
                    from app.services.crm import log_activity
                    log_activity(db, lead=lead, kind="email", text=f"Письмо: {subject}")
                except Exception:  # noqa: BLE001
                    logger.debug("log_activity failed for lead=%s", lead.id, exc_info=True)

                db.commit()
                sent_count += 1
            except Exception:
                logger.exception("process_email_sequences: failed on enr=%s", enr.id)
                db.rollback()

        if sent_count:
            logger.info("process_email_sequences: sent %d email(s)", sent_count)
    except Exception:
        logger.exception("process_email_sequences task failed")
        db.rollback()
    finally:
        db.close()


@celery.task(name="outreach.poll_replies")
def poll_email_replies() -> None:
    """Poll each IMAP-configured org for replies; auto-stop matching enrollments."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        # Orgs with at least one active enrollment.
        org_ids = db.execute(
            select(SequenceEnrollment.organization_id)
            .where(SequenceEnrollment.status == "active")
            .distinct()
        ).scalars().all()
        if not org_ids:
            return

        floor = now - timedelta(days=30)
        stopped_total = 0
        for org_id in org_ids:
            try:
                settings = db.execute(
                    select(OrgEmailSettings).where(
                        OrgEmailSettings.organization_id == org_id
                    )
                ).scalar_one_or_none()
                if not settings or not settings.imap_host:
                    continue

                # Active enrollments for this org joined to their leads' emails.
                rows = db.execute(
                    select(Lead.email, SequenceEnrollment.enrolled_at)
                    .join(Lead, Lead.id == SequenceEnrollment.lead_id)
                    .where(SequenceEnrollment.organization_id == org_id)
                    .where(SequenceEnrollment.status == "active")
                    .where(Lead.email.is_not(None))
                ).all()
                addresses = {email for email, _ in rows if email}
                if not addresses:
                    continue

                earliest = min((e for _, e in rows if e is not None), default=now)
                since = max(earliest, floor)

                replied = imap_poll_replies(settings, since, addresses)
                if not replied:
                    continue
                replied_lc = {a.lower() for a in replied}

                active = db.execute(
                    select(SequenceEnrollment)
                    .join(Lead, Lead.id == SequenceEnrollment.lead_id)
                    .where(SequenceEnrollment.organization_id == org_id)
                    .where(SequenceEnrollment.status == "active")
                    .where(Lead.email.is_not(None))
                ).scalars().all()
                # Map enrollment -> lead email for matching.
                for enr in active:
                    lead = db.get(Lead, enr.lead_id)
                    if lead and lead.email and lead.email.lower() in replied_lc:
                        enr.status = "replied"
                        enr.stop_reason = "reply"
                        stopped_total += 1
                db.commit()
            except Exception:
                logger.exception("poll_email_replies: failed on org=%s", org_id)
                db.rollback()

        if stopped_total:
            logger.info("poll_email_replies: stopped %d enrollment(s) on reply", stopped_total)
    except Exception:
        logger.exception("poll_email_replies task failed")
        db.rollback()
    finally:
        db.close()

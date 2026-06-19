"""Email-outreach engine: template rendering + sending via the CLIENT's own SMTP
+ unsubscribe tokens + IMAP reply detection.

Sending always uses the org's OrgEmailSettings (their domain/reputation/consent)
— never our shared transactional sender. Every send carries List-Unsubscribe
headers + a footer link for deliverability and 152-ФЗ/CAN-SPAM opt-out.
"""
from __future__ import annotations

import imaplib
import logging
import re
import secrets
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from app.core.config import get_settings
from app.services.crypto import decrypt_secret

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")


def _lead_field(lead, name: str) -> str:
    if isinstance(lead, dict):
        return str(lead.get(name, "") or "")
    return str(getattr(lead, name, "") or "")


def render_template(text: str, lead) -> str:
    """Substitute {{company}}, {{city}}, {{email}}, {{phone}}, {{domain}},
    {{website}} from the lead. Unknown placeholders are left as-is."""
    allowed = {"company", "city", "email", "phone", "domain", "website", "address"}

    def repl(m: re.Match) -> str:
        key = m.group(1).lower()
        return _lead_field(lead, key) if key in allowed else m.group(0)

    return _VAR_RE.sub(repl, text or "")


def new_unsubscribe_token() -> str:
    return secrets.token_urlsafe(24)


def unsubscribe_url(token: str) -> str:
    base = (get_settings().frontend_app_url or "https://usebaza.ru").rstrip("/")
    return f"{base}/api/outreach/u/{token}"


def _to_html(text: str) -> str:
    return "<br>".join(text.splitlines()) if text else ""


def append_unsubscribe(html_body: str, text_body: str, unsub_url: str) -> tuple[str, str]:
    """Append an unobtrusive unsubscribe footer to both parts."""
    html = (html_body or "") + (
        f'<br><br><hr style="border:none;border-top:1px solid #eee">'
        f'<p style="font-size:12px;color:#888">'
        f'Если письмо отправлено по ошибке — <a href="{unsub_url}">отписаться</a>.'
        f"</p>"
    )
    text = (text_body or "") + f"\n\n—\nОтписаться: {unsub_url}"
    return html, text


def send_via_smtp(
    s,
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    unsub_url: str | None = None,
) -> str:
    """Send one email through the org's SMTP. Returns the Message-ID on success;
    raises on failure (caller logs + marks the message failed)."""
    pw = decrypt_secret(s.smtp_password_enc)
    if not (s.smtp_host and s.smtp_user and pw):
        raise RuntimeError("SMTP не настроен")

    from_addr = s.from_email or s.smtp_user
    msg = EmailMessage()
    msg["From"] = formataddr((s.from_name or "", from_addr))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = from_addr
    msg_id = make_msgid()
    msg["Message-ID"] = msg_id
    if unsub_url:
        msg["List-Unsubscribe"] = f"<{unsub_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text_body or " ")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    host = s.smtp_host
    port = int(s.smtp_port or 587)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=25) as srv:
            srv.login(s.smtp_user, pw)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as srv:
            srv.ehlo()
            if s.smtp_use_tls:
                srv.starttls()
                srv.ehlo()
            srv.login(s.smtp_user, pw)
            srv.send_message(msg)
    return msg_id


def smtp_test(s, to_email: str) -> tuple[bool, str]:
    """Send a test email to verify the org's SMTP. Returns (ok, error)."""
    try:
        send_via_smtp(
            s,
            to_email=to_email,
            subject="БАЗА · проверка отправки",
            html_body="<p>Это тестовое письмо из БАЗА. Отправка через ваш SMTP работает ✅</p>",
            text_body="Это тестовое письмо из БАЗА. Отправка через ваш SMTP работает.",
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001 — surface the real reason to the user
        return False, f"{type(exc).__name__}: {exc}"[:300]


def poll_replies(s, since: datetime, addresses: set[str]) -> set[str]:
    """Best-effort IMAP poll: return the subset of `addresses` (lowercased) that
    have sent us mail since `since`. Empty set if IMAP unconfigured or on error."""
    addrs = {a.lower() for a in addresses if a}
    pw = decrypt_secret(s.imap_password_enc)
    if not (s.imap_host and s.imap_user and pw and addrs):
        return set()
    replied: set[str] = set()
    box = None
    try:
        box = imaplib.IMAP4_SSL(s.imap_host, int(s.imap_port or 993))
        box.login(s.imap_user, pw)
        box.select("INBOX", readonly=True)
        typ, data = box.search(None, f'(SINCE {since.strftime("%d-%b-%Y")})')
        if typ != "OK" or not data or not data[0]:
            return set()
        ids = data[0].split()[-1000:]  # cap scan
        for num in ids:
            typ, md = box.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
            if typ != "OK" or not md or not md[0]:
                continue
            raw = md[0][1].decode("utf-8", "ignore") if isinstance(md[0][1], bytes) else str(md[0][1])
            sender = parseaddr(raw.split(":", 1)[-1])[1].lower()
            if sender in addrs:
                replied.add(sender)
    except Exception as exc:  # noqa: BLE001
        logger.warning("IMAP reply-poll failed: %s", type(exc).__name__)
    finally:
        if box is not None:
            try:
                box.logout()
            except Exception:
                pass
    return replied

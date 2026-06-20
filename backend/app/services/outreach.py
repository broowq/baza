"""Email-outreach engine: template rendering + sending via the CLIENT's own SMTP
+ unsubscribe tokens + IMAP reply detection.

Sending always uses the org's OrgEmailSettings (their domain/reputation/consent)
— never our shared transactional sender. Every send carries List-Unsubscribe
headers + a footer link for deliverability and 152-ФЗ/CAN-SPAM opt-out.
"""
from __future__ import annotations

import base64
import email as _email
import imaplib
import json as _json
import logging
import re
import secrets
import smtplib
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parsedate_to_datetime, parseaddr

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


# ── Open/click tracking ─────────────────────────────────────────────────────

def new_track_token() -> str:
    return secrets.token_urlsafe(18)


def _base_url() -> str:
    return (get_settings().frontend_app_url or "https://usebaza.ru").rstrip("/")


def tracking_pixel_url(token: str) -> str:
    # No ".gif" suffix on purpose: nginx's static-asset regex location
    # (location ~* \.(...|gif|...)$) would otherwise intercept the request and
    # serve a 404 instead of proxying to the backend. Email clients render the
    # image from the Content-Type header, not the URL extension, so an
    # extensionless URL works everywhere. The route still strips a trailing
    # ".gif" defensively for any already-sent links.
    return f"{_base_url()}/api/outreach/t/o/{token}"


def click_url(token: str, target: str) -> str:
    enc = base64.urlsafe_b64encode((target or "").encode("utf-8")).decode("ascii")
    return f"{_base_url()}/api/outreach/t/c/{token}?u={enc}"


_HREF_RE = re.compile(r'(<a\b[^>]*?\bhref=")(https?://[^"]+)(")', re.IGNORECASE)


def inject_tracking(html_body: str, token: str) -> str:
    """Rewrite http(s) links to go through the click-tracker and append a 1×1
    open pixel. Safe no-op for empty bodies / no links."""
    if not html_body:
        html_body = ""
    html = _HREF_RE.sub(lambda m: m.group(1) + click_url(token, m.group(2)) + m.group(3), html_body)
    pixel = f'<img src="{tracking_pixel_url(token)}" width="1" height="1" alt="" style="display:none">'
    return html + pixel


def decode_click_target(enc: str) -> str:
    """Decode a click-tracker target; "" if invalid or not http(s)."""
    try:
        url = base64.urlsafe_b64decode(enc.encode("ascii")).decode("utf-8")
    except Exception:
        return ""
    return url if url.startswith(("http://", "https://")) else ""


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


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "")


def fetch_replies(s, since: datetime, addresses: set[str]) -> list[dict]:
    """Like poll_replies but returns reply DETAIL for the inbox:
    [{from_email, subject, snippet, received_at(naive UTC|None)}]. Best-effort."""
    addrs = {a.lower() for a in addresses if a}
    pw = decrypt_secret(s.imap_password_enc)
    if not (s.imap_host and s.imap_user and pw and addrs):
        return []
    out: list[dict] = []
    box = None
    try:
        box = imaplib.IMAP4_SSL(s.imap_host, int(s.imap_port or 993))
        box.login(s.imap_user, pw)
        box.select("INBOX", readonly=True)
        typ, data = box.search(None, f'(SINCE {since.strftime("%d-%b-%Y")})')
        if typ != "OK" or not data or not data[0]:
            return []
        for num in data[0].split()[-1000:]:
            typ, md = box.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not md or not md[0]:
                continue
            raw = md[0][1].decode("utf-8", "ignore") if isinstance(md[0][1], (bytes, bytearray)) else str(md[0][1])
            hdr = _email.message_from_string(raw)
            sender = parseaddr(hdr.get("From", ""))[1].lower()
            if sender not in addrs:
                continue
            try:
                subject = str(make_header(decode_header(hdr.get("Subject", ""))))[:300]
            except Exception:
                subject = (hdr.get("Subject", "") or "")[:300]
            received = None
            try:
                received = parsedate_to_datetime(hdr.get("Date", ""))
                if received and received.tzinfo:
                    received = received.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                received = None
            snippet = ""
            try:
                t2, bd = box.fetch(num, "(BODY.PEEK[1]<0.700>)")
                if t2 == "OK" and bd and bd[0] and isinstance(bd[0][1], (bytes, bytearray)):
                    snippet = bd[0][1].decode("utf-8", "ignore")
            except Exception:
                pass
            snippet = re.sub(r"\s+", " ", _strip_tags(snippet)).strip()[:500]
            out.append({"from_email": sender, "subject": subject, "snippet": snippet, "received_at": received})
    except Exception as exc:  # noqa: BLE001
        logger.warning("IMAP fetch_replies failed: %s", type(exc).__name__)
    finally:
        if box is not None:
            try:
                box.logout()
            except Exception:
                pass
    return out


def generate_email(*, niche: str, segments: list[str] | None, goal: str = "",
                   tone: str = "", step_number: int = 1,
                   organization_id: str | None = None) -> dict | None:
    """Generate a cold-outreach subject+body via the LLM (metered to the org).
    Returns {"subject","body"} or None if unavailable/unparseable."""
    from app.services import llm_client
    if not llm_client.is_configured():
        return None
    segs = ", ".join([s for s in (segments or []) if s]) or "—"
    system = (
        "Ты — эксперт по холодным B2B email-рассылкам на русском языке. "
        "Пиши коротко, по делу, без воды и спам-слов (никаких «уникальное предложение», "
        "«только сегодня»). Верни СТРОГО JSON {\"subject\": \"...\", \"body\": \"...\"} "
        "без markdown и пояснений."
    )
    user = (
        f"Компания-отправитель продаёт: {niche or 'свой продукт'}.\n"
        f"Целевые клиенты (сегменты): {segs}.\n"
        f"Цель письма: {goal or 'первое касание, договориться о коротком звонке'}.\n"
        f"Тон: {tone or 'деловой, дружелюбный, на «вы»'}.\n"
        f"Это письмо №{step_number or 1} в цепочке "
        f"({'первое касание' if (step_number or 1) <= 1 else 'follow-up, мягко напомнить'}).\n"
        "Используй плейсхолдер {{company}} для названия компании-получателя. "
        "Тема — до 60 символов, без CAPS. Тело — 4–7 коротких предложений с понятным CTA."
    )
    raw = llm_client.chat(user, system=system, max_tokens=700, temperature=0.6,
                          organization_id=organization_id)
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        obj = _json.loads(m.group(0))
    except Exception:
        return None
    subject = str(obj.get("subject", "")).strip()[:300]
    body = str(obj.get("body", "")).strip()[:6000]
    if not subject or not body:
        return None
    return {"subject": subject, "body": body}

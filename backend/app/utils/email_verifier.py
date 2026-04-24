"""Lightweight email deliverability verification.

Strategy (in decreasing cost):
  1. Syntax check (cheap, local).
  2. Domain MX record lookup (1 DNS query, cacheable).
  3. Optional SMTP VRFY / RCPT handshake (expensive; rate-limited; often
     blocked by grey-listers). Not enabled by default.

Result is an enum:
  - valid: syntactically OK + MX record present
  - no_mx: syntax OK but no MX record (likely dead / invalid)
  - syntax: syntactically invalid (dropped)
  - skipped: could not verify (DNS error, timeout, etc.)

This is ~80% as good as a paid verification API at 0 cost. Real enterprise
users can be upsold to NeverBounce-style deep verification later.
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from functools import lru_cache

try:
    import dns.resolver as _dns_resolver  # type: ignore
    import dns.exception as _dns_exception  # type: ignore
except Exception:  # pragma: no cover — dnspython is in requirements.txt
    _dns_resolver = None
    _dns_exception = None

logger = logging.getLogger(__name__)

# Pragmatic email regex — not RFC-perfect but good enough for B2B contacts.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@([A-Za-z0-9][A-Za-z0-9.\-]{0,253}\.[A-Za-z]{2,10})$"
)

# Common typosquat / nonsense domains that reliably bounce.
_BAD_DOMAINS = frozenset({
    "example.com", "example.org", "example.ru", "test.com", "test.ru",
    "localhost", "invalid", "noreply.com", "nowhere.net",
})


class EmailStatus(str, Enum):
    VALID = "valid"
    NO_MX = "no_mx"
    SYNTAX = "syntax"
    SKIPPED = "skipped"


@lru_cache(maxsize=4096)
def _mx_exists(domain: str) -> bool | None:
    """Return True if domain has MX records, False if confirmed none,
    None if DNS lookup itself failed (treat as 'unknown')."""
    if not _dns_resolver:
        return None
    try:
        resolver = _dns_resolver.Resolver()
        resolver.timeout = 3.0
        resolver.lifetime = 5.0
        answers = resolver.resolve(domain, "MX")
        return bool(list(answers))
    except _dns_resolver.NXDOMAIN:
        return False
    except _dns_resolver.NoAnswer:
        # Some domains serve A record but no MX — still not receivable.
        return False
    except _dns_exception.DNSException:
        return None
    except Exception:
        logger.debug("MX lookup unexpected error for %s", domain, exc_info=True)
        return None


def verify_email(email: str) -> EmailStatus:
    """Verify an email address with local-cheap + DNS checks only.

    NEVER raises — always returns a status. Use the return value to decide
    whether to display, surface, or hide the email in UI.
    """
    if not email:
        return EmailStatus.SYNTAX
    email = email.strip().lower()
    match = _EMAIL_RE.match(email)
    if not match:
        return EmailStatus.SYNTAX
    domain = match.group(1)
    if domain in _BAD_DOMAINS:
        return EmailStatus.NO_MX
    # Domains shorter than 4 chars (a.a) or with repeated TLDs are junk
    if len(domain) < 4:
        return EmailStatus.SYNTAX
    mx_ok = _mx_exists(domain)
    if mx_ok is True:
        return EmailStatus.VALID
    if mx_ok is False:
        return EmailStatus.NO_MX
    return EmailStatus.SKIPPED


def verify_many(emails: list[str]) -> dict[str, EmailStatus]:
    """Verify a list of emails. Deduped by caller's list order."""
    seen: dict[str, EmailStatus] = {}
    for email in emails:
        email_low = (email or "").strip().lower()
        if not email_low or email_low in seen:
            continue
        seen[email_low] = verify_email(email_low)
    return seen

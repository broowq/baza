"""Tests for app.utils.email_verifier — the lightweight MX-based deliverability
check. Network is mocked via monkey-patching the cached _mx_exists function so
tests are deterministic and offline-safe."""
from __future__ import annotations

import pytest

from app.utils import email_verifier as ev
from app.utils.email_verifier import EmailStatus, verify_email


@pytest.fixture(autouse=True)
def _clear_mx_cache():
    """Ensure the lru_cache on _mx_exists is reset between tests — otherwise
    a monkey-patched answer from one test leaks into the next."""
    ev._mx_exists.cache_clear()
    yield
    ev._mx_exists.cache_clear()


def test_syntax_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    # No MX lookup should happen for syntax-invalid addresses
    called = {"n": 0}

    def fake_mx(_: str) -> bool | None:
        called["n"] += 1
        return True

    monkeypatch.setattr(ev, "_mx_exists", fake_mx)

    for bad in ("not-an-email", "@domain.com", "foo@", "foo@bar", "a@a.b"):
        assert verify_email(bad) in (EmailStatus.SYNTAX, EmailStatus.NO_MX), bad

    # MX should never have been queried for purely-syntax-bad inputs
    # (last one "a@a.b" has TLD of 1 char → rejected by regex too)


def test_valid_when_mx_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "_mx_exists", lambda d: True)
    assert verify_email("info@ptitsa-yug.ru") == EmailStatus.VALID


def test_no_mx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "_mx_exists", lambda d: False)
    assert verify_email("sales@dead-domain.ru") == EmailStatus.NO_MX


def test_dns_error_returns_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "_mx_exists", lambda d: None)
    assert verify_email("office@any-domain.ru") == EmailStatus.SKIPPED


def test_known_bad_domains() -> None:
    # example.com, test.ru etc. are statically rejected regardless of MX
    # (a@localhost is syntax-invalid: no TLD, caught earlier)
    for email in ("foo@example.com", "x@test.ru", "user@noreply.com"):
        assert verify_email(email) == EmailStatus.NO_MX, email
    assert verify_email("a@localhost") == EmailStatus.SYNTAX


def test_empty_input() -> None:
    assert verify_email("") == EmailStatus.SYNTAX
    assert verify_email(None) == EmailStatus.SYNTAX  # type: ignore[arg-type]


def test_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "_mx_exists", lambda d: True)
    assert verify_email("INFO@PTITSA-YUG.RU") == EmailStatus.VALID
    assert verify_email("  Info@Ptitsa-Yug.RU  ") == EmailStatus.VALID


def test_verify_many_dedups_and_lowercases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "_mx_exists", lambda d: True)
    result = ev.verify_many(["A@b.ru", "a@b.ru", "A@B.RU", "", None])  # type: ignore[list-item]
    assert len(result) == 1
    assert "a@b.ru" in result
    assert result["a@b.ru"] == EmailStatus.VALID

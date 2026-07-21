"""Юнит-тесты харденинга безопасности (аудит 22.07.2026).

Быстрые проверки без БД: SSRF-гард URL, CSV/XLSX formula-injection,
маскирование ПД в логах, SSRF исходящего вебхука.
"""
from __future__ import annotations

import pytest

from app.api.routes.leads import _formula_safe
from app.utils.logredact import mask_email
from app.utils.url_tools import _is_safe_url


# ── SSRF-гард URL ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # облачная метадата (link-local)
    "http://127.0.0.1/",                            # loopback
    "http://localhost/admin",                       # loopback по имени
    "http://0.0.0.0/",                              # unspecified
    "http://10.0.0.5/internal",                     # приватная сеть
    "http://192.168.1.1/",                          # приватная сеть
    "http://[::1]/",                                # IPv6 loopback
    "http://[::ffff:169.254.169.254]/",             # IPv4-mapped IPv6 метадата
    "http://[::ffff:127.0.0.1]/",                   # IPv4-mapped IPv6 loopback
    "http://foo.internal/",                         # внутренний TLD
    "ftp://example.com/",                           # не-http схема
    "file:///etc/passwd",                           # file-схема
    "gopher://example.com/",                        # gopher-схема
])
def test_is_safe_url_blocks_internal_and_bad_schemes(url):
    assert _is_safe_url(url) is False, url


@pytest.mark.parametrize("url", [
    "https://example.com/",
    "http://usebaza.ru/webhook",
    "https://bitrix24.ru/hook/123",
])
def test_is_safe_url_allows_public(url):
    # Публичные хосты проходят (или молча allow при неразрешимом DNS в CI —
    # httpx упадёт естественно). Главное — не False из-за ошибочной логики.
    assert _is_safe_url(url) is True, url


# ── CSV/XLSX formula-injection ───────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "expected"), [
    ("=cmd|'/c calc'!A1", "'=cmd|'/c calc'!A1"),
    ("+79990000000", "'+79990000000"),
    ("-1+1", "'-1+1"),
    ("@SUM(A1:A9)", "'@SUM(A1:A9)"),
    ("\t=1", "'\t=1"),
    ("ООО Ромашка", "ООО Ромашка"),          # обычный текст не трогаем
    ("info@firm.ru", "info@firm.ru"),         # email в середине — ок
    ("", ""),
])
def test_formula_safe(raw, expected):
    assert _formula_safe(raw) == expected


def test_formula_safe_passes_non_strings():
    assert _formula_safe(42) == 42
    assert _formula_safe(None) is None


# ── Маскирование ПД ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "expected"), [
    ("ivan.petrov@example.com", "i***@example.com"),
    ("a@b.ru", "a***@b.ru"),
    ("@nolocal.ru", "***@nolocal.ru"),
    ("", "<hidden>"),
    ("garbage", "<hidden>"),
    (None, "<hidden>"),
])
def test_mask_email(raw, expected):
    assert mask_email(raw) == expected


# ── SSRF исходящего CRM-вебхука ──────────────────────────────────────────────

def test_push_lead_webhook_blocks_internal_target():
    """Вебхук на внутренний адрес не должен делать сетевой запрос — сразу False."""
    from app.tasks.webhook_tasks import push_lead_webhook

    # Bound-таск вызываем синхронно; _is_safe_url отсекает до любого httpx.
    result = push_lead_webhook.run("http://169.254.169.254/steal", {"id": "x", "email": "a@b.ru"})
    assert result is False


def test_push_lead_webhook_empty_url_false():
    from app.tasks.webhook_tasks import push_lead_webhook

    assert push_lead_webhook.run("", {"id": "x"}) is False

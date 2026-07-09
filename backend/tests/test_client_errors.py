"""Репортер клиентских JS-ошибок (наблюдаемость «Что-то пошло не так»)."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app

_client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "_get_rate_limit", lambda *a, **k: None)


def test_report_accepted_and_logged(caplog):
    with caplog.at_level(logging.ERROR, logger="client_errors"):
        r = _client.post(
            "/api/client-errors",
            json={
                "message": "TypeError: Cannot read properties of undefined",
                "stack": "at SettingsPage (settings/page.tsx:42)",
                "component_stack": "in SettingsPage\nin ErrorBoundary",
                "url": "https://usebaza.ru/dashboard/settings",
                "error_id": "ab12cd",
            },
        )
    assert r.status_code == 204, r.text
    joined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "ab12cd" in joined
    assert "Cannot read properties of undefined" in joined
    assert "dashboard/settings" in joined


def test_report_works_without_auth_and_optional_fields():
    r = _client.post("/api/client-errors", json={"message": "boom"})
    assert r.status_code == 204, r.text


def test_oversized_fields_rejected_422():
    r = _client.post(
        "/api/client-errors",
        json={"message": "x" * 2000},  # max_length=1000
    )
    assert r.status_code == 422


def test_rate_limit_tier_exists():
    """Неаутентифицированный лог-эндпоинт обязан быть задушен жёстче general-API."""
    import app.main as main
    tier = next(
        (t for t in main._RATE_LIMIT_TIERS if t[0] == "/api/client-errors"), None
    )
    assert tier is not None, "нет rate-limit тира для /api/client-errors"
    generic = next(t for t in main._RATE_LIMIT_TIERS if t[0] == "/api/")
    assert tier[1] < generic[1], "репортер должен быть строже общего API-тира"
    # и тир стоит РАНЬШЕ generic /api/ (первый матч выигрывает)
    tiers = [t[0] for t in main._RATE_LIMIT_TIERS]
    assert tiers.index("/api/client-errors") < tiers.index("/api/")

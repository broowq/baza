"""Анти-брутфорс логина (services/login_guard.py, аудит 22.07.2026).

Юнит-слой: порог блокировки, сброс на успехе, fail-open при падении Redis,
отключение в dev, отсутствие enumeration (ключ по нормализованному email).
"""
from __future__ import annotations

import pytest
import redis as redis_lib
from fastapi import HTTPException

from app.services import login_guard as lg


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self.key = None

            def incr(self, key):
                self.key = key
                outer.store[key] = int(outer.store.get(key, 0)) + 1
                return self

            def expire(self, key, ttl):
                return self

            def execute(self):
                return [outer.store[self.key], True]

        return _Pipe()


class _DeadRedis:
    def get(self, key):
        raise redis_lib.exceptions.ConnectionError("down")

    def delete(self, key):
        raise redis_lib.exceptions.ConnectionError("down")

    def pipeline(self):
        raise redis_lib.exceptions.ConnectionError("down")


@pytest.fixture
def prod(monkeypatch):
    """Прод-режим (в dev гвард отключён) + свежий фейковый Redis + порог 5."""
    monkeypatch.setattr(lg.settings, "app_env", "production")
    monkeypatch.setattr(lg.settings, "login_max_failed_attempts", 5)
    monkeypatch.setattr(lg.settings, "login_lockout_minutes", 15)
    fake = _FakeRedis()
    monkeypatch.setattr(lg, "_redis", fake)
    return fake


# ── ключ ─────────────────────────────────────────────────────────────────────

def test_key_normalizes_and_hashes():
    # Регистр/пробелы не влияют — один ключ.
    assert lg._fail_key("User@Example.com ") == lg._fail_key("user@example.com")
    # Разные адреса — разные ключи.
    assert lg._fail_key("a@x.ru") != lg._fail_key("b@x.ru")
    # Ключ не содержит сам email (в Redis нет ПД).
    assert "user@example.com" not in lg._fail_key("user@example.com")


# ── порог и кулдаун ──────────────────────────────────────────────────────────

def test_locks_after_threshold(prod):
    email = "victim@corp.ru"
    # 5 неудач — каждая проходит ensure (счётчик ещё ниже порога), потом note.
    for _ in range(5):
        lg.ensure_login_not_locked(email)  # не бросает
        lg.note_failed_login(email)
    # 6-я попытка блокируется 429 с Retry-After.
    with pytest.raises(HTTPException) as exc:
        lg.ensure_login_not_locked(email)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    assert int(exc.value.headers["Retry-After"]) == 15 * 60


def test_success_resets_counter(prod):
    email = "typo@corp.ru"
    for _ in range(3):
        lg.ensure_login_not_locked(email)
        lg.note_failed_login(email)
    # Честный юзер наконец ввёл верный пароль → сброс.
    lg.note_successful_login(email)
    # После сброса снова 5 попыток до блокировки.
    for _ in range(5):
        lg.ensure_login_not_locked(email)
        lg.note_failed_login(email)
    with pytest.raises(HTTPException):
        lg.ensure_login_not_locked(email)


def test_other_account_not_affected(prod):
    for _ in range(6):
        lg.note_failed_login("target@corp.ru")
    # Заблокирован только целевой аккаунт.
    with pytest.raises(HTTPException):
        lg.ensure_login_not_locked("target@corp.ru")
    lg.ensure_login_not_locked("bystander@corp.ru")  # не бросает


# ── fail-open / dev ──────────────────────────────────────────────────────────

def test_fail_open_when_redis_down(monkeypatch):
    monkeypatch.setattr(lg.settings, "app_env", "production")
    monkeypatch.setattr(lg, "_redis", _DeadRedis())
    # Redis лёг — вход важнее лимита: не блокируем и не 500-им.
    lg.ensure_login_not_locked("x@corp.ru")
    lg.note_failed_login("x@corp.ru")
    lg.note_successful_login("x@corp.ru")


def test_disabled_in_dev(monkeypatch):
    monkeypatch.setattr(lg.settings, "app_env", "development")
    fake = _FakeRedis()
    monkeypatch.setattr(lg, "_redis", fake)
    for _ in range(50):
        lg.ensure_login_not_locked("dev@corp.ru")
        lg.note_failed_login("dev@corp.ru")
    # В dev счётчик даже не пишется.
    assert fake.store == {}

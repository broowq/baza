"""Анти-мультиакк регистрации (14.07.2026) — юнит-слой.

Триал (10 разовых лидов) фермится без трёх защит: нормализация identity
почты (plus-теги/точки Gmail/алиасы Яндекса), блок-лист одноразовых почт,
суточный потолок регистраций с IP. E2E-путь (409 на алиас, книга триалов
после удаления аккаунта) — в tests/e2e/test_e2e_auth_account.py.
"""
from __future__ import annotations

import pytest
import redis as redis_lib
from fastapi import HTTPException

from app.services import registration_guard as rg


# ── нормализация identity ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Vasya@Gmail.com", "vasya@gmail.com"),
        ("vasya+trial2@gmail.com", "vasya@gmail.com"),          # plus-тег
        ("v.a.s.y.a@gmail.com", "vasya@gmail.com"),             # точки Gmail
        ("v.asya+x@googlemail.com", "vasya@gmail.com"),         # алиас домена + всё сразу
        ("vasya@ya.ru", "vasya@yandex.ru"),                     # алиасы Яндекса
        ("va.sya@yandex.com", "va-sya@yandex.ru"),              # . ≡ - в логинах Яндекса
        ("va-sya@yandex.ru", "va-sya@yandex.ru"),
        ("vasya@yandex.com.tr", "vasya@yandex.ru"),            # исторические TLD Яндекса
        ("vasya@me.com", "vasya@icloud.com"),                  # один Apple ID — один ящик
        ("va.sya@mac.com", "va.sya@icloud.com"),               # точки вне Gmail значимы
        ("vasya+tag@mail.ru", "vasya@mail.ru"),                 # plus-тег у mail.ru
        ("v.asya@mail.ru", "v.asya@mail.ru"),                   # точки НЕ гмейловские — значимы
        ("director@zavod-perm.ru", "director@zavod-perm.ru"),   # обычный корп-домен
        ("  UPPER@CASE.RU ", "upper@case.ru"),
        ("noatsign", "noatsign"),                               # мусор не роняет
    ],
)
def test_normalize_email_identity(raw, expected):
    assert rg.normalize_email_identity(raw) == expected


def test_trial_identity_hash_stable_and_blind():
    h1 = rg.trial_identity_hash("vasya@gmail.com")
    h2 = rg.trial_identity_hash("vasya@gmail.com")
    assert h1 == h2 and len(h1) == 64
    # хэш не содержит исходный адрес (в книге триалов нет ПД)
    assert "vasya" not in h1 and "gmail" not in h1
    assert rg.trial_identity_hash("petya@gmail.com") != h1


# ── одноразовые почты ────────────────────────────────────────────────────────

def test_disposable_detection():
    assert rg.is_disposable_email("x@temp-mail.org")
    assert rg.is_disposable_email("x@TEMP-MAIL.ORG")
    assert rg.is_disposable_email("x@abc123.mailinator.com")  # поддомен-ротация
    assert not rg.is_disposable_email("x@gmail.com")
    assert not rg.is_disposable_email("x@zavod-perm.ru")
    assert not rg.is_disposable_email("")


def test_disposable_extra_domains_from_env(monkeypatch):
    monkeypatch.setattr(rg.settings, "disposable_email_domains_extra", "evil.example, spam.test")
    assert rg.is_disposable_email("x@evil.example")
    assert rg.is_disposable_email("x@sub.spam.test")
    assert not rg.is_disposable_email("x@good.example")


def test_disposable_rejected_with_400(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        rg.ensure_registration_allowed("bot@yopmail.com", "1.2.3.4")
    assert exc.value.status_code == 400
    assert "Временные email" in exc.value.detail


# ── суточный потолок регистраций с IP ────────────────────────────────────────

class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

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

    def pipeline(self):
        raise redis_lib.exceptions.ConnectionError("down")


@pytest.fixture
def prod_guard(monkeypatch):
    """Гвард в прод-режиме (в dev потолок отключён ради e2e-сьюта)."""
    monkeypatch.setattr(rg.settings, "app_env", "production")
    monkeypatch.setattr(rg.settings, "registration_attempts_per_ip_per_day", 3)
    fake = _FakeRedis()
    monkeypatch.setattr(rg, "_redis", fake)
    return fake


def test_ip_daily_cap_counts_successes_not_attempts(prod_guard):
    """409-опечатки честного пользователя не тратят общий потолок NAT:
    считаются только успешные регистрации (note_successful_registration)."""
    for _ in range(10):  # десять «неуспешных попыток» — ensure не инкрементит
        rg.ensure_registration_allowed("ok@corp-domain.ru", "5.5.5.5")
    for _ in range(3):  # три успеха — потолок выбран
        rg.ensure_registration_allowed("ok@corp-domain.ru", "5.5.5.5")
        rg.note_successful_registration("5.5.5.5")
    with pytest.raises(HTTPException) as exc:
        rg.ensure_registration_allowed("ok2@corp-domain.ru", "5.5.5.5")
    assert exc.value.status_code == 429
    assert "Слишком много регистраций" in exc.value.detail
    # другой IP — не затронут
    rg.ensure_registration_allowed("ok3@corp-domain.ru", "6.6.6.6")


def test_ip_cap_fail_open_when_redis_down(monkeypatch):
    monkeypatch.setattr(rg.settings, "app_env", "production")
    monkeypatch.setattr(rg, "_redis", _DeadRedis())
    # Redis лёг — регистрация важнее лимита, не 500-им и не блокируем
    rg.ensure_registration_allowed("ok@corp-domain.ru", "7.7.7.7")
    rg.note_successful_registration("7.7.7.7")  # и note не роняет


def test_dev_mode_cap_effectively_off(monkeypatch):
    monkeypatch.setattr(rg.settings, "app_env", "development")
    fake = _FakeRedis()
    monkeypatch.setattr(rg, "_redis", fake)
    for _ in range(50):
        rg.ensure_registration_allowed("ok@corp-domain.ru", "8.8.8.8")
        rg.note_successful_registration("8.8.8.8")


# ── доменный потолок: хэш домена и freemail-исключения ───────────────────────

def test_trial_domain_hash_folds_aliases():
    assert rg.trial_domain_hash("a@ya.ru") == rg.trial_domain_hash("b@yandex.ru")
    assert rg.trial_domain_hash("a@corp-one.ru") != rg.trial_domain_hash("a@corp-two.ru")
    h = rg.trial_domain_hash("a@corp-one.ru")
    assert len(h) == 64 and "corp-one" not in h  # хэш, не домен


def test_is_freemail_domain():
    assert rg.is_freemail_domain("x@gmail.com")
    assert rg.is_freemail_domain("x@ya.ru")        # алиас схлопнут до yandex.ru
    assert rg.is_freemail_domain("x@bk.ru")        # семейство mail.ru
    assert not rg.is_freemail_domain("x@zavod-perm.ru")
    assert not rg.is_freemail_domain("")

"""TRUE E2E: auth + account lifecycle.

Drives the real FastAPI app through real HTTP, real JWT issuance/verification,
real Postgres and real Redis (forgot/reset tokens live in Redis). Email sending
is stubbed by conftest's _quiet_notifications fixture; Celery is eager.

Covers: register happy path, duplicate email / duplicate org rejection,
weak-password 422, login wrong-password / unknown-email 401, refresh→new access,
GET /auth/me shape, change-password (new works / old fails + refresh revoked),
forgot-password generic non-leaking response, GET /auth/me/export shape,
DELETE /auth/me (then login fails), and the reset-password request flow.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Membership, Organization, User

# The auth route uses a module-level redis client; reuse it so the test reads
# the SAME Redis the request handler wrote to (reset/verify tokens live here).
from app.api.routes.auth import redis_client


def _unique_email() -> str:
    return f"e2e-auth-{uuid.uuid4().hex[:10]}@example.com"


def _unique_org() -> str:
    return f"E2E Auth Org {uuid.uuid4().hex[:10]}"


def _register_payload(email: str | None = None, org: str | None = None, **over) -> dict:
    return {
        "email": email or _unique_email(),
        "full_name": over.get("full_name", "Иван Тестов"),
        "password": over.get("password", "password123"),
        "organization_name": org or _unique_org(),
    }


# ── register ────────────────────────────────────────────────────────────────

def test_register_happy_path_returns_tokens_and_persists(client, db):
    payload = _register_payload()
    try:
        r = client.post("/api/auth/register", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        # Tokens are usable bearer creds.
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"
        # email_verification_required is OFF in this env → user is logged in now.
        assert body["email_verification_required"] is False

        # The freshly minted access token authenticates against /me for real.
        me = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["email"] == payload["email"].lower()

        # Persisted: user row, org row, owner membership.
        user = db.execute(
            select(User).where(User.email == payload["email"].lower())
        ).scalar_one()
        assert user.full_name == payload["full_name"]
        assert user.hashed_password != payload["password"], "password must be hashed"
        assert user.email_verified is True  # verification not required → auto-verified
        org = db.execute(
            select(Organization).where(Organization.name == payload["organization_name"])
        ).scalar_one()
        membership = db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organization_id == org.id,
            )
        ).scalar_one()
        assert membership.role == "owner"
    finally:
        _purge(db, payload["email"].lower(), payload["organization_name"])


def test_register_email_normalized_to_lowercase(client, db):
    raw = f"E2E-Auth-{uuid.uuid4().hex[:8]}@Example.COM"
    payload = _register_payload(email=raw)
    try:
        r = client.post("/api/auth/register", json=payload)
        assert r.status_code == 200, r.text
        # The user row is stored lowercased; login with the lowered form works.
        row = db.execute(select(User).where(User.email == raw.lower())).scalar_one_or_none()
        assert row is not None
        login = client.post("/api/auth/login", json={"email": raw, "password": "password123"})
        assert login.status_code == 200, login.text
    finally:
        _purge(db, raw.lower(), payload["organization_name"])


def test_register_duplicate_email_rejected(client, db):
    email = _unique_email()
    first = _register_payload(email=email)
    try:
        r1 = client.post("/api/auth/register", json=first)
        assert r1.status_code == 200, r1.text
        # Same email, DIFFERENT org name → must be refused on the email.
        r2 = client.post("/api/auth/register", json=_register_payload(email=email))
        assert r2.status_code == 409, r2.text
        assert "email" in r2.json()["detail"].lower() or "Email" in r2.json()["detail"]
    finally:
        _purge(db, email, first["organization_name"])


def test_register_duplicate_org_name_rejected(client, db):
    org = _unique_org()
    first = _register_payload(org=org)
    second_email = _unique_email()
    try:
        r1 = client.post("/api/auth/register", json=first)
        assert r1.status_code == 200, r1.text
        # Different email, SAME org name → must be refused on the org.
        r2 = client.post("/api/auth/register", json=_register_payload(email=second_email, org=org))
        assert r2.status_code == 409, r2.text
        assert "рганизаци" in r2.json()["detail"]  # "Организация ... уже существует"
        # The second user must NOT have been created.
        assert (
            db.execute(select(User).where(User.email == second_email)).scalar_one_or_none()
            is None
        )
    finally:
        _purge(db, first["email"].lower(), org)


@pytest.mark.parametrize("bad_password", ["short", "1234567"])  # < 8 chars
def test_register_weak_password_422(client, bad_password):
    r = client.post("/api/auth/register", json=_register_payload(password=bad_password))
    assert r.status_code == 422, r.text


def test_register_invalid_email_422(client):
    payload = _register_payload()
    payload["email"] = "not-an-email"
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 422, r.text


# ── login ───────────────────────────────────────────────────────────────────

def test_login_happy_path(make_account):
    acct = make_account()
    r = acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": acct.password}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    # The login-issued token is a real working access token.
    me = acct.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == acct.email


def _refresh_cookie_maxage(response) -> int | None:
    """Max-Age refresh-cookie из Set-Cookie ответа (или None, если нет)."""
    from app.core.config import get_settings
    name = get_settings().refresh_cookie_name
    for h in response.headers.get_list("set-cookie"):
        if h.startswith(f"{name}="):
            for part in h.split(";"):
                p = part.strip().lower()
                if p.startswith("max-age="):
                    return int(p.split("=", 1)[1])
    return None


def test_remember_me_sets_30day_cookie_and_survives_refresh(make_account):
    """«Запомнить меня» → refresh-cookie на 30 дней, и ротация при /refresh
    сохраняет длинный срок (иначе через 7 дней сессия молча схлопнулась бы)."""
    from app.core.config import get_settings
    s = get_settings()
    acct = make_account()

    r = acct.client.post(
        "/api/auth/login",
        json={"email": acct.email, "password": acct.password, "remember_me": True},
    )
    assert r.status_code == 200, r.text
    login_maxage = _refresh_cookie_maxage(r)
    assert login_maxage == s.refresh_token_remember_expire_minutes * 60, login_maxage

    # Рефреш по cookie должен ВЫДАТЬ такой же длинный срок (флаг пережил ротацию).
    rr = acct.client.post("/api/auth/refresh", json={})
    assert rr.status_code == 200, rr.text
    assert _refresh_cookie_maxage(rr) == s.refresh_token_remember_expire_minutes * 60
    # И новый access-токен рабочий.
    me = acct.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {rr.json()['access_token']}"}
    )
    assert me.status_code == 200


def test_login_without_remember_me_keeps_7day_cookie(make_account):
    """Без «Запомнить меня» (по умолчанию False) — обычные 7 дней, и ротация тоже 7."""
    from app.core.config import get_settings
    s = get_settings()
    acct = make_account()

    r = acct.client.post(
        "/api/auth/login",
        json={"email": acct.email, "password": acct.password},  # remember_me не передан
    )
    assert r.status_code == 200, r.text
    assert _refresh_cookie_maxage(r) == s.refresh_token_expire_minutes * 60

    rr = acct.client.post("/api/auth/refresh", json={})
    assert rr.status_code == 200, rr.text
    assert _refresh_cookie_maxage(rr) == s.refresh_token_expire_minutes * 60


def test_logout_revokes_remember_me_token_for_full_lifetime(make_account):
    """Разлогин 30-дневной сессии («Запомнить меня») должен держать запись об
    отзыве весь срок жизни токена, а не 7 дней — иначе тот же refresh
    переигрывался бы на /refresh ещё ~23 дня после выхода (регресс remember-me)."""
    from app.core.config import get_settings
    from app.core.security import decode_token
    s = get_settings()
    acct = make_account()

    r = acct.client.post(
        "/api/auth/login",
        json={"email": acct.email, "password": acct.password, "remember_me": True},
    )
    assert r.status_code == 200, r.text
    refresh_token = r.json()["refresh_token"]
    jti = decode_token(refresh_token)["jti"]

    lo = acct.client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    assert lo.status_code == 200, lo.text

    # Запись об отзыве держится на ~30 дней (весь срок токена), а не на 7.
    ttl = redis_client.ttl(f"revoked_refresh:{jti}")
    assert ttl > s.refresh_token_expire_minutes * 60, ttl
    assert ttl <= s.refresh_token_remember_expire_minutes * 60, ttl

    # И сам токен теперь отвергается на /refresh — сессия действительно убита.
    rr = acct.client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert rr.status_code == 401, rr.text


def test_logout_revocation_ttl_stays_7day_for_default_session(make_account):
    """Без «Запомнить меня» TTL отзыва остаётся ~7 дней — длинный срок не
    раздуваем на обычные сессии."""
    from app.core.config import get_settings
    from app.core.security import decode_token
    s = get_settings()
    acct = make_account()

    r = acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": acct.password}
    )
    assert r.status_code == 200, r.text
    refresh_token = r.json()["refresh_token"]
    jti = decode_token(refresh_token)["jti"]

    lo = acct.client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    assert lo.status_code == 200, lo.text

    ttl = redis_client.ttl(f"revoked_refresh:{jti}")
    assert ttl > (s.refresh_token_expire_minutes - 60) * 60, ttl
    assert ttl <= s.refresh_token_expire_minutes * 60, ttl


def test_login_wrong_password_401(make_account):
    acct = make_account()
    r = acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": "definitely-wrong-pw"}
    )
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "Неверный логин или пароль"


def test_login_unknown_email_401(client):
    r = client.post(
        "/api/auth/login",
        json={"email": _unique_email(), "password": "password123"},
    )
    assert r.status_code == 401, r.text
    # Same generic message as wrong-password → no user-existence leak.
    assert r.json()["detail"] == "Неверный логин или пароль"


def test_login_bruteforce_lockout(make_account, monkeypatch):
    """Аудит: после N неудачных попыток аккаунт блокируется на кулдаун (429),
    даже с верным паролем; успех после сброса снова открывает вход.

    Гвард отключён в dev — включаем прод-режим ПОСЛЕ регистрации (иначе
    сработал бы суточный IP-потолок регистраций)."""
    from app.services import login_guard as lg

    acct = make_account()
    monkeypatch.setattr(lg.settings, "app_env", "production")
    monkeypatch.setattr(lg.settings, "login_max_failed_attempts", 5)
    # На всякий случай — свежий счётчик именно этого email.
    try:
        lg._redis.delete(lg._fail_key(acct.email))
    except Exception:
        pass

    # 5 неудачных попыток — все 401.
    for _ in range(5):
        r = acct.client.post("/api/auth/login",
                             json={"email": acct.email, "password": "wrong-pw"})
        assert r.status_code == 401, r.text
    # 6-я (даже с ВЕРНЫМ паролем) — 429 + Retry-After.
    blocked = acct.client.post("/api/auth/login",
                               json={"email": acct.email, "password": acct.password})
    assert blocked.status_code == 429, blocked.text
    assert "retry-after" in {k.lower() for k in blocked.headers}

    # Сброс счётчика (эмуляция истёкшего кулдауна) → верный пароль снова входит.
    lg._redis.delete(lg._fail_key(acct.email))
    ok = acct.client.post("/api/auth/login",
                          json={"email": acct.email, "password": acct.password})
    assert ok.status_code == 200, ok.text


# ── refresh ─────────────────────────────────────────────────────────────────

def test_refresh_issues_new_access_token(make_account):
    acct = make_account()
    r = acct.client.post(
        "/api/auth/refresh", json={"refresh_token": acct.refresh_token}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    new_access = body["access_token"]
    assert new_access
    # The new access token actually authenticates.
    me = acct.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == acct.email
    # A rotated refresh token comes back too.
    assert body["refresh_token"]


def test_refresh_with_garbage_token_401(client):
    r = client.post("/api/auth/refresh", json={"refresh_token": "not.a.jwt"})
    assert r.status_code == 401, r.text


def test_refresh_rejects_access_token_as_refresh(make_account):
    """Passing an ACCESS token to /refresh must be rejected (wrong type)."""
    acct = make_account()
    r = acct.client.post("/api/auth/refresh", json={"refresh_token": acct.token})
    assert r.status_code == 401, r.text


# ── /auth/me ────────────────────────────────────────────────────────────────

def test_me_shape(make_account):
    acct = make_account()
    r = acct.get("/api/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"id", "email", "full_name", "is_admin", "email_verified", "marketing_consent"}
    assert body["email"] == acct.email
    assert body["full_name"] == acct.full_name
    assert body["is_admin"] is False
    assert body["email_verified"] is True


def test_me_requires_auth(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401, r.text


def test_me_rejects_bad_bearer(make_account):
    acct = make_account()
    r = acct.get("/api/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401, r.text


# ── change-password ──────────────────────────────────────────────────────────

def test_change_password_new_works_old_fails(make_account):
    acct = make_account()
    new_pw = "brandNewPass456"

    r = acct.post(
        "/api/auth/change-password",
        json={"current_password": acct.password, "new_password": new_pw},
    )
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Пароль обновлен"

    # OLD password no longer logs in.
    old = acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": acct.password}
    )
    assert old.status_code == 401, old.text

    # NEW password works.
    new = acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": new_pw}
    )
    assert new.status_code == 200, new.text
    assert new.json()["access_token"]


def test_change_password_wrong_current_400(make_account):
    acct = make_account()
    r = acct.post(
        "/api/auth/change-password",
        json={"current_password": "wrong-current", "new_password": "anotherPass789"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Текущий пароль указан неверно"
    # Original password still works → no change happened.
    still = acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": acct.password}
    )
    assert still.status_code == 200


def test_change_password_revokes_old_refresh_token(make_account):
    """After a password change, the pre-change refresh token is bulk-revoked."""
    acct = make_account()
    old_refresh = acct.refresh_token
    r = acct.post(
        "/api/auth/change-password",
        json={"current_password": acct.password, "new_password": "rotatePass321"},
    )
    assert r.status_code == 200, r.text
    # The refresh token minted at register predates the revocation timestamp.
    used = acct.client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert used.status_code == 401, used.text
    assert used.json()["detail"] == "Refresh token отозван"


# ── forgot-password (no email leak) ──────────────────────────────────────────

def test_forgot_password_existing_email_generic_message(make_account):
    acct = make_account()
    r = acct.client.post("/api/auth/forgot-password", json={"email": acct.email})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Если email существует, инструкция отправлена"


def test_forgot_password_unknown_email_same_generic_message(client):
    """An unknown email returns the SAME 200 + message — does not leak existence."""
    r = client.post("/api/auth/forgot-password", json={"email": _unique_email()})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Если email существует, инструкция отправлена"


# ── resend-verification (no email leak, cooldown, real token) ────────────────

_GENERIC_RESEND = "Если аккаунт существует и не подтверждён — письмо отправлено"


def test_resend_verification_unknown_email_generic(client):
    """Unknown email → SAME generic 200 (no account enumeration)."""
    r = client.post("/api/auth/resend-verification", json={"email": _unique_email()})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == _GENERIC_RESEND


def test_resend_verification_verified_user_noop_generic(make_account):
    """Already-verified user → generic 200, no token issued."""
    acct = make_account()
    r = acct.client.post("/api/auth/resend-verification", json={"email": acct.email})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == _GENERIC_RESEND


def test_resend_verification_issues_fresh_token_with_cooldown(make_account, db, monkeypatch):
    """Unverified user (verification flag ON) → a NEW verify_email token lands
    in Redis pointing at the user; an immediate second call hits the 60s
    cooldown and issues nothing new (still generic 200)."""
    from app.api.routes import auth as auth_route

    acct = make_account()
    user = db.execute(select(User).where(User.email == acct.email)).scalar_one()
    user.email_verified = False
    db.commit()
    user_id = str(user.id)

    monkeypatch.setattr(auth_route.settings, "email_verification_required", True, raising=False)
    # Clean slate: no cooldown, no stale verify tokens for this user.
    redis_client.delete(f"verify_resend:{user_id}")
    for key in redis_client.scan_iter("verify_email:*"):
        if redis_client.get(key) == user_id:
            redis_client.delete(key)

    r = acct.client.post("/api/auth/resend-verification", json={"email": acct.email})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == _GENERIC_RESEND

    tokens = [k for k in redis_client.scan_iter("verify_email:*") if redis_client.get(k) == user_id]
    assert len(tokens) == 1, "resend must store exactly one fresh verify token"

    # Cooldown: the second immediate call must NOT mint another token.
    r2 = acct.client.post("/api/auth/resend-verification", json={"email": acct.email})
    assert r2.status_code == 200
    tokens2 = [k for k in redis_client.scan_iter("verify_email:*") if redis_client.get(k) == user_id]
    assert len(tokens2) == 1, "cooldown must suppress a second token within 60s"

    # The fresh token actually verifies the account (full loop).
    token_value = tokens2[0].split("verify_email:", 1)[1]
    rv = acct.client.post("/api/auth/verify-email", json={"token": token_value})
    assert rv.status_code == 200, rv.text
    db.expire_all()
    assert db.execute(select(User).where(User.email == acct.email)).scalar_one().email_verified is True
    redis_client.delete(f"verify_resend:{user_id}")


def test_forgot_then_reset_password_full_flow(make_account):
    """Full reset flow: forgot-password writes a token to Redis; reset-password
    with that token sets a new password that then logs in (old fails)."""
    acct = make_account()
    new_pw = "resetThroughRedis99"

    # Drain any stale reset keys for this user so we read the right one.
    user_id = _user_id(acct)
    _drain_reset_keys_for(user_id)

    r = acct.client.post("/api/auth/forgot-password", json={"email": acct.email})
    assert r.status_code == 200, r.text

    token = _find_reset_token_for(user_id)
    assert token is not None, "forgot-password must store a password_reset token in Redis"

    reset = acct.client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": new_pw}
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["message"] == "Пароль успешно изменен"

    # New password logs in; old does not.
    assert acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": new_pw}
    ).status_code == 200
    assert acct.client.post(
        "/api/auth/login", json={"email": acct.email, "password": acct.password}
    ).status_code == 401

    # The token is single-use: reusing it now fails.
    again = acct.client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "yetAnother1"}
    )
    assert again.status_code == 400, again.text


def test_reset_password_invalid_token_400(client):
    r = client.post(
        "/api/auth/reset-password",
        json={"token": "this-token-does-not-exist", "new_password": "whateverPass1"},
    )
    assert r.status_code == 400, r.text
    assert "недействителен" in r.json()["detail"]


# ── /auth/me/export (152-ФЗ subject access) ──────────────────────────────────

def test_me_export_returns_user_data(make_account):
    acct = make_account()
    r = acct.get("/api/auth/me/export")
    assert r.status_code == 200, r.text
    body = r.json()
    # Top-level shape.
    assert body["profile"]["email"] == acct.email
    assert body["profile"]["full_name"] == acct.full_name
    assert body["export_metadata"]["subject_email"] == acct.email
    assert body["export_metadata"]["legal_basis"].startswith("ст. 14")
    # Owner membership is reflected.
    roles = {m["organization_id"]: m["role"] for m in body["memberships"]}
    assert acct.org_id in roles
    assert roles[acct.org_id] == "owner"
    # Owner → org block with the org's name is included.
    org_ids = {o["id"] for o in body["organizations"]}
    assert acct.org_id in org_ids


def test_me_export_throttled_to_once_per_minute(make_account):
    """The export endpoint is rate-limited per user (Redis SETNX, 60s)."""
    acct = make_account()
    first = acct.get("/api/auth/me/export")
    assert first.status_code == 200, first.text
    second = acct.get("/api/auth/me/export")
    assert second.status_code == 429, second.text


def test_me_export_requires_auth(client):
    r = client.get("/api/auth/me/export")
    assert r.status_code == 401, r.text


# ── DELETE /auth/me (152-ФЗ erasure) ─────────────────────────────────────────

def test_delete_account_then_login_fails(make_account, db):
    acct = make_account()
    email = acct.email

    # Wrong password → refused (guard against compromised access token).
    bad = acct.request(
        "DELETE", "/api/auth/me", json={"password": "not-the-password"}
    )
    assert bad.status_code == 403, bad.text
    # Still alive.
    assert acct.get("/api/auth/me").status_code == 200

    # Correct password → account erased.
    ok = acct.request(
        "DELETE", "/api/auth/me", json={"password": acct.password, "reason": "тест"}
    )
    assert ok.status_code == 200, ok.text
    assert "удален" in ok.json()["message"]

    # User row is gone.
    assert db.execute(select(User).where(User.email == email)).scalar_one_or_none() is None

    # Login with the deleted account now fails.
    login = acct.client.post(
        "/api/auth/login", json={"email": email, "password": acct.password}
    )
    assert login.status_code == 401, login.text

    # The org (sole-owner) was cascade-deleted too.
    org_row = db.get(Organization, acct.org_id)
    assert org_row is None


def test_delete_account_requires_auth(client):
    r = client.request("DELETE", "/api/auth/me", json={"password": "x"})
    assert r.status_code == 401, r.text


# ── helpers ──────────────────────────────────────────────────────────────────

def _user_id(acct) -> str:
    me = acct.get("/api/auth/me")
    return me.json()["id"]


def _find_reset_token_for(user_id: str) -> str | None:
    for key in redis_client.scan_iter(match="password_reset:*"):
        if redis_client.get(key) == str(user_id):
            return key.split("password_reset:", 1)[1]
    return None


def _drain_reset_keys_for(user_id: str) -> None:
    for key in list(redis_client.scan_iter(match="password_reset:*")):
        if redis_client.get(key) == str(user_id):
            redis_client.delete(key)


def _purge(db, email: str, org_name: str) -> None:
    """Clean rows created by client.post('/register', ...) directly (these don't
    flow through make_account's tracked teardown)."""
    from sqlalchemy import delete

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    org = db.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()
    try:
        if org is not None:
            db.execute(delete(Membership).where(Membership.organization_id == org.id))
        if user is not None:
            db.execute(delete(Membership).where(Membership.user_id == user.id))
        if org is not None:
            db.execute(delete(Organization).where(Organization.id == org.id))
        if user is not None:
            db.execute(delete(User).where(User.id == user.id))
        db.commit()
    except Exception:
        db.rollback()


# ── анти-мультиакк регистрации (14.07.2026) ──────────────────────────────────
# Триал = 10 разовых лидов; эти тесты закрывают пути его фермерства через
# реальный HTTP-стек: алиасы одного ящика, одноразовые почты и петлю
# «удалить аккаунт → зарегистрироваться заново».

def _purge_trial_grant(db, email: str) -> None:
    from sqlalchemy import delete as _delete

    from app.models import TrialGrant
    from app.services import registration_guard as _rg

    h = _rg.trial_identity_hash(_rg.normalize_email_identity(email))
    try:
        db.execute(_delete(TrialGrant).where(TrialGrant.email_identity_hash == h))
        db.commit()
    except Exception:
        db.rollback()


def test_register_gmail_alias_variants_rejected(client, db):
    uid = uuid.uuid4().hex[:10]
    email = f"e2eauth{uid}@gmail.com"
    first = _register_payload(email=email)
    try:
        r1 = client.post("/api/auth/register", json=first)
        assert r1.status_code == 200, r1.text
        # plus-тег, точки Gmail и алиас домена — тот же inbox, все 409
        for alias in (
            f"e2eauth{uid}+farm2@gmail.com",
            f"e2e.auth.{uid}@gmail.com",
            f"e2eauth{uid}@googlemail.com",
        ):
            r = client.post("/api/auth/register", json=_register_payload(email=alias))
            assert r.status_code == 409, f"{alias}: {r.status_code} {r.text}"
            assert "уже зарегистрирован" in r.json()["detail"]
    finally:
        _purge(db, email, first["organization_name"])
        _purge_trial_grant(db, email)


def test_register_disposable_email_rejected(client):
    r = client.post(
        "/api/auth/register",
        json=_register_payload(email=f"bot-{uuid.uuid4().hex[:8]}@yopmail.com"),
    )
    assert r.status_code == 400, r.text
    assert "Временные email" in r.json()["detail"]


def test_trial_not_regranted_after_account_deletion(client, db):
    """Петля «зарегистрировался → сжёг 10 пробных лидов → удалил аккаунт →
    зарегистрировался на тот же ящик» не даёт второй триал: книга trial_grants
    хранит солёный хэш identity и переживает удаление ПД."""
    uid = uuid.uuid4().hex[:10]
    email = f"e2e-auth-{uid}@example.com"
    org_a = f"E2E Trial Loop A {uid}"
    org_b = f"E2E Trial Loop B {uid}"
    try:
        r1 = client.post("/api/auth/register", json=_register_payload(email=email, org=org_a))
        assert r1.status_code == 200, r1.text
        o1 = db.execute(select(Organization).where(Organization.name == org_a)).scalar_one()
        assert o1.leads_used_current_month == 0  # первый раз — полный триал
        # фермер СЖЁГ пробные лиды (неиспользованный триал при удалении
        # возвращается — см. test_trial_refunded_when_deleted_unused)
        o1.leads_used_current_month = o1.leads_limit_per_month
        db.commit()

        rd = client.request(
            "DELETE",
            "/api/auth/me",
            json={"password": "password123"},
            headers={"Authorization": f"Bearer {r1.json()['access_token']}"},
        )
        assert rd.status_code == 200, rd.text

        r2 = client.post("/api/auth/register", json=_register_payload(email=email, org=org_b))
        assert r2.status_code == 200, r2.text  # регистрация проходит...
        db.expire_all()
        o2 = db.execute(select(Organization).where(Organization.name == org_b)).scalar_one()
        # ...но триал уже израсходован: сразу честный пейволл
        assert o2.leads_used_current_month == o2.leads_limit_per_month > 0
        assert o2.ai_cost_used_kopecks_current_month == o2.ai_cost_limit_kopecks_per_month
    finally:
        _purge(db, email, org_a)
        _purge(db, email, org_b)
        _purge_trial_grant(db, email)


def test_register_collision_of_historical_identities_409_not_500(client, db):
    """Два до-нормализационных юзера могли схлопнуться в одну identity
    (бэкфилл миграции это допускает) — регистрация третьего алиаса должна
    давать 409, а не 500 MultipleResultsFound (блокер ревью 14.07)."""
    from app.core.security import hash_password
    from app.services import registration_guard as _rg

    uid = uuid.uuid4().hex[:10]
    identity = _rg.normalize_email_identity(f"e2ecoll{uid}@gmail.com")
    u1 = User(
        email=f"e2ecoll{uid}+a@gmail.com", email_normalized=identity,
        full_name="Hist A", hashed_password=hash_password("password123"),
        email_verified=True,
    )
    u2 = User(
        email=f"e2ecoll{uid}+b@gmail.com", email_normalized=identity,
        full_name="Hist B", hashed_password=hash_password("password123"),
        email_verified=True,
    )
    db.add_all([u1, u2])
    db.commit()
    try:
        r = client.post(
            "/api/auth/register",
            json=_register_payload(email=f"e2e.coll.{uid}@gmail.com"),
        )
        assert r.status_code == 409, r.text
        assert "уже зарегистрирован" in r.json()["detail"]
    finally:
        from sqlalchemy import delete as _delete
        db.execute(_delete(User).where(User.email_normalized == identity))
        db.commit()


def test_trial_domain_cap_stops_catchall_farm(client, db, monkeypatch):
    """Catch-all на своём домене ($2/год) даёт безлимит «разных» ящиков —
    доменный потолок выдаёт триал первым N, дальше орги стартуют с
    потраченным триалом (регистрация НЕ блокируется)."""
    from app.core.config import get_settings as _gs
    monkeypatch.setattr(_gs(), "trials_per_email_domain", 2)

    uid = uuid.uuid4().hex[:8]
    domain = f"e2e-catchall-{uid}.ru"
    emails, orgs = [], []
    try:
        for i in range(3):
            email = f"farm{i}@{domain}"
            org = f"E2E Catchall {uid} {i}"
            emails.append(email)
            orgs.append(org)
            r = client.post("/api/auth/register", json=_register_payload(email=email, org=org))
            assert r.status_code == 200, r.text
        db.expire_all()
        used = [
            db.execute(select(Organization).where(Organization.name == o)).scalar_one().leads_used_current_month
            for o in orgs
        ]
        assert used[0] == 0 and used[1] == 0  # первые два — полный триал
        assert used[2] > 0                    # третий — триал уже потрачен
        # freemail-домен потолком не задет: gmail-регистрация даёт полный триал
        g_email = f"e2efree{uid}@gmail.com"
        g_org = f"E2E Freemail OK {uid}"
        emails.append(g_email)
        orgs.append(g_org)
        rg2 = client.post("/api/auth/register", json=_register_payload(email=g_email, org=g_org))
        assert rg2.status_code == 200, rg2.text
        db.expire_all()
        g = db.execute(select(Organization).where(Organization.name == g_org)).scalar_one()
        assert g.leads_used_current_month == 0
    finally:
        for e, o in zip(emails, orgs):
            _purge(db, e, o)
            _purge_trial_grant(db, e)


def test_trial_refunded_when_deleted_unused(client, db):
    """Честная петля: зарегистрировался → НЕ тратил лиды → удалил аккаунт →
    вернулся. Грант возвращён, триал снова полный (в отличие от фермера,
    потратившего лиды, — см. test_trial_not_regranted_after_account_deletion)."""
    uid = uuid.uuid4().hex[:10]
    email = f"e2e-auth-{uid}@example.com"
    org_a, org_b = f"E2E Refund A {uid}", f"E2E Refund B {uid}"
    try:
        r1 = client.post("/api/auth/register", json=_register_payload(email=email, org=org_a))
        assert r1.status_code == 200, r1.text
        rd = client.request(
            "DELETE", "/api/auth/me",
            json={"password": "password123"},
            headers={"Authorization": f"Bearer {r1.json()['access_token']}"},
        )
        assert rd.status_code == 200, rd.text
        r2 = client.post("/api/auth/register", json=_register_payload(email=email, org=org_b))
        assert r2.status_code == 200, r2.text
        db.expire_all()
        o2 = db.execute(select(Organization).where(Organization.name == org_b)).scalar_one()
        assert o2.leads_used_current_month == 0  # триал вернулся целиком
    finally:
        _purge(db, email, org_a)
        _purge(db, email, org_b)
        _purge_trial_grant(db, email)


def test_marketing_consent_optional_default_off(client, db):
    """Согласие на рассылки НЕОБЯЗАТЕЛЬНО и по умолчанию выключено (опт-ин,
    ст. 18 ФЗ «О рекламе»). Регистрация без флага → marketing_consent=False."""
    email = _unique_email()
    payload = _register_payload(email=email)  # без marketing_consent
    try:
        r = client.post("/api/auth/register", json=payload)
        assert r.status_code == 200, r.text
        u = db.execute(select(User).where(User.email == email)).scalar_one()
        assert u.marketing_consent is False
        assert u.marketing_consent_at is None
    finally:
        _purge(db, email, payload["organization_name"])
        _purge_trial_grant(db, email)


def test_marketing_consent_opt_in_and_toggle(client, db):
    """Флаг при регистрации сохраняется с датой; ручка подписки/отписки
    меняет его в обе стороны."""
    email = _unique_email()
    payload = _register_payload(email=email)
    payload["marketing_consent"] = True
    try:
        r = client.post("/api/auth/register", json=payload)
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}

        u = db.execute(select(User).where(User.email == email)).scalar_one()
        assert u.marketing_consent is True
        assert u.marketing_consent_at is not None

        # /me отдаёт статус
        me = client.get("/api/auth/me", headers=hdr)
        assert me.json()["marketing_consent"] is True

        # отписка
        off = client.post("/api/auth/me/marketing-consent", headers=hdr, json={"consent": False})
        assert off.status_code == 200 and off.json()["marketing_consent"] is False
        db.expire_all()
        u = db.execute(select(User).where(User.email == email)).scalar_one()
        assert u.marketing_consent is False and u.marketing_consent_at is None

        # повторная подписка проставляет дату
        on = client.post("/api/auth/me/marketing-consent", headers=hdr, json={"consent": True})
        assert on.json()["marketing_consent"] is True
        db.expire_all()
        assert db.execute(select(User).where(User.email == email)).scalar_one().marketing_consent_at is not None
    finally:
        _purge(db, email, payload["organization_name"])
        _purge_trial_grant(db, email)

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
    assert set(body.keys()) == {"id", "email", "full_name", "is_admin", "email_verified"}
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

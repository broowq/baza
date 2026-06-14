"""TRUE E2E: organization + team management, end to end through real HTTP + auth + DB.

Covers the org/team surface in app/api/routes/organizations.py:
  GET  /organizations/me, /my-list, /membership, /members, /invites, /actions
  PATCH /organizations/me/webhook
  invite flow: POST /invites → GET /invites → a SECOND user POST /invites/accept
               → they appear in /members
  PATCH /organizations/members/{user_id}/role
  DELETE /organizations/members/{user_id}
  free-plan refusal (can_invite_members False)

Everything runs through real Bearer+X-Org-Id auth, real Postgres, the real
role/quota guards. We assert status codes AND response/DB state.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Invite, Membership, User


# ── helpers ─────────────────────────────────────────────────────────────────

def _user_id(db, acct) -> str:
    return str(db.execute(select(User).where(User.email == acct.email)).scalar_one().id)


# ── org read endpoints ──────────────────────────────────────────────────────

def test_me_and_my_list_return_the_creators_org(make_account):
    acct = make_account()  # free plan

    me = acct.get("/api/organizations/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["id"] == acct.org_id
    assert body["plan"] == "free"
    # free plan: invites disabled, single-user quota.
    assert body["can_invite_members"] is False
    assert body["users_limit"] == 1
    assert body["leads_limit_per_month"] == 0

    my_list = acct.get("/api/organizations/my-list")
    assert my_list.status_code == 200, my_list.text
    ids = [o["id"] for o in my_list.json()]
    assert acct.org_id in ids
    # A fresh user belongs to exactly the org they registered.
    assert len(ids) == 1


def test_my_list_is_per_user_isolated(make_account):
    """Each user only sees their own org in /my-list."""
    a = make_account()
    b = make_account()  # independent org+user

    a_ids = [o["id"] for o in a.get("/api/organizations/my-list").json()]
    b_ids = [o["id"] for o in b.get("/api/organizations/my-list").json()]
    assert a.org_id in a_ids and a.org_id not in b_ids
    assert b.org_id in b_ids and b.org_id not in a_ids


def test_membership_role_is_owner_for_creator(make_account, db):
    acct = make_account()
    r = acct.get("/api/organizations/membership")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "owner"
    assert body["organization_id"] == acct.org_id
    assert body["user_id"] == _user_id(db, acct)


def test_me_requires_auth(client):
    """Unauthenticated request (raw client, no Bearer) is rejected."""
    r = client.get("/api/organizations/me")
    assert r.status_code == 401, r.text


# ── webhook update (owner/admin only) ───────────────────────────────────────

def test_update_webhook_sets_and_clears(paid_account, db):
    acct = paid_account
    url = "https://hooks.example.com/bitrix/abc123"
    r = acct.patch("/api/organizations/me/webhook", json={"lead_webhook_url": url})
    assert r.status_code == 200, r.text
    assert r.json()["lead_webhook_url"] == url
    # Persisted.
    assert acct.get("/api/organizations/me").json()["lead_webhook_url"] == url

    # Empty string disables.
    r2 = acct.patch("/api/organizations/me/webhook", json={"lead_webhook_url": ""})
    assert r2.status_code == 200, r2.text
    assert r2.json()["lead_webhook_url"] == ""
    assert acct.get("/api/organizations/me").json()["lead_webhook_url"] == ""


def test_update_webhook_rejects_non_http_scheme(paid_account):
    acct = paid_account
    r = acct.patch("/api/organizations/me/webhook",
                   json={"lead_webhook_url": "ftp://nope.example.com"})
    assert r.status_code == 422, r.text
    # The bad URL must NOT have been saved.
    assert acct.get("/api/organizations/me").json()["lead_webhook_url"] == ""


# ── members listing (owner/admin only) ──────────────────────────────────────

def test_members_lists_the_owner(paid_account, db):
    acct = paid_account
    r = acct.get("/api/organizations/members")
    assert r.status_code == 200, r.text
    members = r.json()
    assert len(members) == 1
    me = members[0]
    assert me["email"] == acct.email
    assert me["role"] == "owner"
    assert me["user_id"] == _user_id(db, acct)


# ── invite flow refusal on free plan ────────────────────────────────────────

def test_free_plan_cannot_invite(make_account):
    """A free org has can_invite_members=False → create_invite refused 403."""
    acct = make_account()  # free
    assert acct.get("/api/organizations/me").json()["can_invite_members"] is False
    r = acct.post("/api/organizations/invites",
                  json={"email": "newbie@example.com", "role": "member"})
    assert r.status_code == 403, r.text
    assert "тариф" in r.json()["detail"].lower()
    # No invite was created.
    assert acct.get("/api/organizations/invites").json() == []


# ── full invite → accept → member → role change → removal ───────────────────

def test_full_invite_accept_role_and_removal_journey(paid_account, make_account, db):
    owner = paid_account  # pro org → can_invite_members True
    invitee = make_account()  # second independent user

    # 1. Owner creates an invite for the second user's email.
    create = owner.post("/api/organizations/invites",
                        json={"email": invitee.email, "role": "member"})
    assert create.status_code == 200, create.text
    invite = create.json()
    assert invite["email"] == invitee.email.lower()
    assert invite["role"] == "member"
    assert invite["accepted"] is False

    # 2. Invite shows in the org's invite list.
    inv_list = owner.get("/api/organizations/invites")
    assert inv_list.status_code == 200, inv_list.text
    assert any(i["id"] == invite["id"] for i in inv_list.json())

    # 3. Grab the raw token (not exposed over HTTP) from the DB.
    token = db.execute(
        select(Invite.token).where(Invite.id == invite["id"])
    ).scalar_one()

    # 4. The second user accepts the invite → joins the owner's org.
    accept = invitee.post("/api/organizations/invites/accept", json={"token": token})
    assert accept.status_code == 200, accept.text
    assert accept.json()["id"] == owner.org_id

    # Membership row really exists now.
    invitee_uid = _user_id(db, invitee)
    db.expire_all()
    joined = db.execute(
        select(Membership).where(
            Membership.organization_id == owner.org_id,
            Membership.user_id == invitee_uid,
        )
    ).scalar_one_or_none()
    assert joined is not None and joined.role == "member"

    # The accepted user now sees the owner's org in their list.
    invitee_orgs = [o["id"] for o in invitee.get("/api/organizations/my-list").json()]
    assert owner.org_id in invitee_orgs

    # 5. Owner's member list now has TWO members.
    members = owner.get("/api/organizations/members").json()
    emails = {m["email"] for m in members}
    assert {owner.email, invitee.email} <= emails
    assert len(members) == 2

    # 6. Re-accepting the same (now-accepted) token is rejected (404).
    reaccept = invitee.post("/api/organizations/invites/accept", json={"token": token})
    assert reaccept.status_code == 404, reaccept.text

    # 7. Owner promotes the new member to admin.
    promote = owner.patch(
        f"/api/organizations/members/{invitee_uid}/role", json={"role": "admin"}
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["role"] == "admin"
    assert promote.json()["user_id"] == invitee_uid

    # 8. Owner cannot change their OWN role.
    owner_uid = _user_id(db, owner)
    self_role = owner.patch(
        f"/api/organizations/members/{owner_uid}/role", json={"role": "member"}
    )
    assert self_role.status_code == 400, self_role.text

    # 9. Owner removes the member.
    removed = owner.delete(f"/api/organizations/members/{invitee_uid}")
    assert removed.status_code == 200, removed.text
    db.expire_all()
    gone = db.execute(
        select(Membership).where(
            Membership.organization_id == owner.org_id,
            Membership.user_id == invitee_uid,
        )
    ).scalar_one_or_none()
    assert gone is None
    assert len(owner.get("/api/organizations/members").json()) == 1

    # 10. Owner cannot remove themselves.
    self_remove = owner.delete(f"/api/organizations/members/{owner_uid}")
    assert self_remove.status_code == 400, self_remove.text


def test_accept_invite_rejects_email_mismatch(paid_account, make_account, db):
    """An invite is bound to its email — a different user cannot redeem it."""
    owner = paid_account
    intended = make_account()   # invite is for this person
    intruder = make_account()   # but THIS person tries to accept

    create = owner.post("/api/organizations/invites",
                        json={"email": intended.email, "role": "member"})
    assert create.status_code == 200, create.text
    token = db.execute(
        select(Invite.token).where(Invite.id == create.json()["id"])
    ).scalar_one()

    r = intruder.post("/api/organizations/invites/accept", json={"token": token})
    assert r.status_code == 403, r.text
    # No membership leaked to the intruder.
    intruder_uid = _user_id(db, intruder)
    db.expire_all()
    leaked = db.execute(
        select(Membership).where(
            Membership.organization_id == owner.org_id,
            Membership.user_id == intruder_uid,
        )
    ).scalar_one_or_none()
    assert leaked is None


def test_accept_invite_bad_token_is_404(paid_account):
    r = paid_account.post("/api/organizations/invites/accept",
                          json={"token": "this-token-does-not-exist"})
    assert r.status_code == 404, r.text


def test_create_invite_rejects_bad_role(paid_account):
    r = paid_account.post("/api/organizations/invites",
                          json={"email": "x@example.com", "role": "superadmin"})
    assert r.status_code == 400, r.text


# ── role-guard: a plain member cannot perform owner/admin-only actions ───────

def test_member_cannot_use_admin_endpoints(paid_account, make_account, db):
    """After joining as a 'member', the invitee is denied owner/admin actions."""
    owner = paid_account
    member = make_account()

    create = owner.post("/api/organizations/invites",
                        json={"email": member.email, "role": "member"})
    assert create.status_code == 200, create.text
    token = db.execute(
        select(Invite.token).where(Invite.id == create.json()["id"])
    ).scalar_one()
    # Accept against the OWNER's org (X-Org-Id must point at it).
    accept = member.post(
        "/api/organizations/invites/accept",
        json={"token": token},
    )
    assert accept.status_code == 200, accept.text

    member_headers = {"Authorization": f"Bearer {member.token}", "X-Org-Id": owner.org_id}

    # members list — admin/owner only → 403 for a member.
    r1 = member.get("/api/organizations/members", headers=member_headers)
    assert r1.status_code == 403, r1.text

    # invites list — admin/owner only → 403.
    r2 = member.get("/api/organizations/invites", headers=member_headers)
    assert r2.status_code == 403, r2.text

    # webhook update — admin/owner only → 403.
    r3 = member.patch("/api/organizations/me/webhook",
                      json={"lead_webhook_url": "https://x.example.com"},
                      headers=member_headers)
    assert r3.status_code == 403, r3.text

    # role change — owner only → 403.
    owner_uid = _user_id(db, owner)
    r4 = member.patch(f"/api/organizations/members/{owner_uid}/role",
                      json={"role": "member"}, headers=member_headers)
    assert r4.status_code == 403, r4.text

    # audit log — admin/owner only → 403.
    r5 = member.get("/api/organizations/actions", headers=member_headers)
    assert r5.status_code == 403, r5.text

    # But the member CAN still read their own membership (any role allowed).
    r6 = member.get("/api/organizations/membership", headers=member_headers)
    assert r6.status_code == 200, r6.text
    assert r6.json()["role"] == "member"


# ── member role/removal error cases ─────────────────────────────────────────

def test_role_update_unknown_member_is_404(paid_account):
    # Valid UUID that isn't a member of this org.
    r = paid_account.patch(
        "/api/organizations/members/00000000-0000-0000-0000-000000000000/role",
        json={"role": "admin"},
    )
    assert r.status_code == 404, r.text


def test_role_update_bad_uuid_is_400(paid_account):
    r = paid_account.patch(
        "/api/organizations/members/not-a-uuid/role", json={"role": "admin"}
    )
    assert r.status_code == 400, r.text


def test_role_update_rejects_invalid_role(paid_account, make_account, db):
    """An invalid target role is refused before any DB mutation."""
    owner = paid_account
    member = make_account()
    create = owner.post("/api/organizations/invites",
                        json={"email": member.email, "role": "member"})
    token = db.execute(
        select(Invite.token).where(Invite.id == create.json()["id"])
    ).scalar_one()
    member.post("/api/organizations/invites/accept", json={"token": token})
    member_uid = _user_id(db, member)

    r = owner.patch(f"/api/organizations/members/{member_uid}/role",
                    json={"role": "god"})
    assert r.status_code == 400, r.text
    # Role unchanged in DB.
    db.expire_all()
    m = db.execute(
        select(Membership).where(
            Membership.organization_id == owner.org_id,
            Membership.user_id == member_uid,
        )
    ).scalar_one()
    assert m.role == "member"


def test_remove_unknown_member_is_404(paid_account):
    r = paid_account.delete(
        "/api/organizations/members/00000000-0000-0000-0000-000000000000"
    )
    assert r.status_code == 404, r.text


# ── audit log ───────────────────────────────────────────────────────────────

def test_actions_audit_log_records_invite_lifecycle(paid_account, make_account, db):
    """The audit log captures invite.created / invite.accepted / member.* events."""
    owner = paid_account
    member = make_account()

    create = owner.post("/api/organizations/invites",
                        json={"email": member.email, "role": "member"})
    assert create.status_code == 200, create.text
    token = db.execute(
        select(Invite.token).where(Invite.id == create.json()["id"])
    ).scalar_one()
    member.post("/api/organizations/invites/accept", json={"token": token})
    member_uid = _user_id(db, member)
    owner.patch(f"/api/organizations/members/{member_uid}/role", json={"role": "admin"})
    owner.delete(f"/api/organizations/members/{member_uid}")

    actions = owner.get("/api/organizations/actions")
    assert actions.status_code == 200, actions.text
    rows = actions.json()
    kinds = {a["action"] for a in rows}
    assert "invite.created" in kinds
    assert "invite.accepted" in kinds
    assert "member.role.updated" in kinds
    assert "member.removed" in kinds

    # Newest-first ordering + org scoping + meta payload present.
    assert all(a["organization_id"] == owner.org_id for a in rows)
    created = next(a for a in rows if a["action"] == "invite.created")
    assert created["meta"].get("email") == member.email.lower()


def test_actions_respects_limit_param(paid_account, make_account, db):
    """The ?limit clamp truncates the returned audit rows."""
    owner = paid_account
    # Create two distinct audit events (two invites → two invite.created rows).
    for i in range(2):
        peer = make_account()
        create = owner.post("/api/organizations/invites",
                            json={"email": peer.email, "role": "member"})
        assert create.status_code == 200, create.text

    # No limit: both invite.created events present.
    full = owner.get("/api/organizations/actions").json()
    assert sum(1 for a in full if a["action"] == "invite.created") >= 2

    # limit=1: exactly one row returned (newest-first).
    r = owner.get("/api/organizations/actions?limit=1")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

import secrets
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, get_current_user, get_org_membership, require_org_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models import ActionLog, Invite, Membership, Organization, User
from app.schemas.orgs import (
    ActionLogOut,
    InviteAcceptRequest,
    InviteCreateRequest,
    CurrentMembershipOut,
    InviteOut,
    MemberRoleUpdateRequest,
    MemberOut,
    OrganizationOut,
    PlanUpdateRequest,
    WebhookUpdateRequest,
)
from app.services.audit import log_action
from app.services.quota import apply_plan_limits

router = APIRouter(prefix="/organizations", tags=["organizations"])
settings = get_settings()
_redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _revoke_all_user_refresh_tokens(user_id: str) -> None:
    """Revoke all refresh tokens for a user by storing a revocation timestamp.

    TTL — по МАКСИМАЛЬНОМУ сроку жизни refresh-токена (remember-me, 30 дней),
    а не обычному (7). Аудит: раньше маркер отзыва жил 7 дней, а «Запомнить
    меня»-токен — 30, поэтому через 7 дней маркер исчезал и отозванная/угнанная
    30-дневная сессия ВОСКРЕСАЛА ещё на ~23 дня.
    """
    _redis_client.setex(
        f"user_tokens_revoked_at:{user_id}",
        settings.refresh_token_remember_expire_minutes * 60,
        str(int(time.time())),
    )


@router.get("/me", response_model=OrganizationOut)
def my_org(organization: Organization = Depends(get_current_org)):
    return organization


@router.get("/my-list", response_model=list[OrganizationOut])
def list_user_organizations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Single JOIN-backed query instead of N+1 lookups (previously: 1 query to
    # fetch memberships + 1 per org via db.get).
    organizations = (
        db.execute(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id)
        )
        .scalars()
        .all()
    )
    return organizations


@router.get("/membership", response_model=CurrentMembershipOut)
def my_membership(membership: Membership = Depends(get_org_membership)):
    return CurrentMembershipOut(
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        role=membership.role,
    )


@router.patch("/me/plan", response_model=OrganizationOut)
def update_plan(
    payload: PlanUpdateRequest,
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner")),
    db: Session = Depends(get_db),
):
    if settings.app_env != "development":
        raise HTTPException(status_code=403, detail="Прямое изменение тарифа отключено. Используйте checkout.")
    organization.plan = payload.plan
    apply_plan_limits(organization)
    if _membership:
        log_action(
            db,
            user_id=str(_membership.user_id),
            organization_id=str(organization.id),
            action="organization.plan.updated",
            meta={"plan": payload.plan.value},
        )
    db.commit()
    db.refresh(organization)
    return organization


@router.patch("/me/webhook", response_model=OrganizationOut)
def update_webhook(
    payload: WebhookUpdateRequest,
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    """Set or clear the CRM webhook URL for this org.

    Each new lead is POSTed to the URL as JSON. Bitrix24 incoming webhook URL
    or AmoCRM webhook endpoint both work. Empty string disables.
    """
    url = (payload.lead_webhook_url or "").strip()
    if url:
        if not (url.startswith("http://") or url.startswith("https://")):
            raise HTTPException(status_code=422, detail="URL должен начинаться с http:// или https://")
        # SSRF-гард на этапе установки (аудит): вебхук-URL задаёт админ орги, а
        # воркер потом POST'ит на него ПД лидов. Без проверки можно навести
        # его на внутреннюю сеть / облачную метадату (169.254.169.254) или
        # localhost-сервисы. Отсекаем приватные/loopback/link-local цели.
        # На отправке (webhook_tasks) стоит второй гард (защита от DNS-rebind).
        from app.utils.url_tools import _is_safe_url

        if not _is_safe_url(url):
            raise HTTPException(
                status_code=422,
                detail="URL вебхука недопустим: нельзя указывать внутренние/приватные адреса.",
            )
    organization.lead_webhook_url = url
    db.commit()
    db.refresh(organization)
    return organization


@router.get("/invites", response_model=list[InviteOut])
def list_invites(
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    return (
        db.execute(select(Invite).where(Invite.organization_id == organization.id).order_by(Invite.created_at.desc()))
        .scalars()
        .all()
    )


@router.post("/invites", response_model=InviteOut)
def create_invite(
    payload: InviteCreateRequest,
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    if not organization.can_invite_members:
        raise HTTPException(status_code=403, detail="Текущий тариф не поддерживает приглашения")
    if payload.role not in {"owner", "admin", "member"}:
        raise HTTPException(status_code=400, detail="Недопустимая роль")
    # Эскалация привилегий (аудит, HIGH): роут открыт для owner И admin, но
    # ВЫДАВАТЬ роль owner (полный контроль над тенантом) может ТОЛЬКО owner.
    # Иначе admin приглашал бы owner-инвайт → принятие → захват организации.
    if payload.role == "owner" and _membership.role != "owner":
        raise HTTPException(status_code=403, detail="Только владелец может приглашать с ролью «владелец»")
    members_count = (
        db.scalar(select(func.count(Membership.id)).where(Membership.organization_id == organization.id)) or 0
    )
    if members_count >= organization.users_limit:
        raise HTTPException(status_code=402, detail="Лимит пользователей на текущем тарифе исчерпан")
    invite = Invite(
        organization_id=organization.id,
        email=payload.email.lower().strip(),
        role=payload.role,
        token=secrets.token_urlsafe(24),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invite)
    if _membership:
        log_action(
            db,
            user_id=str(_membership.user_id),
            organization_id=str(organization.id),
            action="invite.created",
            meta={"email": invite.email, "role": invite.role},
        )
    db.commit()
    db.refresh(invite)
    # «Пригласить по email» должно реально приглашать: шлём письмо со ссылкой
    # (тот же формат, что и «скопировать ссылку» в настройках). Best-effort
    # ПОСЛЕ коммита — сбой почты не откатывает созданный инвайт, ссылку всё
    # равно можно скопировать из UI.
    if invite.email:
        try:
            from urllib.parse import urlencode

            from app.tasks.email_tasks import send_email_task

            settings = get_settings()
            base_url = (settings.frontend_app_url or "https://usebaza.ru").rstrip("/")
            qs = urlencode({"invite_token": invite.token, "email": invite.email})
            role_ru = {"owner": "владелец", "admin": "администратор", "member": "участник"}.get(invite.role, invite.role)
            send_email_task.delay(
                f"Вас пригласили в «{organization.name}» в БАЗЕ",
                (
                    f"Вас пригласили присоединиться к организации «{organization.name}» "
                    f"в БАЗЕ (роль: {role_ru}).\n\n"
                    f"Принять приглашение: {base_url}/login?{qs}\n\n"
                    "Ссылка действует 7 дней. Если у вас ещё нет аккаунта — "
                    "зарегистрируйтесь с этим же email."
                ),
                invite.email,
            )
        except Exception:  # noqa: BLE001 — почта не должна ломать создание инвайта
            import logging

            logging.getLogger(__name__).warning(
                "invite email enqueue failed for %s", invite.email, exc_info=True
            )
    return invite


@router.post("/invites/accept", response_model=OrganizationOut)
def accept_invite(
    payload: InviteAcceptRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invite = db.execute(select(Invite).where(Invite.token == payload.token)).scalar_one_or_none()
    if not invite or invite.accepted:
        raise HTTPException(status_code=404, detail="Приглашение не найдено")
    # Columns are `timestamp without time zone`, so psycopg2 returns NAIVE
    # datetimes; the stored wall-clock IS UTC (session TZ is pinned). Normalize
    # before comparing or the naive-vs-aware comparison raises TypeError (500).
    expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Срок действия приглашения истек")
    if invite.email.lower().strip() != user.email.lower().strip():
        raise HTTPException(status_code=403, detail="Email пользователя не совпадает с приглашением")

    exists = db.execute(
        select(Membership).where(
            Membership.organization_id == invite.organization_id,
            Membership.user_id == user.id,
        )
    ).scalar_one_or_none()
    if not exists:
        members_count = (
            db.scalar(select(func.count(Membership.id)).where(Membership.organization_id == invite.organization_id)) or 0
        )
        organization = db.get(Organization, invite.organization_id)
        if organization and members_count >= organization.users_limit:
            raise HTTPException(status_code=402, detail="Лимит пользователей на текущем тарифе исчерпан")
        db.add(Membership(organization_id=invite.organization_id, user_id=user.id, role=invite.role))
    invite.accepted = True
    log_action(
        db,
        user_id=str(user.id),
        organization_id=str(invite.organization_id),
        action="invite.accepted",
        meta={"email": user.email, "role": invite.role},
    )
    db.commit()
    organization = db.get(Organization, invite.organization_id)
    return organization


@router.get("/members", response_model=list[MemberOut])
def list_members(
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    rows_raw = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization.id)
    ).all()
    return [
        MemberOut(user_id=user.id, email=user.email, full_name=user.full_name, role=membership.role)
        for membership, user in rows_raw
    ]


@router.patch("/members/{user_id}/role", response_model=MemberOut)
def update_member_role(
    user_id: str,
    payload: MemberRoleUpdateRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner")),
    db: Session = Depends(get_db),
):
    if payload.role not in {"owner", "admin", "member"}:
        raise HTTPException(status_code=400, detail="Недопустимая роль")
    try:
        target_user_id = UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный user_id") from exc
    target_membership = db.execute(
        select(Membership).where(Membership.organization_id == organization.id, Membership.user_id == target_user_id)
    ).scalar_one_or_none()
    if not target_membership:
        raise HTTPException(status_code=404, detail="Участник не найден")
    if str(target_membership.user_id) == str(membership.user_id):
        raise HTTPException(status_code=400, detail="Нельзя изменить собственную роль")
    # Нельзя разжаловать ПОСЛЕДНЕГО владельца — организация осталась бы без
    # хозяина (никто не смог бы менять тариф/участников). Аудит: last-owner guard.
    if target_membership.role == "owner" and payload.role != "owner":
        owners_count = db.scalar(
            select(func.count(Membership.id)).where(
                Membership.organization_id == organization.id,
                Membership.role == "owner",
            )
        ) or 0
        if owners_count <= 1:
            raise HTTPException(status_code=400, detail="Нельзя разжаловать единственного владельца организации")
    target_membership.role = payload.role
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="member.role.updated",
        meta={"target_user_id": str(target_membership.user_id), "role": payload.role},
    )
    db.commit()
    user = db.get(User, target_membership.user_id)
    return MemberOut(
        user_id=target_membership.user_id,
        email=user.email if user else "",
        full_name=user.full_name if user else "",
        role=target_membership.role,
    )


@router.delete("/members/{user_id}")
def remove_member(
    user_id: str,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    try:
        target_user_id = UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный user_id") from exc
    target = db.execute(
        select(Membership).where(Membership.organization_id == organization.id, Membership.user_id == target_user_id)
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Участник не найден")
    if str(target.user_id) == str(membership.user_id):
        raise HTTPException(status_code=400, detail="Нельзя удалить себя из организации")
    # Эскалация/захват тенанта (аудит, HIGH): роут открыт owner И admin, но
    # удалять ВЛАДЕЛЬЦА может только владелец — иначе admin выгонял бы owner'а
    # и перехватывал контроль. Плюс защита от удаления последнего владельца.
    if target.role == "owner":
        if membership.role != "owner":
            raise HTTPException(status_code=403, detail="Только владелец может удалить другого владельца")
        owners_count = db.scalar(
            select(func.count(Membership.id)).where(
                Membership.organization_id == organization.id,
                Membership.role == "owner",
            )
        ) or 0
        if owners_count <= 1:
            raise HTTPException(status_code=400, detail="Нельзя удалить единственного владельца организации")
    db.delete(target)
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="member.removed",
        meta={"target_user_id": str(target_user_id)},
    )
    db.commit()
    # Revoke all refresh tokens for the removed user to invalidate their sessions
    _revoke_all_user_refresh_tokens(str(target_user_id))
    return {"message": "Участник удален"}


@router.get("/actions", response_model=list[ActionLogOut])
def list_actions(
    limit: int = 100,
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    return (
        db.execute(
            select(ActionLog)
            .where(ActionLog.organization_id == organization.id)
            .order_by(ActionLog.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        .scalars()
        .all()
    )

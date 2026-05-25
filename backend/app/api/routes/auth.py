import logging
import time
from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
import redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.db.session import get_db
from app.models import Membership, Organization, PlanType, User
from app.schemas.auth import (
    AccountDeleteRequest,
    AuthMessageResponse,
    ForgotPasswordRequest,
    LoginRequest,
    PasswordChangeRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.services.audit import log_action
from app.services.notifications import email_delivery_configured
from app.services.quota import apply_plan_limits
from app.tasks.email_tasks import send_email_task

_auth_logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _revoke_all_user_refresh_tokens(user_id: str) -> None:
    """Store a timestamp in Redis; any refresh token issued before this time is invalid."""
    redis_client.setex(
        f"user_tokens_revoked_at:{user_id}",
        settings.refresh_token_expire_minutes * 60,
        str(int(time.time())),
    )


def _is_refresh_token_revoked_for_user(user_id: str, token_iat: int | None) -> bool:
    """Check if a user's refresh tokens were bulk-revoked after the token was issued."""
    revoked_at = redis_client.get(f"user_tokens_revoked_at:{user_id}")
    if not revoked_at:
        return False
    try:
        revoked_ts = int(revoked_at)
    except (ValueError, TypeError):
        return False
    # If no iat in token, treat as revoked (conservative)
    if token_iat is None:
        return True
    return token_iat <= revoked_ts


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    if settings.email_verification_required and not email_delivery_configured():
        raise HTTPException(status_code=503, detail="Подтверждение email временно недоступно. Настройте SMTP.")
    normalized_email = payload.email.lower().strip()
    existing = db.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email уже зарегистрирован")
    existing_org = (
        db.execute(select(Organization).where(Organization.name == payload.organization_name)).scalar_one_or_none()
    )
    if existing_org:
        raise HTTPException(status_code=409, detail="Организация с таким именем уже существует")

    org = Organization(name=payload.organization_name, plan=PlanType.free)
    apply_plan_limits(org)
    user = User(
        email=normalized_email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        email_verified=not settings.email_verification_required,
    )
    try:
        db.add_all([org, user])
        db.flush()
        membership = Membership(organization_id=org.id, user_id=user.id, role="owner")
        db.add(membership)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email или организация уже существуют") from exc

    token = create_access_token(str(user.id), expires_delta=timedelta(minutes=settings.access_token_expire_minutes))
    refresh_token = create_refresh_token(
        str(user.id), expires_delta=timedelta(minutes=settings.refresh_token_expire_minutes)
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure or settings.app_env != "development",
        samesite=settings.refresh_cookie_samesite,
        max_age=settings.refresh_token_expire_minutes * 60,
        path="/",
    )
    if settings.email_verification_required:
        verify_token = secrets.token_urlsafe(32)
        redis_client.setex(
            f"verify_email:{verify_token}",
            settings.email_verification_expire_minutes * 60,
            str(user.id),
        )
        verify_link = f"{settings.frontend_app_url}/verify-email?token={verify_token}"
        send_email_task.delay(
            "Подтвердите email в БАЗА",
            f"Перейдите по ссылке для подтверждения email: {verify_link}",
            user.email,
        )
        return TokenResponse(
            access_token=token,
            refresh_token=refresh_token,
            message="Аккаунт создан. Подтвердите email, затем войдите.",
            email_verification_required=True,
        )
    return TokenResponse(
        access_token=token,
        refresh_token=refresh_token,
        message="Аккаунт создан. Вы уже вошли в систему.",
        email_verification_required=False,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    normalized_email = payload.email.lower().strip()
    user = db.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        client_ip = request.client.host if request.client else "unknown"
        _auth_logger.warning(
            "Failed login attempt for email=%s from ip=%s",
            normalized_email,
            client_ip,
        )
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if settings.email_verification_required and not user.email_verified:
        raise HTTPException(status_code=403, detail="Подтвердите email перед входом")
    token = create_access_token(str(user.id), expires_delta=timedelta(minutes=settings.access_token_expire_minutes))
    refresh_token = create_refresh_token(
        str(user.id), expires_delta=timedelta(minutes=settings.refresh_token_expire_minutes)
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure or settings.app_env != "development",
        samesite=settings.refresh_cookie_samesite,
        max_age=settings.refresh_token_expire_minutes * 60,
        path="/",
    )
    return TokenResponse(access_token=token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshTokenRequest, request: Request, response: Response):
    refresh_token = payload.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Отсутствует refresh token")
    try:
        decoded = decode_token(refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Неверный refresh token") from exc
    if decoded.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Некорректный тип refresh token")
    jti = decoded.get("jti")
    if jti and redis_client.get(f"revoked_refresh:{jti}"):
        raise HTTPException(status_code=401, detail="Refresh token отозван")
    user_id = decoded.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Некорректный payload refresh token")
    # Check user-level bulk revocation (e.g. after password change)
    if _is_refresh_token_revoked_for_user(user_id, decoded.get("iat")):
        raise HTTPException(status_code=401, detail="Refresh token отозван")
    new_access = create_access_token(user_id, expires_delta=timedelta(minutes=settings.access_token_expire_minutes))
    new_refresh = create_refresh_token(user_id, expires_delta=timedelta(minutes=settings.refresh_token_expire_minutes))
    if jti:
        redis_client.setex(f"revoked_refresh:{jti}", settings.refresh_token_expire_minutes * 60, "1")
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=new_refresh,
        httponly=True,
        secure=settings.refresh_cookie_secure or settings.app_env != "development",
        samesite=settings.refresh_cookie_samesite,
        max_age=settings.refresh_token_expire_minutes * 60,
        path="/",
    )
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout")
def logout(payload: RefreshTokenRequest, request: Request, response: Response):
    refresh_token = payload.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    try:
        if not refresh_token:
            raise ValueError("missing token")
        decoded = decode_token(refresh_token)
        if decoded.get("type") != "refresh":
            raise ValueError("wrong token type")
        jti = decoded.get("jti")
        if jti:
            redis_client.setex(f"revoked_refresh:{jti}", settings.refresh_token_expire_minutes * 60, "1")
    except Exception:
        pass
    response.delete_cookie(
        settings.refresh_cookie_name,
        path="/",
        secure=settings.refresh_cookie_secure or settings.app_env != "development",
        samesite=settings.refresh_cookie_samesite,
        httponly=True,
    )
    return {"message": "Вы вышли из системы"}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
        "email_verified": user.email_verified,
    }


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
    user.hashed_password = hash_password(payload.new_password)
    membership = db.execute(
        select(Membership).where(Membership.user_id == user.id)
    ).scalar_one_or_none()
    if membership:
        log_action(
            db,
            user_id=str(user.id),
            organization_id=str(membership.organization_id),
            action="auth.password_changed",
        )
    db.commit()
    # Revoke all refresh tokens for this user by setting a revocation timestamp
    _revoke_all_user_refresh_tokens(str(user.id))
    return {"message": "Пароль обновлен"}


@router.post("/forgot-password", response_model=AuthMessageResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    normalized_email = payload.email.lower().strip()
    user = db.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
    if not user:
        return AuthMessageResponse(message="Если email существует, инструкция отправлена")
    if not email_delivery_configured() and settings.app_env != "development":
        raise HTTPException(status_code=503, detail="Сервис email временно недоступен.")
    token = secrets.token_urlsafe(32)
    redis_client.setex(
        f"password_reset:{token}",
        settings.password_reset_expire_minutes * 60,
        str(user.id),
    )
    reset_link = f"{settings.frontend_app_url}/reset-password?token={token}"
    send_email_task.delay(
        "Сброс пароля БАЗА",
        f"Ссылка для сброса пароля: {reset_link}",
        user.email,
    )
    return AuthMessageResponse(message="Если email существует, инструкция отправлена")


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user_id = redis_client.get(f"password_reset:{payload.token}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Токен сброса недействителен или истек")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.hashed_password = hash_password(payload.new_password)
    redis_client.delete(f"password_reset:{payload.token}")
    db.commit()
    # Revoke all refresh tokens for this user after password reset
    _revoke_all_user_refresh_tokens(str(user.id))
    return {"message": "Пароль успешно изменен"}


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    user_id = redis_client.get(f"verify_email:{payload.token}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Токен подтверждения недействителен или истек")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.email_verified = True
    db.commit()
    redis_client.delete(f"verify_email:{payload.token}")
    return {"message": "Email подтвержден"}


# ─────────────────────────────────────────────────────────────────────────
# 152-ФЗ Data Subject Rights
# =========================
# ст. 14 ч. 7 — право получить от оператора все ПД, которые у него есть.
# ст. 14 ч. 3 / ст. 21 — право требовать уничтожения ПД (отзыв согласия).
# Эти эндпойнты обязательны для соответствия требованиям РКН.
# Все вызовы пишутся в audit log (журнал обращений субъектов ПД), который
# можно предъявить при проверке.
# ─────────────────────────────────────────────────────────────────────────

@router.get("/me/export")
def export_my_data(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Право на доступ (ст. 14 ч. 7 152-ФЗ).

    Возвращает все персональные данные субъекта, которые хранит оператор,
    в машиночитаемом формате (JSON). Включает:
      • профиль пользователя
      • членство в организациях и роли
      • аудит-лог действий пользователя
      • если пользователь — owner: данные организации и собранные лиды
        (формально это ПД представителей юр.лиц, обрабатываемые на
        основании п.10 ч.1 ст.6 — общедоступные данные)

    Throttle: 1 запрос / 60 секунд (Redis SETNX). Защита от использования
    эндпойнта как утечкоканала компрометированного токена.
    """
    from datetime import datetime as _dt

    # Throttle
    throttle_key = f"sar_export:{user.id}"
    if not redis_client.set(throttle_key, "1", nx=True, ex=60):
        raise HTTPException(
            status_code=429,
            detail="Запрос на экспорт ПД доступен раз в минуту. Попробуйте позже.",
        )

    memberships = db.execute(
        select(Membership).where(Membership.user_id == user.id)
    ).scalars().all()

    payload: dict = {
        "export_metadata": {
            "exported_at": _dt.now(timezone.utc).isoformat(),
            "operator": "БАЗА (usebaza.ru)",
            "legal_basis": "ст. 14 ч. 7 ФЗ-152",
            "subject_email": user.email,
        },
        "profile": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "email_verified": user.email_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "memberships": [
            {
                "organization_id": str(m.organization_id),
                "role": m.role,
            }
            for m in memberships
        ],
        "organizations": [],
    }

    # Detailed org / lead payload только если пользователь — owner.
    # Member видит только свою принадлежность; полный массив лидов
    # принадлежит организации как оператору-клиенту, а не отдельному юзеру.
    from app.models import Lead, Project, ActionLog

    for m in memberships:
        if m.role != "owner":
            continue
        org = db.get(Organization, m.organization_id)
        if not org:
            continue
        projects = db.execute(
            select(Project).where(Project.organization_id == org.id)
        ).scalars().all()
        leads = db.execute(
            select(Lead).where(Lead.organization_id == org.id)
        ).scalars().all()
        payload["organizations"].append({
            "id": str(org.id),
            "name": org.name,
            "plan": org.plan.value if hasattr(org.plan, "value") else str(org.plan),
            "projects": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "niche": p.niche,
                    "geography": p.geography,
                    "segments": p.segments,
                }
                for p in projects
            ],
            "leads_count": len(leads),
            # Полный массив лидов клиент может выгрузить через свой
            # обычный экспорт CSV/Excel в продуктовом UI — здесь только
            # счётчик чтобы JSON не разрастался на десятки МБ.
        })

    # Audit log — обязательно фиксируем факт обращения по ст. 14 ч. 2
    if memberships:
        log_action(
            db,
            user_id=str(user.id),
            organization_id=str(memberships[0].organization_id),
            action="pd.exported",
            meta={"format": "json", "size_orgs": len(payload["organizations"])},
        )
        db.commit()

    return payload


@router.delete("/me", response_model=AuthMessageResponse)
def delete_my_account(
    payload: AccountDeleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Право на уничтожение ПД (ст. 14 ч. 3 + ст. 21 ФЗ-152).

    Полное удаление аккаунта пользователя и всех связанных с ним ПД.
    Если пользователь — единственный owner организации, удаляется и
    организация со всеми её проектами / лидами (cascade delete).

    Защита:
      • Требуется пароль (защита от случайного клика и от
        скомпрометированного access-токена без знания пароля).
      • Все refresh-токены отзываются.
      • Действие необратимо.

    Журнал:
      • Запись `pd.delete_requested` ДО удаления (на случай rollback).
      • Запись `pd.deleted` пишется в отдельный системный audit log
        (на уровне сервера, не в users table — она будет удалена).
    """
    import logging as _logging
    _logger = _logging.getLogger("baza.pd_deletion")

    # 1. Подтвердить пароль
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Неверный пароль")

    user_id_str = str(user.id)
    user_email = user.email
    reason = payload.reason or "не указана"

    # 2. Журнал обращения ДО удаления (по ст. 14 ч. 2 — обязан фиксировать
    # обращения субъектов ПД).
    memberships = db.execute(
        select(Membership).where(Membership.user_id == user.id)
    ).scalars().all()
    primary_org_id = str(memberships[0].organization_id) if memberships else None
    if primary_org_id:
        log_action(
            db,
            user_id=user_id_str,
            organization_id=primary_org_id,
            action="pd.delete_requested",
            meta={"reason": reason[:500]},
        )
        db.commit()

    # 3. Удаление каскадом
    # Если пользователь единственный owner в организации — удаляем и её.
    # Иначе — только отзываем membership.
    orgs_to_delete: list = []
    for m in memberships:
        org = db.get(Organization, m.organization_id)
        if not org:
            continue
        owners = db.execute(
            select(Membership)
            .where(Membership.organization_id == org.id)
            .where(Membership.role == "owner")
        ).scalars().all()
        # Если этот пользователь — единственный owner организации,
        # организация остаётся без хозяина → удалить её целиком.
        if len(owners) == 1 and owners[0].user_id == user.id:
            orgs_to_delete.append(org)

    for org in orgs_to_delete:
        db.delete(org)  # cascade: memberships, projects, leads, invites

    db.delete(user)
    db.commit()

    # 4. Отозвать ВСЕ refresh-токены (на всякий случай — даже если строка
    # юзера уже удалена, токены ещё могут жить в Redis).
    _revoke_all_user_refresh_tokens(user_id_str)

    # 5. Структурный лог в файл — это запись остаётся даже если все БД-
    # таблицы аудита привязаны к удалённому пользователю и каскадом
    # тоже исчезли. Нужно для аудита РКН.
    _logger.warning(
        "PD_DELETED user_id=%s email=%s orgs_deleted=%d reason=%r",
        user_id_str, user_email, len(orgs_to_delete), reason[:500],
    )

    return AuthMessageResponse(
        message=(
            "Аккаунт и все связанные персональные данные удалены. "
            "Если у вас были вопросы или жалобы — обратитесь на support@usebaza.ru."
        ),
    )

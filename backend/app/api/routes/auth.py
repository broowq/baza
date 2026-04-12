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

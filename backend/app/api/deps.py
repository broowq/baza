import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Membership, Organization, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
settings = get_settings()
_logger = logging.getLogger("app.deps")
# Тот же клиент/ключ, что и в auth.py: смена/сброс пароля и удаление участника
# пишут user_tokens_revoked_at:<uid> = ts. Access-токен с iat <= ts считается
# отозванным. Fail-open при недоступности Redis (как rate-limiter) — доступность
# важнее, а refresh-слой всё равно отзовётся при следующей ротации.
_revocation_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _access_token_revoked(user_id: str, token_iat) -> bool:
    try:
        revoked_at = _revocation_redis.get(f"user_tokens_revoked_at:{user_id}")
    except Exception:
        _logger.warning("token-revocation Redis check failed — fail-open")
        return False
    if not revoked_at:
        return False
    try:
        revoked_ts = int(revoked_at)
    except (ValueError, TypeError):
        return False
    if token_iat is None:
        return True  # консервативно: старые токены без iat считаем отозванными
    try:
        return int(token_iat) <= revoked_ts
    except (ValueError, TypeError):
        return True


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось проверить учетные данные",
    )
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise JWTError("Wrong token type")
        user_id = payload.get("sub")
    except JWTError as exc:
        raise credentials_exception from exc
    if not user_id:
        raise credentials_exception
    # Массовый отзыв access-токенов (смена/сброс пароля, удаление участника):
    # токен, выпущенный ДО отметки отзыва, больше не действует.
    if _access_token_revoked(str(user_id), payload.get("iat")):
        raise credentials_exception
    user = db.get(User, user_id)
    if not user:
        raise credentials_exception
    if settings.email_verification_required and not user.email_verified:
        raise HTTPException(status_code=403, detail="Подтвердите email для доступа к системе")
    return user


def get_current_org(
    x_org_id: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    base_filter = select(Membership).where(Membership.user_id == user.id)
    if not x_org_id:
        # No X-Org-Id: pick the user's first membership deterministically.
        # scalar_one_or_none() raised MultipleResultsFound (500) for multi-org users.
        membership = db.execute(base_filter.order_by(Membership.id)).scalars().first()
        if not membership:
            raise HTTPException(status_code=403, detail="У вас нет доступа к организации")
        org = db.get(Organization, membership.organization_id)
        if not org:
            raise HTTPException(status_code=404, detail="Организация не найдена")
        return org

    try:
        org_id = UUID(x_org_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный заголовок X-Org-Id") from exc

    membership = db.execute(base_filter.where(Membership.organization_id == org_id)).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Вы не участник этой организации")
    organization = db.get(Organization, org_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    return organization


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    return user


def get_org_membership(
    x_org_id: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Membership:
    base_filter = select(Membership).where(Membership.user_id == user.id)
    if not x_org_id:
        # Same deterministic pick as get_current_org (multi-org users would 500).
        membership = db.execute(base_filter.order_by(Membership.id)).scalars().first()
        if not membership:
            raise HTTPException(status_code=403, detail="У вас нет доступа к организации")
        return membership
    try:
        org_id = UUID(x_org_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный заголовок X-Org-Id") from exc
    membership = db.execute(base_filter.where(Membership.organization_id == org_id)).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Вы не участник этой организации")
    return membership


def require_org_roles(*allowed_roles: str):
    def _dependency(membership: Membership = Depends(get_org_membership)) -> Membership:
        if membership.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав в организации")
        return membership

    return _dependency

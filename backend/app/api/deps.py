from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Membership, Organization, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
settings = get_settings()


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
        membership = db.execute(base_filter).scalar_one_or_none()
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
        membership = db.execute(base_filter).scalar_one_or_none()
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

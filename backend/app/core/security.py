import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["argon2", "pbkdf2_sha256"], deprecated="auto")
ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    # iat нужен, чтобы access-токен можно было массово отзывать (смена/сброс
    # пароля, удаление участника): deps.get_current_user сравнивает iat с
    # маркером user_tokens_revoked_at. Без iat отозвать access нельзя.
    payload: dict[str, Any] = {
        "sub": subject, "exp": expire, "type": "access", "iat": int(time.time()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(
    subject: str, expires_delta: timedelta | None = None, *, remember: bool = False
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.refresh_token_expire_minutes)
    )
    # `remember` survives refresh rotation: the /refresh endpoint reads it back
    # and re-mints with the same long lifetime + cookie max-age, so «Запомнить
    # меня» keeps the session alive for the full remember-window across refreshes.
    payload: dict[str, Any] = {
        "sub": subject, "exp": expire, "type": "refresh",
        "jti": str(uuid4()), "iat": int(time.time()), "remember": bool(remember),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])

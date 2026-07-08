from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    organization_name: str = Field(min_length=2, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)
    # «Запомнить меня»: True → длинная сессия (30 дней), иначе 7 дней.
    remember_me: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    message: str | None = None
    email_verification_required: bool = False


class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(max_length=256)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class AuthMessageResponse(BaseModel):
    message: str
    preview_url: str | None = None


# ── 152-ФЗ Subject Access Request / Right to Erasure ────────────────────
# ст. 14 ч. 7 — субъект имеет право получить все свои ПД от оператора.
# ст. 14 ч. 3 + ст. 21 — субъект имеет право требовать уничтожения ПД.
# Эти схемы используются эндпойнтами /auth/me/export и DELETE /auth/me.

class AccountDeleteRequest(BaseModel):
    """Право на удаление (ст. 21 152-ФЗ). Требует пароля как подтверждения —
    защита от случайного клика и от компрометированного access-токена."""
    password: str = Field(min_length=1, max_length=1024)
    # Free-text causa — попадёт в журнал обращений субъектов ПД, чтобы
    # при проверке РКН видно было основание (отзыв согласия / закрытие
    # бизнеса / прочее).
    reason: str = Field(default="", max_length=500)

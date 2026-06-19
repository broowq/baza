"""Symmetric encryption for secrets at rest (client SMTP/IMAP passwords).

Key is derived from settings.secret_key so we don't need a second secret. On
prod secret_key is a generated 32+ char value (deploy.sh), so the Fernet key is
strong. Rotating secret_key invalidates stored ciphertexts (decrypt returns "").
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    secret = (get_settings().secret_key or "").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret → urlsafe token string. Empty in → empty out."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a token → plaintext. Returns "" on any failure (bad/rotated key)."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""

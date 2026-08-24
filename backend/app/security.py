"""Security helpers: password hashing, JWT, and API key generation."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

_JWT_ISSUER = "humanllm"


# ----------------------------- Passwords -----------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> list[str]:
    """Return a list of human-readable policy violations (empty == OK).

    Policy is driven by ``settings`` so operators can relax it per deployment.
    """
    errors: list[str] = []
    if not isinstance(password, str) or len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"密码长度至少 {settings.PASSWORD_MIN_LENGTH} 位")
    if settings.PASSWORD_REQUIRE_UPPER and not re.search(r"[A-Z]", password or ""):
        errors.append("需包含大写字母")
    if settings.PASSWORD_REQUIRE_LOWER and not re.search(r"[a-z]", password or ""):
        errors.append("需包含小写字母")
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r"\d", password or ""):
        errors.append("需包含数字")
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(r"[^\w\s]", password or ""):
        errors.append("需包含特殊字符")
    return errors


# ------------------------------- JWT --------------------------------
def create_access_token(
    subject: str,
    role: str,
    expires_delta: int | None = None,
    token_version: int | None = None,
) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        seconds=expires_delta or settings.JWT_EXPIRE_SECONDS
    )
    payload = {
        "sub": subject,
        "role": role,
        "iss": _JWT_ISSUER,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
        "jti": secrets.token_hex(8),
    }
    if token_version is not None:
        payload["tv"] = token_version
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=_JWT_ISSUER,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    return payload


# ----------------------------- API keys -----------------------------
def generate_api_key() -> tuple[str, str]:
    """Return (full_key, prefix). The full key is shown once to the user."""
    raw = secrets.token_urlsafe(24)
    key = f"sk-human-{raw}"
    prefix = key[:18]
    return key, prefix


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def mask_api_key(key: str) -> str:
    return key[:10] + "..." + key[-4:] if len(key) > 14 else key


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

"""FastAPI dependencies: API-key auth, worker auth, admin auth."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ApiKey, User, UserRole, Worker, user_has_perm
from app.openai_errors import OpenAIError
from app.security import decode_access_token, hash_api_key


async def get_db() -> AsyncSession:
    async for s in get_session():
        yield s


def _bearer(token: str | None) -> str | None:
    if not token:
        return None
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


async def authenticate_api_key(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> ApiKey:
    """Validate the OpenAI-compatible Authorization header (Bearer sk-...)."""
    key = _bearer(authorization)
    if not key:
        raise OpenAIError(
            "You didn't provide an API key. "
            "You need to provide your API key in an Authorization header "
            "using Bearer auth (e.g. 'Authorization: Bearer sk-human-...').",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    hashed = hash_api_key(key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.is_active == True)  # noqa: E712
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise OpenAIError(
            "Incorrect API key provided.",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    # Mark last used.
    api_key.last_used_at = datetime.utcnow()
    await db.commit()
    # Validate owning user is active.
    user = await db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise OpenAIError(
            "The API key's owner account is inactive.",
            status_code=403,
            error_type="permission_error",
            code="account_inactive",
        )
    return api_key


async def get_worker_from_token(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Worker:
    """Resolve the human worker for an incoming request.

    Accepts a worker JWT (role == "worker", sub == worker id) or any dashboard
    user JWT (super_admin / staff / legacy admin) — every dashboard account owns
    a bound Worker (via Worker.owner_user_id) that it uses on the workbench.
    """
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    payload = decode_access_token(token)
    if payload is None or payload.get("sub") is None:
        raise HTTPException(status_code=401, detail="Invalid worker token")
    if payload.get("role") == "worker":
        worker = await db.get(Worker, int(payload["sub"]))
    else:
        # dashboard user: find the worker owned by this user
        result = await db.execute(select(Worker).where(Worker.owner_user_id == int(payload["sub"])))
        worker = result.scalar_one_or_none()
        # Revocation check for the owning user's JWT.
        owner = await db.get(User, int(payload["sub"]))
        if owner is None:
            raise HTTPException(status_code=401, detail="Invalid worker token")
        if payload.get("tv") != owner.token_version:
            raise HTTPException(status_code=401, detail="Token revoked. Please log in again.")
    if worker is None or not worker.is_active:
        raise HTTPException(status_code=401, detail="Worker not found or inactive")
    return worker


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Any authenticated, active dashboard user (super_admin or staff)."""
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    payload = decode_access_token(token)
    if payload is None or payload.get("sub") is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")
    # Token revocation: a bumped password invalidates all prior JWTs.
    if payload.get("tv") != user.token_version:
        raise HTTPException(status_code=401, detail="Token revoked. Please log in again.")
    return user


def require_permission(perm: str):
    """Dependency factory: grants access if the user has `perm`.

    super_admin always passes; staff must have `perm` in User.permissions.
    """

    async def checker(user: User = Depends(get_current_user)) -> User:
        if not user_has_perm(user, perm):
            raise HTTPException(status_code=403, detail=f"Permission required: {perm}")
        return user

    return checker


async def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


async def get_admin_from_token(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Backwards-compatible alias of require_super_admin."""
    return await require_super_admin(user=await get_current_user(authorization=authorization, db=db))


def get_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

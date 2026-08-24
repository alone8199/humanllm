"""Authentication for HumanLLM.

Two account tiers:
  - super_admin: full control (users, models, keys, everything).
  - staff: module access granted per-permission via User.permissions.

Any dashboard user logs in through ``/auth/login`` (alias ``/auth/admin/login``)
and receives a JWT carrying role + permissions. That JWT works for the
management API and for the workbench WebSocket (each user owns a bound Worker).
API consumers call ``/v1/*`` with an API key owned by a user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_guard
from app.config import settings
from app.database import get_session
from app.deps import get_ip
from app.models import ApiKey, User, UserRole
from app.ratelimit import limiter
from app.schemas import ApiKeyCreated, ApiKeyCreate, LoginRequest, TokenResponse
from app.security import (
    create_access_token,
    generate_api_key,
    hash_api_key,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


async def _require_super_admin(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
):
    from app.deps import _bearer, get_current_user

    user = await get_current_user(authorization=authorization, db=db)
    if user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


@router.post("/login", response_model=TokenResponse)
@router.post("/admin/login", response_model=TokenResponse)
async def admin_login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_session)):
    ip = get_ip(request)

    # 1) Per-IP login throttle (stop rapid guessing from one source).
    if settings.RATE_LIMIT_ENABLED:
        allowed, _rem, retry_after = limiter.check(
            f"login:ip:{ip}", settings.RATE_LOGIN_PER_MIN, 60
        )
        if not allowed:
            await auth_guard.log_event(db, "auth.login.ratelimited", body.username, {"ip": ip})
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    else:
        allowed, _rem, retry_after = True, 0, 0.0
    if not allowed:
        await auth_guard.log_event(db, "auth.login.ratelimited", body.username, {"ip": ip})
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    # 2) Account/IP lockout from prior cumulative failures.
    if auth_guard.is_locked(body.username, ip):
        await auth_guard.log_event(db, "auth.login.locked", body.username, {"ip": ip})
        raise HTTPException(
            status_code=429,
            detail="Account temporarily locked due to too many failed attempts. Try again later.",
        )

    user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    ok = (
        user is not None
        and user.role in (UserRole.super_admin, UserRole.staff)
        and user.is_active
        and verify_password(body.password, user.hashed_password)
    )
    if not ok:
        auth_guard.register_failure(body.username, ip)
        await auth_guard.log_event(
            db, "auth.login.failure", body.username,
            {"ip": ip, "user_exists": user is not None},
        )
        raise HTTPException(status_code=400, detail="Invalid credentials or account disabled.")

    # Success: clear failure counters and emit an audit event.
    auth_guard.register_success(body.username, ip)
    await auth_guard.log_event(db, "auth.login.success", body.username, {"ip": ip})
    token = create_access_token(
        str(user.id), user.role.value, token_version=user.token_version
    )
    return TokenResponse(
        access_token=token,
        role=user.role.value,
        username=user.username,
        permissions=user.permissions or ([] if user.role == UserRole.staff else None),
    )


@router.post("/user/apikeys", response_model=ApiKeyCreated)
async def create_api_key(
    body: ApiKeyCreate,
    user=Depends(_require_super_admin),
    db: AsyncSession = Depends(get_session),
):
    key, prefix = generate_api_key()
    rec = ApiKey(key_prefix=prefix, key_hash=hash_api_key(key), user_id=user.id, name=body.name)
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return ApiKeyCreated(id=rec.id, name=rec.name, key=key, key_prefix=prefix)

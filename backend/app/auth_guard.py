"""Login brute-force guard: per-IP + per-username failure tracking & lockout.

State is in-memory (single process). On ``LOGIN_MAX_FAIL`` cumulative failures
within the tracking window the account (and the source IP) is locked for
``LOGIN_LOCKOUT_SECONDS``. Successful logins clear the counters.

This pairs with ``app.ratelimit.limiter`` (which throttles *rate*) and with
``app.security`` (which validates *credentials*). Together they stop online
password guessing while staying dependency-free.
"""
from __future__ import annotations

import threading
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import EventLog

_lock = threading.Lock()
# key -> {"count": int, "locked_until": float}
_state: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def _key_user(username: str) -> str:
    return f"u:{username.lower()}"


def _key_ip(ip: str) -> str:
    return f"ip:{ip}"


def is_locked(username: str, ip: str) -> bool:
    now = _now()
    with _lock:
        for k in (_key_user(username), _key_ip(ip)):
            st = _state.get(k)
            if st and st["locked_until"] > now:
                return True
    return False


def register_failure(username: str, ip: str) -> None:
    """Record a failed attempt; lock the account/IP if the threshold is hit."""
    now = _now()
    with _lock:
        for k in (_key_user(username), _key_ip(ip)):
            st = _state.setdefault(k, {"count": 0, "locked_until": 0.0})
            st["count"] += 1
            if st["count"] >= settings.LOGIN_MAX_FAIL:
                st["locked_until"] = now + settings.LOGIN_LOCKOUT_SECONDS


def register_success(username: str, ip: str) -> None:
    with _lock:
        for k in (_key_user(username), _key_ip(ip)):
            _state.pop(k, None)


async def log_event(
    db: AsyncSession,
    kind: str,
    actor: str | None,
    detail: dict | None = None,
) -> None:
    """Best-effort audit log (does not raise on failure)."""
    try:
        db.add(EventLog(kind=kind, actor=actor, detail=detail))
        await db.commit()
    except Exception:  # noqa: BLE001
        # Never let audit logging break the auth flow.
        import logging

        logging.getLogger("humanllm.security").exception("audit log failed: %s", kind)

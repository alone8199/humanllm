"""Shared enums and permission helpers for the HumanLLM data model."""
from __future__ import annotations

import enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import User


class UserRole(str, enum.Enum):
    """Account roles used by the admin and worker authorization layers."""
    super_admin = "super_admin"
    staff = "staff"


# Granular permission bits (module-level access). User management is exclusive
# to super_admin and is intentionally not part of this list.
ALL_PERMISSIONS = [
    "overview",
    "workbench",
    "models",
    "apikeys",
    "tasks",
    "usage",
    "logs",
]


def user_has_perm(user: "User", perm: str) -> bool:
    """Return whether a user has the requested permission."""
    if user.role == UserRole.super_admin:
        return True
    if user.role == UserRole.staff:
        return perm in (user.permissions or [])
    return False


class WorkerStatus(str, enum.Enum):
    offline = "offline"
    online = "online"
    busy = "busy"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    assigned = "assigned"
    streaming = "streaming"
    waiting_tool = "waiting_tool"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"


class TransactionKind(str, enum.Enum):
    charge = "charge"
    preauth_hold = "preauth_hold"
    refund = "refund"
    worker_earning = "worker_earning"
    platform_commission = "platform_commission"
